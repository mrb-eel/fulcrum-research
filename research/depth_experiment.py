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
def simulate(paths, initial_c, initial_d, lltv, daily_budget, reserve, lag=0,
             fee=0.01, terminal_discount=0.01):
    """Rank eligible loans by LTV and allocate daily profitable repayment capacity."""
    count, steps = paths.shape
    accounts = len(initial_d)
    lif = 1 / (0.7 + 0.3 * lltv)
    losses = np.zeros(count)
    repayments = np.zeros(count)
    for path in prange(count):
        collateral = initial_c.copy()
        debt = initial_d.copy()
        order = np.empty(accounts, dtype=np.int64)
        ranks = np.empty(accounts, dtype=np.float64)
        writeoff = 0.0
        for day in range(1, steps):
            spot = paths[path, day]
            oracle = paths[path, max(0, day - lag)]
            budget = min(daily_budget, profitable_budget(lif, spot, oracle, reserve, fee))
            eligible = 0
            for i in range(accounts):
                if collateral[i] < 1e-8:
                    writeoff += debt[i]
                    debt[i] = 0
                elif budget > 0 and debt[i] > 1e-9 and collateral[i] * oracle * lltv < debt[i] - 1e-9:
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
                budget -= payment
                repayments[path] += payment
                collateral[i] = max(0.0, collateral[i] - payment * lif / oracle)
                debt[i] = max(0.0, debt[i] - payment)
                if collateral[i] < 1e-8:
                    writeoff += debt[i]
                    debt[i] = 0.0
        recovery_multiple = paths[path, -1] * (1 - terminal_discount)
        for i in range(accounts):
            writeoff += max(0.0, debt[i] - collateral[i] * recovery_multiple)
        losses[path] = writeoff
    return losses, repayments


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
