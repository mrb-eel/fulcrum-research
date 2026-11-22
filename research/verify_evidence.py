"""Offline checks of the retained evidence and the calculations reported in the revision."""

import hashlib
import json
import math
import re
import runpy
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "research"
OUT = R / "results"


def words(s):
    return [int(s[i : i + 64], 16) for i in range(2, len(s), 64)]


def verify_file_hashes(manifest):
    records = json.loads(manifest.read_text(encoding="utf-8"))
    checks = {}
    for row in records:
        observed = hashlib.sha256((ROOT / row["file"]).read_bytes()).hexdigest()
        if observed != row["sha256"]:
            raise ValueError(
                f"Frozen packet differs: {row['file']} (SHA-256 {observed})"
            )
        checks[row["file"]] = observed
    return checks


def verify():
    checks = []

    def check(name, actual, expected, tol=1e-9):
        good = actual == expected
        if isinstance(actual, float) or isinstance(expected, float):
            good = math.isclose(actual, expected, rel_tol=tol, abs_tol=tol)
        if not good:
            raise ValueError(f"{name}: expected {expected!r}, got {actual!r}")
        checks.append({"check": name, "result": "pass"})

    ns = runpy.run_path(str(R / "reference_numerics.py"))
    check("Legacy numerical reference calculations", len(ns["checks"]), 71)
    ns["check"]("Compound illustrative headroom", 125000 - 100000 * 1.3, -5000)
    ns["check"](
        "Quarter quote scaling gap", 983043.179610 * 4 - 3844988.933583, 87183.784857
    )
    ns["check"](
        "Half quote scaling gap", 1964984.917125 * 2 - 3844988.933583, 84980.900667
    )
    for manifest in (R / "raw-manifest.json", R / "evidence-manifest.json"):
        for name in verify_file_hashes(manifest):
            check("Raw fingerprint " + name, True, True)
    study = json.loads((OUT / "vault-study.json").read_text(encoding="utf-8"))
    check("Selected positive-allocation markets", len(study["markets"]), 51)
    check(
        "Borrower-market positions",
        sum(len(m["positions"]) for m in study["markets"]),
        3547,
    )
    addresses = {p["account"] for m in study["markets"] for p in m["positions"]}
    check("Unique borrower addresses", len(addresses), 3059)
    for m in study["markets"]:
        packet = json.loads(
            (ROOT / "data/book" / m["source_file"]).read_text(encoding="utf-8")
        )["snapshot"]
        capture = next(
            v for k, v in packet["borrowers"].items() if k.lower() == m["market_id"]
        )
        check(
            "Raw share reconciliation " + m["market_id"],
            sum(int(p["state"]["borrowShares"]) for p in capture["items"]),
            m["total_borrow_shares"],
        )
        check(
            "Canonical share reconciliation " + m["market_id"],
            sum(p["shares"] for p in m["positions"]),
            m["total_borrow_shares"],
        )
        check("Borrower pagination " + m["market_id"], capture["complete"], True)
    records = json.loads(
        (R / "raw/compound-liquidation-logs.json").read_text(encoding="utf-8")
    )
    previous = 11332732
    events = []
    for rec in records:
        p = rec["request"]["params"][0]
        check("Consecutive Compound request", int(p["fromBlock"], 16), previous + 1)
        previous = int(p["toBlock"], 16)
        events += rec["response"]["result"]
    check("Compound final block", previous, 11335286)
    check(
        "Unique liquidation events",
        len({(e["transactionHash"], e["logIndex"]) for e in events}),
        141,
    )
    amounts = [words(e["data"]) for e in events]
    total = sum(w[2] for w in amounts)
    check("Exact DAI repayments", total, 85222474513270326810927896)
    check("Affected borrowers", len({w[1] for w in amounts}), 124)
    check("Participating liquidators", len({w[0] for w in amounts}), 10)
    balances = {}
    for w in amounts:
        balances[w[1]] = balances.get(w[1], 0) + w[2] * 8 // 100
    display = (R / "raw/compound-proposal-balances.json").read_text(encoding="utf-8")
    pairs = re.findall(r'"(0x[0-9a-fA-F]{40})"\s*:\s*"([0-9.]+)"', display)
    check(
        "Compensation address coverage", {int(k, 16) for k, _ in pairs}, set(balances)
    )
    for account, amount in pairs:
        error = abs(
            Decimal(amount) - Decimal(balances[int(account, 16)]) / Decimal(10**18)
        )
        check("Compensation amount " + account, error < Decimal(".000001"), True)
    state = json.loads((R / "raw/common-block-state.json").read_text(encoding="utf-8"))[
        0
    ]
    answers = {x["id"]: x["result"] for x in state["response"] if "result" in x}
    pos = words(answers[0])
    market = words(answers[1])
    params = words(answers[2])
    price = words(answers[3])[0]
    check("Anchor block number", int(answers[10]["number"], 16), 26162436)
    check(
        "Anchor block hash",
        answers[10]["hash"],
        "0xfb54f6e077a537f523c0194211207e954e1ec6ef496e69fc43f52605ec593969",
    )
    replay = json.loads((R / "raw/fork-replay-curve.json").read_text(encoding="utf-8"))
    anchor = replay["anchor"]
    journal = json.loads(
        (R / "raw/fork-rpc-journal-curve.json").read_text(encoding="utf-8")
    )
    rate_call = next(
        record
        for record in journal
        if record["request"]["method"] == "eth_call"
        and record["request"]["params"][0]["data"].startswith("0x8c00bf6b")
    )
    rate_inputs, rate_block = rate_call["request"]["params"]
    check("Rate call block", rate_block, answers[10]["number"])
    check("Rate call contract", int(rate_inputs["to"], 16), params[3])
    rate = int(rate_call["response"]["result"], 16)
    check("Recorded borrow rate", rate, anchor["borrow_rate_per_second_wad"])
    elapsed = int(answers[10]["timestamp"], 16) - market[4]
    first = rate * elapsed
    second = first * first // (2 * 10**18)
    third = second * first // (3 * 10**18)
    interest = market[2] * (first + second + third) // 10**18
    debt = (pos[1] * (market[2] + interest + 1) + market[3] + 10**6 - 1) // (
        market[3] + 10**6
    )
    check("Accrued market interest", interest, 1389049966)
    check("Common-block account debt", debt, 3415021348409)
    check("Oracle collateral scale", pos[2] * price // 10**36, 3931259740859)
    check(
        "Health factor",
        (pos[2] * price // 10**36 * params[4] // 10**18) / debt,
        1.0533177675626622,
    )
    check("Rehearsal chain identifier", replay["chain_id"], 31337)
    check(
        "Rehearsal helper source fingerprint",
        replay["helper_source_sha256"],
        hashlib.sha256((R / "replay/Unwind.sol").read_bytes()).hexdigest(),
    )
    successes = []
    journal_receipts = {
        record["response"]["result"]["transactionHash"]: record["response"]["result"]
        for record in journal
        if record["request"]["method"] == "eth_getTransactionReceipt"
        and record["response"].get("result") is not None
    }
    for a in replay["attempts"]:
        fraction = str(a["fraction"])
        receipt = a["receipt"]
        check(
            f"Retained journal receipt {fraction}",
            journal_receipts[receipt["transactionHash"]],
            receipt,
        )
        check(
            "Receipt and status " + str(a["fraction"]),
            a["receipt"]["status"] == "0x1",
            a["success"],
        )
        check(
            "Exact collateral fraction " + str(a["fraction"]),
            a["collateral_atomic"],
            int(Decimal(str(a["fraction"])) * pos[2]),
        )
        if a["success"]:
            successes.append(a["fraction"])
            logs = [
                e
                for e in a["logs"]
                if e["address"].lower() == a["helper"].lower() and len(e["data"]) == 386
            ]
            check("Completion event count " + str(a["fraction"]), len(logs), 1)
            completed = words(logs[0]["data"])
            fp = a["final_position"]
            fm = a["final_market"]
            check("Remaining PT " + str(a["fraction"]), fp[2], pos[2] - completed[0])
            check(
                "Repayment cash conservation " + str(a["fraction"]),
                completed[1],
                completed[2],
            )
            check("Residual shareholder cash " + str(a["fraction"]), completed[5], 0)
            check("Remaining debt shares " + str(a["fraction"]), completed[3], fp[1])
            final_debt = (fp[1] * (fm[2] + 1) + fm[3] + 10**6 - 1) // (fm[3] + 10**6)
            check(
                "Post-transaction debt " + str(a["fraction"]),
                a["final_debt_atomic"],
                final_debt,
            )
        else:
            revert_data = a["trace"]["output"]
            selector = revert_data[:10]
            actual, limit = words("0x" + revert_data[10:])
            if a["fraction"] < 1:
                check(
                    f"Insufficient-output selector {fraction}", selector, "0xdac3ed48"
                )
                check(
                    f"Output below required proceeds {fraction}", actual < limit, True
                )
            else:
                check("Market proportion selector", selector, "0xfc68d09e")
                check("Proposed market proportion above limit", actual > limit, True)
    check("Completed tested fractions", successes, [0.01, 0.1])
    models = json.loads((OUT / "model-results.json").read_text(encoding="utf-8"))
    forecasts = json.loads((OUT / "test-forecasts.json").read_text(encoding="utf-8"))

    def tlog(x, nu, scale):
        return (
            math.lgamma((nu + 1) / 2)
            - math.lgamma(nu / 2)
            - 0.5 * math.log(math.pi * nu)
            - math.log(scale)
            - (nu + 1) / 2 * math.log1p((x / scale) ** 2 / nu)
        )

    for asset, m in models["models"].items():
        f = forecasts[asset]
        r = f["returns"]
        v = f["variance"]
        n = len(r)
        check(
            asset + " chronological sample counts",
            [m["train_rows"], m["validation_rows"], m["test_rows"]],
            [1461, 730, 731],
        )
        check(
            asset + " unit innovation variance",
            m["filtered_t_scale"] ** 2 * m["filtered_t_nu"] / (m["filtered_t_nu"] - 2),
            1,
        )
        sigma = m["constant_sigma_pretest"]
        scores = {
            "Gaussian": sum(
                -0.5 * math.log(2 * math.pi) - math.log(sigma) - 0.5 * (x / sigma) ** 2
                for x in r
            )
            / n,
            "Student t": sum(
                tlog(x, m["constant_t_nu"], m["constant_t_scale"]) for x in r
            )
            / n,
            "EWMA Gaussian": sum(
                -0.5 * math.log(2 * math.pi) - 0.5 * math.log(h) - 0.5 * x * x / h
                for x, h in zip(r, v)
            )
            / n,
            "EWMA Student t": sum(
                tlog(x / math.sqrt(h), m["filtered_t_nu"], m["filtered_t_scale"])
                - 0.5 * math.log(h)
                for x, h in zip(r, v)
            )
            / n,
        }
        for name, value in scores.items():
            check(
                asset + " predictive density " + name,
                value,
                m["test_metrics"][name]["mean_log_score"],
                1e-10,
            )
        check(
            asset + " one per cent tail count",
            sum(x < q for x, q in zip(r, f["ewma_t_q01"])),
            m["test_metrics"]["EWMA Student t"]["coverage_1pct"]["hits"],
        )
        check(
            asset + " completed forecast candle",
            m["forecast_last_completed_bucket"],
            "2026-10-10",
        )
    liq = json.loads((OUT / "liquidation-study.json").read_text(encoding="utf-8"))
    check("Policy comparison rows", len(liq["rows"]), 9)
    check("Common policy paths", liq["paths"], 5000)
    for i, row in enumerate(liq["rows"]):
        check(
            "Bounded creditor loss " + str(i),
            0
            <= row["mean"]
            <= row["maximum"]
            <= liq["initial_debt"] * math.exp(row["annual_borrow_rate"] * 30 / 365)
            + 1e-3,
            True,
        )
        check("Tail convention " + str(i), row["es_99"] >= row["var_99"], True)
        check("Probability bounds " + str(i), 0 <= row["loss_probability"] <= 1, True)
    check(
        "Profitability cliff at five per cent discount",
        liq["rows"][6]["liquidation_probability"],
        0,
    )
    return {
        "offline_checks_passed": len(checks),
        "legacy_reference_calculations_passed": len(ns["checks"]),
        "checks": checks,
        "scope": "Retained raw evidence, accounting, forecast-score recomputation, unit-variance convention and local-fork receipt reconciliation. The archive inputs retain their observation dates.",
    }


if __name__ == "__main__":
    report = verify()
    print(json.dumps({k: v for k, v in report.items() if k != "checks"}, indent=2))
