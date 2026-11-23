"""Reproduce the v1.2 terminal recovery and partial refill comparisons."""

import argparse
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from numba import get_num_threads, set_num_threads

from depth_experiment import archived_full_book_price, profitable_budget, simulate_recovery
from liquidation_study import describe
from reproduce import compare
from reproduce_revision import OUTPUT as PRICE_OUTPUT, main as reproduce_v11, read, save


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "generated/v1.2"
REFERENCE = HERE / "results/v1.2"
FEE = 0.01


def check_boundary():
    collateral = np.array([100.0, 100.0])
    debt = np.array([10.0, 100.0])
    price = archived_full_book_price(collateral, debt, 1.0, 100.0, 0.0, 0.0)
    np.testing.assert_allclose(price, 0.45)
    sale = np.minimum(collateral, debt / price)
    np.testing.assert_allclose((sale * price).sum(), 100 * sale.sum() / (100 + sale.sum()))
    np.testing.assert_allclose(debt - sale * price, [0.0, 55.0], atol=1e-12)
    assert archived_full_book_price(collateral, debt, 1.0, 100.0, 0.0, 20.0) < price

    paths = np.array([[1.0, 0.75, 0.75]])
    args = paths, np.array([100.0]), np.array([80.0]), 0.86, np.inf, 1e3
    full = simulate_recovery(*args)
    partial = simulate_recovery(*args, daily_refill=0.25)
    none = simulate_recovery(*args, daily_refill=0.0)
    assert full[2][0] > partial[2][0] > none[2][0] > 0
    np.testing.assert_allclose(full[3], full[2])
    np.testing.assert_allclose(full[4], full[2] * (1 / (0.7 + 0.3 * 0.86) - 1))
    unbounded = simulate_recovery(*args[:-1], np.inf)
    np.testing.assert_allclose(unbounded[0], unbounded[1])


def paired(changes):
    return {"mean": float(changes.mean()),
            "se": float(changes.std(ddof=1) / np.sqrt(len(changes)))}


