"""Regenerate the expanded experiments and recorded fork accounting for paper v1.1."""

import csv
import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from empirical_models import run as fit_models
from reproduce import compare
from vault_study import run as rebuild_vaults


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUTPUT = HERE / "generated/v1.1"
REFERENCE = HERE / "results/v1.1"
REPORTS = ("model-results.json", "test-forecasts.json", "depth-study.json",
           "historical-btc-barriers.json", "fork-costs.json", "historical-btc-windows.csv")
PATHS = 100_000
DECAYS = (0.90, 0.94, 0.97, 0.98, 0.985, 0.99, 0.9925, 0.995, 0.997, 0.999, 0.9995, 0.9999)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(target, value):
    target.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def historical_barriers(output):
    """For each origin close, compare the next 30 UTC lows and closes."""
    source = HERE / "raw/bitstamp-btcusd-daily.json"
    records = read(source)["bars"]
    frozen = read(ROOT / "data/book/market-history.json")["snapshot"]["series"]["btcusd"]["closes"]
    archived = {int(day): float(close) for day, close in frozen}
    times = [int(row["timestamp"]) for row in records]
    assert len(records) == 2923 and all(b - a == 86400 for a, b in zip(times, times[1:]))
    closes = [float(row["close"]) for row in records]
    lows = [float(row["low"]) for row in records]
    close_differences = [abs(c - archived[t]) for c, t in zip(closes, times)]
    if max(close_differences) > 1e-8:
        raise ValueError(f"OHLC closes differ from the original series (max {max(close_differences)}).")
    assert all(0 < low <= close for low, close in zip(lows, closes))
    stamp = lambda t: datetime.fromtimestamp(t, UTC).date().isoformat()
    results = []
    for i in range(len(closes) - 30):
        threshold = 0.65 * closes[i]
        close_min = min(closes[i + 1:i + 31])
        low_min = min(lows[i + 1:i + 31])
        results.append({"anchor_bucket": stamp(times[i]), "last_bucket": stamp(times[i + 30]),
                        "close_hit": close_min <= threshold, "low_hit": low_min <= threshold,
                        "minimum_close_ratio": close_min / closes[i], "minimum_low_ratio": low_min / closes[i]})
    with (output / "historical-btc-windows.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    close_hits = sum(row["close_hit"] for row in results)
    low_hits = sum(row["low_hit"] for row in results)
    def groups(key):
        return sum(row[key] and (i == 0 or not results[i - 1][key]) for i, row in enumerate(results))
    save(output / "historical-btc-barriers.json", {
        "rows": len(records), "windows": len(results), "anchor_from": results[0]["anchor_bucket"],
        "last_bucket": results[-1]["last_bucket"], "close_hits": close_hits,
        "low_hits": low_hits, "low_only_hits": low_hits - close_hits,
        "close_hit_frequency": close_hits / len(results), "low_hit_frequency": low_hits / len(results),
        "close_hit_runs": groups("close_hit"), "low_hit_runs": groups("low_hit"),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    })


def fork_costs(output):
    raw = read(HERE / "raw/fork-replay-curve.json")
    anchor = raw["anchor"]
    loan_unit = 10**6
    lltv = 0.915
    price = anchor["oracle_price"]
    before_debt = anchor["expected_borrow_assets_atomic"] / loan_unit
    before_value = anchor["oracle_collateral_atomic"] / loan_unit
    before_equity = before_value - before_debt
    rows = []
    for attempt in raw["attempts"]:
        if not attempt["success"]:
            continue
        log = next(log for log in attempt["logs"] if log["address"].lower() == attempt["helper"].lower()
                   and len(log["data"]) == 386)
        values = [int(log["data"][i:i + 64], 16) for i in range(2, len(log["data"]), 64)]
        quantity, proceeds = values[:2]
        oracle_sale_mark = (quantity * price // 10**36) / loan_unit
        after_value = (attempt["final_position"][2] * price // 10**36) / loan_unit
        after_debt = attempt["final_debt_atomic"] / loan_unit
        after_equity = after_value - after_debt
        after_health = lltv * after_value / after_debt
        assert abs(after_health - attempt["final_health_using_anchor_oracle"]) < 1e-10
        rows.append({"fraction": attempt["fraction"], "pt_sold": quantity / 10**18,
                     "marked_pt_usdc": oracle_sale_mark, "proceeds_usdc": proceeds / loan_unit,
                     "sale_discount": 1 - proceeds / loan_unit / oracle_sale_mark,
                     "health_at_anchor_mark": after_health, "health_change": after_health - anchor["health"],
                     "equity_at_anchor_mark_usdc": after_equity, "equity_change_usdc": after_equity - before_equity,
                     "equity_change_ratio": (after_equity - before_equity) / before_equity,
                     "gas_used": int(attempt["receipt"]["gasUsed"], 16)})
    packet = read(next((ROOT / "data/snapshots").glob("*dab2ca7e9ba2a333-*.json")))
    quotes = packet["snapshot"]["rawInputs"]["exitQuotes"]
    quote = next(q for q in quotes if q["fraction"] == 1)
    aggregator = int(quote["output"]["amount"]) / loan_unit
    assert len(rows) == 2 and aggregator > max(row["proceeds_usdc"] for row in rows)
    save(output / "fork-costs.json", {"anchor_block": anchor["anchor_block"], "opening_health": anchor["health"],
         "opening_equity_usdc": before_equity, "full_aggregator_quote_usdc": aggregator,
         "full_aggregator_quote_discount": 1 - aggregator / before_value, "executions": rows})


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    from depth_experiment import run
    if not REFERENCE.is_dir():
        raise ValueError(f"Expected the paper's published reference outputs in {REFERENCE}.")
    with tempfile.TemporaryDirectory(dir=OUTPUT, prefix="run-") as directory:
        fresh = Path(directory)
        historical_barriers(fresh)
        fork_costs(fresh)
        rebuild_vaults(fresh)
        fit_models(fresh, decay_grid=DECAYS, path_count=PATHS)
        run(fresh)
        for name in REPORTS:
            expected, actual = REFERENCE / name, fresh / name
            if name.endswith('.csv'):
                if expected.read_text(encoding='utf-8') != actual.read_text(encoding='utf-8'):
                    raise ValueError(f"Historical window calculation differs in {name}.")
            else:
                tolerance = 2e-6 if name in {'model-results.json', 'test-forecasts.json', 'depth-study.json'} else 1e-10
                compare(read(expected), read(actual), name, relative=tolerance, absolute=1e-8)
            print(f"Matched {name}", flush=True)
        for file in fresh.iterdir():
            file.replace(OUTPUT / file.name)


if __name__ == "__main__":
    main()
