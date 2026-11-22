"""Finite-throughput liquidation experiments on a reconciled historical borrower book."""

import csv
import json
from pathlib import Path

import numpy as np


def simulate(
    prices,
    c0,
    d0,
    lltv,
    capacity_fraction,
    lag=0,
    discount=0.01,
    annual_borrow_rate=0,
    priority="ltv",
):
    prices = np.asarray(prices, dtype=float)
    n, h = prices.shape
    h -= 1
    c = np.broadcast_to(np.asarray(c0, dtype=float), (n, len(c0))).copy()
    d = np.broadcast_to(np.asarray(d0, dtype=float), c.shape).copy()
    initial_debt = float(np.sum(d0))
    lif = 1 / (0.7 + 0.3 * lltv)
    writeoff = np.zeros(n)
    repaid = np.zeros(n)
    any_liquidation = np.zeros(n, dtype=bool)
    peak = np.zeros(n)
    for t in range(1, h + 1):
        if annual_borrow_rate:
            d *= np.exp(annual_borrow_rate / 365)
        spot = prices[:, t]
        oracle = prices[:, max(0, t - lag)]
        healthy = c * oracle[:, None] * lltv >= d - 1e-9
        profitable = lif * (spot / oracle) * (1 - discount) > 1
        eligible = (~healthy) & profitable[:, None] & (d > 1e-9) & (c > 1e-9)
        desired = np.where(eligible, np.minimum(d, c * oracle[:, None] / lif), 0)
        if np.isinf(capacity_fraction):
            payment = desired
        else:
            rank = (
                np.divide(d, c, out=np.full_like(d, np.inf), where=c > 1e-12)
                if priority == "ltv"
                else d
            )
            order = np.argsort(-rank, axis=1, kind="stable")
            demand = np.take_along_axis(desired, order, axis=1)
            before = np.cumsum(demand, axis=1) - demand
            payment_rank = np.minimum(
                demand, np.maximum(0, capacity_fraction * initial_debt - before)
            )
            payment = np.zeros_like(payment_rank)
            np.put_along_axis(payment, order, payment_rank, axis=1)
        seized = payment * lif / oracle[:, None]
        c = np.maximum(0, c - seized)
        d = np.maximum(0, d - payment)
        exhausted = c < 1e-8
        writeoff += np.where(exhausted, d, 0).sum(axis=1)
        d = np.where(exhausted, 0, d)
        flow = payment.sum(axis=1)
        repaid += flow
        peak = np.maximum(peak, flow)
        any_liquidation |= flow > 1e-8
        assert np.all(c >= 0) and np.all(d >= 0)
    terminal = np.maximum(0, d - c * prices[:, -1, None] * (1 - discount)).sum(axis=1)
    loss = writeoff + terminal
    return {
        "loss": loss,
        "realised_writeoff": writeoff,
        "terminal_uncovered_debt": terminal,
        "repaid": repaid,
        "any_liquidation": any_liquidation,
        "peak_repayment": peak,
    }


def self_test():
    # Healthy path preserves the frozen debt and collateral.
    r = simulate([[1, 1, 1]], [100], [70], 0.86, np.inf)
    assert r["loss"][0] == 0 and r["repaid"][0] == 0
    # Prompt full liquidation at 0.90 pays an 80-unit loan in full.
    r = simulate([[1, 0.9, 0.8]], [100], [80], 0.86, np.inf)
    assert abs(r["repaid"][0] - 80) < 1e-9 and r["loss"][0] < 1e-9
    # A direct fall to 0.80 exhausts collateral before repaying all debt.
    lif = 1 / (0.7 + 0.3 * 0.86)
    r = simulate([[1, 0.8]], [100], [80], 0.86, np.inf)
    assert abs(r["loss"][0] - (80 - 80 / lif)) < 1e-8
    # Zero transaction capacity reproduces terminal account-level shortfall.
    p = np.array([[1, 0.8, 0.7], [1, 1.1, 1.2]])
    r = simulate(p, [100, 200], [80, 100], 0.86, 0)
    expected = np.maximum(
        0, np.array([80, 100]) - np.array([100, 200]) * p[:, -1, None] * 0.99
    ).sum(axis=1)
    assert np.allclose(r["loss"], expected)
    # A stale high oracle and an unprofitable purchase defer liquidation.
    r = simulate([[1, 0.8]], [100], [80], 0.86, np.inf, lag=1)
    assert r["repaid"][0] == 0 and abs(r["loss"][0] - 0.8) < 1e-8
    print("Five liquidation conservation and boundary checks passed.")


