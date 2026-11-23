"""Compare daily liquidation policies under an explicit constant-product depth curve."""

import json
from pathlib import Path

import numpy as np
from numba import get_num_threads, njit, prange, set_num_threads

from liquidation_study import describe


@njit
def profitable_budget(lif, spot, oracle, reserve, fee):
    spot_value_per_repaid = lif * spot / oracle
    net_share = 1 - fee
    marginal_multiple = net_share * spot_value_per_repaid
    if marginal_multiple <= 1:
        return 0.0
    if np.isinf(reserve):
        return np.inf
    return reserve * (np.sqrt(marginal_multiple) - 1) / marginal_multiple


@njit(parallel=True)
def simulate_recovery(paths, initial_c, initial_d, lltv, daily_budget, reserve, lag=0,
                      fee=0.01, terminal_discount=0.01, daily_refill=1.0,
                      steps_per_day=1, oracle_multiplier=1.0, rescue_fraction=0.0,
                      archived_full_book=False, oracle_paths=None, account_repaid=None):
    """Return path losses under both terminal conventions and execution totals."""
    count, steps = paths.shape
    accounts = len(initial_d)
    lif = 1 / (0.7 + 0.3 * lltv)
    flat_losses = np.zeros(count)
    pool_losses = np.zeros(count)
    repayments = np.zeros(count)
    underwater_repayments = np.zeros(count)
    underwater_premiums = np.zeros(count)
    cumulative_writeoffs = np.zeros(count)
    borrower_repayments = np.zeros(count)
    for path in prange(count):
        collateral = initial_c.copy()
        debt = initial_d.copy()
        order = np.empty(accounts, dtype=np.int64)
        ranks = np.empty(accounts, dtype=np.float64)
        writeoff = 0.0
        inventory = 0.0
        remaining_daily = daily_budget
        outside_cash = initial_d * rescue_fraction
        for step in range(1, steps):
            spot = paths[path, step]
            marked_at = max(0, step - lag)
            oracle = (paths[path, marked_at] if oracle_paths is None else oracle_paths[path, marked_at]) * oracle_multiplier
            if (step - 1) % steps_per_day == 0:
                inventory *= 1 - daily_refill
                remaining_daily = daily_budget
            net_collateral_per_repaid = (1 - fee) * lif / oracle
            if inventory == 0.0 or np.isinf(reserve):
                depth_budget = profitable_budget(lif, spot, oracle, reserve, fee)
            else:
                neutral_collateral = reserve / spot
                pool_product = reserve * neutral_collateral
                break_even_reserve = np.sqrt(pool_product * net_collateral_per_repaid)
                depth_budget = max(0.0, (break_even_reserve - neutral_collateral - inventory)
                                   / net_collateral_per_repaid)
            budget = min(remaining_daily, depth_budget)
            eligible = 0
            for i in range(accounts):
                oracle_limit = collateral[i] * oracle * lltv
                if outside_cash[i] > 0 and debt[i] > oracle_limit + 1e-9:
                    own_payment = min(outside_cash[i], debt[i] - oracle_limit)
                    debt[i] -= own_payment
                    outside_cash[i] -= own_payment
                    borrower_repayments[path] += own_payment
                if collateral[i] < 1e-8:
                    writeoff += debt[i]
                    debt[i] = 0
                elif budget > 0 and debt[i] > 1e-9 and oracle_limit < debt[i] - 1e-9:
                    rank = debt[i] / collateral[i]
                    at = eligible
                    while at > 0 and ranks[at - 1] < rank:
                        ranks[at] = ranks[at - 1]
                        order[at] = order[at - 1]
                        at -= 1
                    ranks[at] = rank
                    order[at] = i
                    eligible += 1
            for place in range(eligible):
                if budget <= 1e-9:
                    break
                i = order[place]
                payment = min(budget, debt[i], collateral[i] * oracle / lif)
                seized = payment * lif / oracle
                if collateral[i] * spot < debt[i] - 1e-9:
                    underwater_repayments[path] += payment
                    underwater_premiums[path] += max(0.0, seized * spot - payment)
                budget -= payment
                remaining_daily -= payment
                repayments[path] += payment
                if account_repaid is not None:
                    account_repaid[path, i] += payment
                if not np.isinf(reserve):
                    inventory += (1 - fee) * seized
                collateral[i] = max(0.0, collateral[i] - seized)
                debt[i] = max(0.0, debt[i] - payment)
                if collateral[i] < 1e-8:
                    writeoff += debt[i]
                    debt[i] = 0.0
        spot = paths[path, -1]
        recovery_multiple = spot * (1 - terminal_discount)
        if archived_full_book:
            batch_price = archived_full_book_price(collateral, debt, spot, reserve, fee, inventory)
        else:
            batch_price = terminal_batch_price(collateral, debt, spot, reserve, fee, inventory)
        flat_losses[path] = writeoff
        pool_losses[path] = writeoff
        cumulative_writeoffs[path] = writeoff
        for i in range(accounts):
            if not archived_full_book and collateral[i] * spot >= debt[i] - 1e-9:
                continue
            flat_losses[path] += max(0.0, debt[i] - collateral[i] * recovery_multiple)
            pool_losses[path] += max(0.0, debt[i] - collateral[i] * batch_price)
    return (flat_losses, pool_losses, repayments, underwater_repayments,
            underwater_premiums, cumulative_writeoffs, borrower_repayments)