def run(output: Path, prices: Path):
    set_num_threads(min(8, get_num_threads()))
    check_boundary()
    market = read(prices / "vault-study.json")["selected_market"]
    c = np.array([p["collateral_value"] for p in market["positions"]])
    d = np.array([p["debt"] for p in market["positions"]])
    with np.load(prices / "btc-price-paths.npz") as source:
        paths = source["prices"]
    if paths.shape != (100_000, 31) or not np.isfinite(paths).all() or not (paths > 0).all():
        raise ValueError("Expected the 100,000 common 30-day paths from the v1.1 replication.")
    initial_debt = float(d.sum())
    lltv = market["lltv"]
    lif = 1 / (0.7 + 0.3 * lltv)
    policies = [
        ("No liquidation, shallow", 0, 25e6, 0, 1.0),
        ("No liquidation, base", 0, 100e6, 0, 1.0),
        ("No liquidation, deep", 0, 400e6, 0, 1.0),
        ("No liquidation, no impact", 0, np.inf, 0, 1.0),
        ("1% daily cap", 0.01, 100e6, 0, 1.0),
        ("5% daily cap", 0.05, 100e6, 0, 1.0),
        ("Uncapped, base", np.inf, 100e6, 0, 1.0),
        ("Uncapped, shallow", np.inf, 25e6, 0, 1.0),
        ("Uncapped, deep", np.inf, 400e6, 0, 1.0),
        ("Uncapped, no impact", np.inf, np.inf, 0, 1.0),
        ("Uncapped, 25% refill", np.inf, 100e6, 0, 0.25),
        ("Uncapped, no refill", np.inf, 100e6, 0, 0.0),
        ("Uncapped, one-day lag", np.inf, 100e6, 1, 1.0),
    ]
    rows, outcomes, baselines = [], {}, {}
    for label, cap, reserve, lag, refill in policies:
        flat_loss, pool_loss, repaid, distressed, premium, written_off, _ = simulate_recovery(
            paths, c, d, lltv, cap * initial_debt, reserve, lag,
            fee=FEE, terminal_discount=FEE, daily_refill=refill, archived_full_book=True,
        )
        if not (np.all(pool_loss >= flat_loss - 1e-6) and np.all(pool_loss <= initial_debt + 1e-6)):
            raise ValueError(f"Terminal recovery or loss conservation failed for {label}.")
        if cap == 0:
            baselines[reserve] = flat_loss, pool_loss
        baseline_flat, baseline_pool = baselines[reserve]
        flat_delta = flat_loss - baseline_flat
        pool_delta = pool_loss - baseline_pool
        row = {"policy": label, "daily_cap_fraction": None if np.isinf(cap) else cap,
               "neutral_reserve_usdc": None if np.isinf(reserve) else reserve,
               "oracle_lag_days": lag, "daily_refill_fraction": refill,
               "flat_terminal": describe(flat_loss), "pool_terminal": describe(pool_loss),
               "flat_paired_vs_matched_control": paired(flat_delta),
               "pool_paired_vs_matched_control": paired(pool_delta),
               "mean_repaid": float(np.mean(repaid)),
               "mean_repaid_already_insolvent": float(np.mean(distressed)),
               "repayment_share_already_insolvent": float(distressed.sum() / repaid.sum()) if repaid.sum() else 0.0,
               "mean_spot_premium_already_insolvent": float(np.mean(premium)),
               "paths_with_insolvent_repayment": int(np.count_nonzero(distressed > 1e-8)),
               "mean_writeoff_before_terminal": float(np.mean(written_off))}
        rows.append(row)
        outcomes[label] = flat_loss, pool_loss
        print(f"{label}: flat {flat_loss.mean():,.2f}, pool {pool_loss.mean():,.2f}, "
              f"insolvent premium {premium.mean():,.2f} USDC", flush=True)

    depth_per_reserve = profitable_budget(lif, 1.0, 1.0, 1.0, FEE)
    reserve_thresholds = {str(cap): cap * initial_debt / depth_per_reserve for cap in (0.01, 0.05)}
    comparisons = {}
    for label in ("1% daily cap", "5% daily cap", "Uncapped, 25% refill",
                  "Uncapped, no refill", "Uncapped, one-day lag"):
        flat, pool = outcomes[label]
        clear_flat, clear_pool = outcomes["Uncapped, base"]
        comparisons[label] = {"flat_terminal": paired(flat - clear_flat),
                              "pool_terminal": paired(pool - clear_pool)}
    save(output / "settlement-study.json", {
        "paths": len(paths), "days": 30, "borrowers": len(d), "initial_debt_usdc": initial_debt,
        "lltv": lltv, "liquidation_incentive_factor": lif, "fee": FEE,
        "matched_spot_budget_per_reserve": depth_per_reserve,
        "matched_spot_reserve_thresholds_usdc": reserve_thresholds,
        "paired_vs_uncapped_base": comparisons, "rows": rows,
    })
    columns = ["policy", "neutral_reserve_usdc", "daily_cap_fraction", "daily_refill_fraction",
               "oracle_lag_days", "flat_mean_loss_usdc", "pool_mean_loss_usdc",
               "flat_paired_change_usdc", "flat_paired_se_usdc", "pool_paired_change_usdc",
               "pool_paired_se_usdc", "mean_repaid_already_insolvent_usdc",
               "mean_spot_premium_already_insolvent_usdc"]
    with (output / "settlement-policies.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        for row in rows:
            flat, pool = row["flat_paired_vs_matched_control"], row["pool_paired_vs_matched_control"]
            writer.writerow([
                row["policy"], row["neutral_reserve_usdc"], row["daily_cap_fraction"], row["daily_refill_fraction"],
                row["oracle_lag_days"], row["flat_terminal"]["mean"], row["pool_terminal"]["mean"],
                flat["mean"], flat["se"], pool["mean"], pool["se"],
                row["mean_repaid_already_insolvent"], row["mean_spot_premium_already_insolvent"],
            ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-paths", action="store_true", help="Use paths from a recent v1.1 replication.")
    args = parser.parse_args()
    if not args.reuse_paths:
        reproduce_v11()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=OUTPUT, prefix="run-") as directory:
        fresh = Path(directory)
        run(fresh, PRICE_OUTPUT)
        report = "settlement-study.json"
        compare(read(REFERENCE / report), read(fresh / report), report, relative=2e-6, absolute=1e-7)
        print(f"Matched {report}")
        for file in fresh.iterdir():
            file.replace(OUTPUT / file.name)


if __name__ == "__main__":
    main()
