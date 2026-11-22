"""Borrower-level audit of the ten retained Fulcrum vault packets."""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/book"


def factor(symbol):
    s = symbol.upper()
    if s in {"WBTC", "CBBTC", "TBTC", "LBTC", "BTC"}:
        return "BTC"
    if s in {
        "WETH",
        "ETH",
        "WEETH",
        "WSTETH",
        "STETH",
        "RSETH",
        "EZETH",
        "RETH",
        "OSETH",
    }:
        return "ETH"
    return "other"


def credit_loss(m, shock, discount):
    cfac = (1 - shock) if m["factor"] in {"BTC", "ETH"} else 1
    lfac = (1 - shock) if m["loan_factor"] in {"BTC", "ETH"} else 1
    ratio = cfac / lfac
    return sum(
        max(0, p["debt"] - p["collateral_value"] * ratio * (1 - discount))
        for p in m["positions"]
    )


def run(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    packets = []
    for p in sorted(RAW.glob("*.json")):
        try:
            o = json.loads(p.read_text(encoding="utf-8"))
            s = o.get("snapshot", {})
        except Exception:
            continue
        if s.get("schemaVersion") == "fulcrum-vault-evidence/v1":
            packets.append((p, s))
    assert len(packets) == 10, len(packets)
    markets = {}
    vaults = []
    allocations = []
    for p, s in sorted(packets, key=lambda pair: pair[1]["capturedAt"]):
        v = s["vault"]
        vs = v["state"]
        allocs = []
        for a in vs["allocation"]:
            if not a or not a.get("market") or int(a["supplyAssets"]) == 0:
                continue
            m = a["market"]
            mid = m["marketId"].lower()
            b = s["borrowers"].get(m["marketId"]) or s["borrowers"].get(mid) or {}
            items = b.get("items", [])
            if mid not in markets or (
                bool(b.get("complete")) and not markets[mid]["complete"]
            ):
                ms = m["state"]
                dec = m["loanAsset"]["decimals"]
                den = 10**dec
                total_shares = int(ms["borrowShares"])
                observed = sum(int(i["state"]["borrowShares"]) for i in items)
                debt_sum = sum(int(i["state"]["borrowAssets"]) for i in items)
                rate = a["supplyAssetsUsd"] / (int(a["supplyAssets"]) / den)
                markets[mid] = {
                    "market_id": mid,
                    "source_file": p.name,
                    "capture_time": s["capturedAt"],
                    "market_block": ms.get("blockNumber"),
                    "collateral": (m.get("collateralAsset") or {"symbol": "cash"})[
                        "symbol"
                    ],
                    "loan": m["loanAsset"]["symbol"],
                    "factor": factor(
                        (m.get("collateralAsset") or {"symbol": "cash"})["symbol"]
                    ),
                    "loan_factor": factor(m["loanAsset"]["symbol"]),
                    "lltv": int(m["lltv"]) / 1e18,
                    "supply": int(ms["supplyAssets"]) / den,
                    "debt": int(ms["borrowAssets"]) / den,
                    "loan_usd_mark": rate,
                    "complete": bool(b.get("complete")),
                    "borrowers": len(items),
                    "sum_borrow_shares": observed,
                    "total_borrow_shares": total_shares,
                    "share_coverage": observed / total_shares if total_shares else 1,
                    "borrow_assets_sum": debt_sum / den,
                    "positions": [
                        {
                            "account": i["user"]["address"].lower(),
                            "debt": int(i["state"]["borrowAssets"]) / den,
                            "collateral_value": int(i["state"]["collateralValue"])
                            / den,
                            "shares": int(i["state"]["borrowShares"]),
                        }
                        for i in items
                    ],
                }
            alloc = {
                "vault": v["name"],
                "market_id": mid,
                "supply": int(a["supplyAssets"]) / 10 ** v["asset"]["decimals"],
                "supply_usd": a["supplyAssetsUsd"],
            }
            allocs.append(alloc)
            allocations.append(alloc)
        vaults.append(
            {
                "name": v["name"],
                "address": v["address"],
                "asset": v["asset"]["symbol"],
                "source_file": p.name,
                "capture_time": s["capturedAt"],
                "vault_block": vs["blockNumber"],
                "total_assets_usd": vs["totalAssetsUsd"],
                "allocated_usd": sum(a["supply_usd"] for a in allocs),
                "markets": len(allocs),
                "allocations": allocs,
                "warning_count": len(s.get("warnings", [])),
            }
        )
    for m in markets.values():
        ds = sorted((p["debt"] for p in m["positions"]), reverse=True)
        total = sum(ds)
        m["top_borrower_share"] = ds[0] / total if total else 0
        m["hhi"] = sum((d / total) ** 2 for d in ds) if total else 0
        m["baseline_shortfall"] = credit_loss(m, 0, 0)
        m["stress_35pct_discount_1pct"] = credit_loss(m, 0.35, 0.01)
    for v in vaults:
        loss = 0
        eligible = 0
        for a in v["allocations"]:
            m = markets[a["market_id"]]
            if m["supply"] <= 0:
                continue
            contribution = (
                max(0, m["stress_35pct_discount_1pct"] - m["baseline_shortfall"])
                * min(1, a["supply"] / m["supply"])
                * m["loan_usd_mark"]
            )
            loss += contribution
            if m["factor"] in {"BTC", "ETH"}:
                eligible += a["supply_usd"]
        v["shock_exposed_supply_fraction"] = eligible / v["total_assets_usd"]
        v["static_stress_loss_usd"] = loss
        v["hypothetical_million_deposit_loss_usd"] = loss / v["total_assets_usd"] * 1e6
    candidates = [
        m
        for m in markets.values()
        if m["collateral"] == "WBTC"
        and m["loan"] == "USDC"
        and m["complete"]
        and abs(m["share_coverage"] - 1) < 0.001
    ]
    assert candidates, "No complete WBTC/USDC market"
    selected = max(candidates, key=lambda m: m["debt"])
    curve = []
    for shock_int in range(0, 61):
        shock = shock_int / 100
        for discount in [0, 0.01, 0.04, 0.05]:
            account = credit_loss(selected, shock, discount)
            pooled = max(
                0,
                sum(p["debt"] for p in selected["positions"])
                - sum(p["collateral_value"] for p in selected["positions"])
                * (1 - shock)
                * (1 - discount),
            )
            curve.append(
                {
                    "shock": shock,
                    "sale_discount": discount,
                    "account_shortfall": account,
                    "pooled_shortfall": pooled,
                    "shortfall_fraction_of_debt": account / selected["debt"],
                }
            )
    result = {
        "selection": "Ten retained vault packets from Fulcrum data/book; positive supply allocations; complete borrower captures take precedence, then earliest capture for a repeated market; market position consists of market id and borrower address. This is a purposive historical sample.",
        "capture_from": min(s["capturedAt"] for _, s in packets),
        "capture_to": max(s["capturedAt"] for _, s in packets),
        "vault_count": len(vaults),
        "unique_markets": len(markets),
        "configured_market_records": len(
            {
                a["market"]["marketId"]
                for _, s in packets
                for a in s["vault"]["state"]["allocation"]
                if a and a.get("market")
            }
        ),
        "borrower_market_positions": sum(m["borrowers"] for m in markets.values()),
        "unique_addresses": len(
            {p["account"] for m in markets.values() for p in m["positions"]}
        ),
        "all_pagination_complete": all(m["complete"] for m in markets.values()),
        "min_share_coverage": min(
            m["share_coverage"] for m in markets.values() if m["total_borrow_shares"]
        ),
        "max_share_coverage": max(
            m["share_coverage"] for m in markets.values() if m["total_borrow_shares"]
        ),
        "selected_market": selected,
        "vaults": vaults,
        "markets": list(markets.values()),
        "loss_curve": curve,
        "stress_assumptions": {
            "BTC_and_ETH_decline": 0.35,
            "sale_discount": 0.01,
            "other_asset_prices": "fixed",
            "loan_unit_conversion": "relative collateral factor divided by loan factor; reporting using initial loan USD marks",
            "liquidation": "terminal recovery, account-level recourse; no intervening liquidation or new borrowing",
            "holdings": "hypothetical 1m USD deposit in each vault; no user attribution",
        },
    }
    (output / "vault-study.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    for name, rows in [
        (
            "vault-summary.csv",
            [{k: v for k, v in x.items() if k != "allocations"} for x in vaults],
        ),
        (
            "market-summary.csv",
            [
                {k: v for k, v in x.items() if k != "positions"}
                for x in markets.values()
            ],
        ),
        (
            "borrower-ledger.csv",
            [
                {
                    "market_id": m["market_id"],
                    "collateral": m["collateral"],
                    "loan": m["loan"],
                    **p,
                }
                for m in markets.values()
                for p in m["positions"]
            ],
        ),
        ("loss-curves.csv", curve),
    ]:
        with (output / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in {"selected_market", "vaults", "markets", "loss_curve"}
            },
            indent=2,
        )
    )
    print(
        "SELECTED",
        selected["market_id"],
        selected["borrowers"],
        selected["debt"],
        selected["top_borrower_share"],
        selected["hhi"],
    )
    print(
        "VAULTS",
        [
            (v["name"], round(v["hypothetical_million_deposit_loss_usd"], 2))
            for v in vaults
        ],
    )