@njit
def terminal_batch_price(collateral, debt, spot, reserve, fee, inventory):
    """Pro-rata execution price for selling the collateral of spot-insolvent loans."""
    if np.isinf(reserve):
        return spot * (1 - fee)
    forced_inventory = 0.0
    for i in range(len(debt)):
        if collateral[i] * spot < debt[i] - 1e-9:
            forced_inventory += collateral[i]
    neutral_collateral = reserve / spot
    available_collateral = neutral_collateral + inventory
    available_loan = reserve * neutral_collateral / available_collateral
    return available_loan * (1 - fee) / (available_collateral + (1 - fee) * forced_inventory)


@njit
def archived_full_book_price(collateral, debt, spot, reserve, fee, inventory):
    """Withdrawn v1.2 convention, kept solely to reproduce that archived edition."""
    fee_multiplier = 1 - fee
    if np.isinf(reserve):
        return spot * fee_multiplier
    neutral_collateral = reserve / spot
    available_collateral = neutral_collateral + inventory
    available_loan = reserve * neutral_collateral / available_collateral
    slope_scale = fee_multiplier / available_collateral
    zero_size_bid = available_loan * slope_scale

    # For p >= 0, F(p) = p + slope_scale * sum(min(D_i, p*C_i)) is
    # increasing and concave. Newton iterations from zero approach its root
    # from below, and finish as soon as the set of fully repayable loans settles.
    price = 0.0
    for _ in range(64):
        recovered = 0.0
        slope = 1.0
        for i in range(len(debt)):
            marked = price * collateral[i]
            if marked < debt[i]:
                recovered += marked
                slope += slope_scale * collateral[i]
            else:
                recovered += debt[i]
        increment = (zero_size_bid - price - slope_scale * recovered) / slope
        if abs(increment) <= zero_size_bid * 1e-13:
            return min(zero_size_bid, price + increment)
        price += increment

    lower, upper = 0.0, zero_size_bid
    for _ in range(48):
        price = (lower + upper) / 2
        recovered = 0.0
        for i in range(len(debt)):
            recovered += min(debt[i], price * collateral[i])
        if price + slope_scale * recovered < zero_size_bid:
            lower = price
        else:
            upper = price
    return (lower + upper) / 2


def simulate(paths, initial_c, initial_d, lltv, daily_budget, reserve, lag=0,
             fee=0.01, terminal_discount=0.01):
    """Reproduce the v1.1 flat-salvage comparison."""
    flat, _, repayments, _, _, _, _ = simulate_recovery(
        paths, initial_c, initial_d, lltv, daily_budget, reserve, lag, fee, terminal_discount,
        archived_full_book=True,
    )
    return flat, repayments