def describe(x):
    x = np.asarray(x)
    q = float(np.quantile(x, 0.99))
    tail = np.sort(x)[-max(1, int(np.ceil(0.01 * len(x)))) :]
    return {
        "mean": float(x.mean()),
        "mean_mc_se": float(x.std(ddof=1) / np.sqrt(len(x))),
        "loss_probability": float(np.mean(x > 1e-6)),
        "loss_probability_mc_se": float(
            np.sqrt(np.mean(x > 1e-6) * (1 - np.mean(x > 1e-6)) / len(x))
        ),
        "var_99": q,
        "es_99": float(tail.mean()) if len(tail) else 0,
        "maximum": float(x.max()),
    }


def run(path: Path, output: Path, n: int = 5000):
    with np.load(path) as data:
        prices = np.asarray(data["prices"])[:n]
    if len(prices) != n:
        raise ValueError(f"Expected at least {n} paths, found {len(prices)}")
    assert prices.ndim == 2 and prices.shape[1] == 31 and np.all(prices > 0)
    if not np.allclose(prices[:, 0], 1):
        prices = prices / prices[:, 0, None]
    study = json.loads((output / "vault-study.json").read_text(encoding="utf-8"))
    m = study["selected_market"]
    c0 = [x["collateral_value"] for x in m["positions"]]
    d0 = [x["debt"] for x in m["positions"]]
    rows = []
    raw = {}
    settings = [
        (0, 0, 0.01, 0, "ltv"),
        (0.01, 0, 0.01, 0, "ltv"),
        (0.05, 0, 0.01, 0, "ltv"),
        (np.inf, 0, 0.01, 0, "ltv"),
        (0.05, 1, 0.01, 0, "ltv"),
        (0.05, 0, 0.04, 0, "ltv"),
        (0.05, 0, 0.05, 0, "ltv"),
        (0.05, 0, 0.01, 0.10, "ltv"),
        (0.05, 0, 0.01, 0, "debt"),
    ]
    reference = None
    for cap, lag, discount, apr, priority in settings:
        name = f"cap={cap};lag={lag};discount={discount};apr={apr};priority={priority}"
        r = simulate(prices, c0, d0, m["lltv"], cap, lag, discount, apr, priority)
        desc = describe(r["loss"])
        if reference is None:
            reference = r["loss"].copy()
        difference = r["loss"] - reference
        row = {
            "capacity_fraction_per_day": None if np.isinf(cap) else cap,
            "oracle_lag_days": lag,
            "sale_discount": discount,
            "annual_borrow_rate": apr,
            "priority": priority,
            **desc,
            "liquidation_probability": float(r["any_liquidation"].mean()),
            "mean_repaid": float(r["repaid"].mean()),
            "mean_difference_from_zero_capacity": float(difference.mean()),
            "paired_difference_mc_se": float(
                difference.std(ddof=1) / np.sqrt(len(difference))
            ),
        }
        rows.append(row)
        raw[name] = r["loss"]
    np.savez_compressed(output / "liquidation-path-losses.npz", **raw)
    report = {
        "market": m["market_id"],
        "borrowers": len(c0),
        "initial_debt": m["debt"],
        "lltv": m["lltv"],
        "lif": 1 / (0.7 + 0.3 * m["lltv"]),
        "paths": len(prices),
        "horizon_days": 30,
        "price_paths_file": path.name,
        "policy": "Each day accrued debt, oracle update, profitability check, ranked capacity allocation, proportional collateral seizure, and exhausted-collateral writeoff. Terminal uncovered debt is added to recorded writeoff.",
        "capacity": "Exogenous loan-token repayment per day as fraction of initial debt. Common paths used for all policy comparisons.",
        "rows": rows,
    }
    (output / "liquidation-study.json").write_text(json.dumps(report, indent=2))
    with (output / "liquidation-study.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0])
        w.writeheader()
        w.writerows(rows)