def check_boundary():
    from liquidation_study import simulate as baseline

    paths = np.array([[1, 0.9, 0.8], [1, 0.8, 0.8], [1, 1.1, 1.2]])
    c = np.array([100.0, 200.0])
    d = np.array([80.0, 140.0])
    for limit in (0, 0.05, np.inf):
        actual, repaid = simulate(paths, c, d, 0.86, limit * d.sum(), np.inf)
        expected = baseline(paths, c, d, 0.86, limit)
        np.testing.assert_allclose(actual, expected["loss"], atol=1e-9)
        np.testing.assert_allclose(repaid, expected["repaid"], atol=1e-9)
    lif, reserve, fee = 1 / (0.7 + 0.3 * 0.86), 25e6, 0.01
    budget = profitable_budget(lif, 1.0, 1.0, reserve, fee)
    marginal_multiple = (1 - fee) * lif / (1 + (1 - fee) * lif * budget / reserve) ** 2
    np.testing.assert_allclose(marginal_multiple, 1.0)
    assert profitable_budget(lif, 0.9, 1.0, reserve, fee) == 0


def run(output: Path):
    set_num_threads(min(8, get_num_threads()))
    check_boundary()
    study = json.loads((output / "vault-study.json").read_text(encoding="utf-8"))
    market = study["selected_market"]
    c = np.array([p["collateral_value"] for p in market["positions"]])
    d = np.array([p["debt"] for p in market["positions"]])
    with np.load(output / "btc-price-paths.npz") as source:
        paths = source["prices"]
    if paths.shape[1] != 31 or len(paths) < 100_000 or not np.isfinite(paths).all() or not (paths > 0).all():
        raise ValueError("Expected at least 100,000 valid 30-day price paths.")
    policies = [
        ("No liquidation", 0, 100e6, 0),
        ("1% daily cap", 0.01, 100e6, 0),
        ("5% daily cap", 0.05, 100e6, 0),
        ("No daily cap", np.inf, 100e6, 0),
        ("No daily cap, shallow pool", np.inf, 25e6, 0),
        ("No daily cap, deep pool", np.inf, 400e6, 0),
        ("No daily cap, no impact", np.inf, np.inf, 0),
        ("No daily cap, one-day lag", np.inf, 100e6, 1),
    ]
    rows, retained = [], {}
    for label, cap, reserve, lag in policies:
        loss, repaid = simulate(paths, c, d, market["lltv"], cap * d.sum(), reserve, lag)
        retained[label] = loss
        difference = loss - retained["No liquidation"]
        row = {"policy": label, "cap_fraction": None if np.isinf(cap) else cap,
               "loan_reserve_usdc": None if np.isinf(reserve) else reserve,
               "oracle_lag_days": lag, **describe(loss),
               "positive_loss_paths": int((loss > 1e-6).sum()),
               "intervention_probability": float((repaid > 1e-8).mean()),
               "mean_repayment": float(repaid.mean()),
               "paired_mean_difference": float(difference.mean()),
               "paired_mean_se": float(difference.std(ddof=1) / np.sqrt(len(paths)))}
        rows.append(row)
        print(f"{label}: {row['mean']:.2f} USDC mean, {row['positive_loss_paths']} positive paths", flush=True)
    cap_comparison = retained["5% daily cap"] - retained["1% daily cap"]
    reference_budget = profitable_budget(1 / (0.7 + 0.3 * market["lltv"]), 1.0, 1.0, 100e6, 0.01)
    (output / "depth-study.json").write_text(json.dumps({
        "paths": len(paths), "days": 30, "borrowers": len(d), "initial_debt": float(d.sum()),
        "market_id": market["market_id"], "lltv": market["lltv"],
        "execution_fee": 0.01, "terminal_recovery_discount": 0.01,
        "matched_spot_reference_budget_usdc": reference_budget,
        "five_minus_one_pct_cap": {"mean_difference": float(cap_comparison.mean()),
                                   "paired_se": float(cap_comparison.std(ddof=1) / np.sqrt(len(paths))),
                                   "paths_changed": int(np.count_nonzero(cap_comparison))},
        "rows": rows,
    }, indent=2), encoding="utf-8")
    np.savez_compressed(output / "depth-path-losses.npz", **retained)
