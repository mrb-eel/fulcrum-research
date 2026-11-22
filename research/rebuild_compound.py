"""Reconstruct the cDAI liquidation table from the archived RPC responses."""

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal, localcontext
from pathlib import Path

RESEARCH = Path(__file__).resolve().parent
START_BLOCK = 11_332_733
END_BLOCK = 11_335_286
CDAI = "0x5d3a536e4d6dbd6114cc1ead35777bab948e3643"
SIGNATURE = "LiquidateBorrow(address,address,uint256,address,uint256)"
TOPIC = "0x298637f684da70674f26509b10f07ec2fbc77a335ab1e7d6215a4b2484d8bb52"
DAI_SCALE = 10**18
PROPOSAL_PROSE_TOTAL = Decimal("85220406.43")


@dataclass(frozen=True)
class Liquidation:
    block: int
    transaction_index: int
    log_index: int
    tx_hash: str
    liquidator: str
    borrower: str
    repaid_dai_atomic: int
    collateral_ctoken: str
    seized_ctoken_atomic: int


def decode_log(log, first_block, last_block):
    block = int(log["blockNumber"], 16)
    if not first_block <= block <= last_block:
        raise ValueError(f"Log at block {block} is outside the requested range")
    if log["address"].lower() != CDAI or log["topics"] != [TOPIC] or log["removed"]:
        raise ValueError(f"Unexpected log at block {block}: {log['transactionHash']}")
    payload = log["data"]
    if not re.fullmatch(r"0x[0-9a-fA-F]{320}", payload):
        raise ValueError(f"Invalid LiquidateBorrow data at block {block}")
    liquidator, borrower, repayment, collateral, seized = (
        payload[index:index + 64].lower() for index in range(2, 322, 64)
    )
    if any(word[:24] != "0" * 24 for word in (liquidator, borrower, collateral)):
        raise ValueError(f"Invalid ABI address padding at block {block}")
    return Liquidation(
        block,
        int(log["transactionIndex"], 16),
        int(log["logIndex"], 16),
        log["transactionHash"].lower(),
        "0x" + liquidator[-40:],
        "0x" + borrower[-40:],
        int(repayment, 16),
        "0x" + collateral[-40:],
        int(seized, 16),
    )


def read_events(log_path):
    records = json.loads(log_path.read_text(encoding="utf-8"))
    events = []
    event_ids = set()
    next_block = START_BLOCK
    for record in records:
        request = record["request"]
        params, = request["params"]
        first_block = int(params["fromBlock"], 16)
        last_block = int(params["toBlock"], 16)
        if request["method"] != "eth_getLogs" or params["address"].lower() != CDAI:
            raise ValueError(f"Unexpected request starting at block {first_block}")
        if params["topics"] != [TOPIC] or not next_block == first_block <= last_block <= END_BLOCK:
            raise ValueError(f"Invalid topics or noncontiguous range at block {first_block}")
        response = record["response"]
        if response.get("id") != request["id"] or not isinstance(response.get("result"), list):
            raise ValueError(f"Missing log response for range {first_block}-{last_block}")
        for log in response["result"]:
            event = decode_log(log, first_block, last_block)
            event_id = (event.tx_hash, event.log_index)
            if event_id in event_ids:
                raise ValueError(f"Duplicate liquidation at {event.tx_hash}:{event.log_index}")
            event_ids.add(event_id)
            events.append(event)
        next_block = last_block + 1
    if next_block != END_BLOCK + 1 or not events:
        raise ValueError("The archived requests must cover the full window and contain liquidation events")
    return sorted(events, key=lambda event: (event.block, event.transaction_index, event.log_index))


def summarize(events):
    borrowers = Counter()
    liquidators = Counter()
    collateral = {}
    for event in events:
        borrowers[event.borrower] += event.repaid_dai_atomic
        liquidators[event.liquidator] += event.repaid_dai_atomic
        bucket = collateral.setdefault(event.collateral_ctoken, {
            "events": 0,
            "repaid_dai_atomic": 0,
            "seized_ctoken_atomic": 0,
        })
        bucket["events"] += 1
        bucket["repaid_dai_atomic"] += event.repaid_dai_atomic
        bucket["seized_ctoken_atomic"] += event.seized_ctoken_atomic

    total = sum(borrowers.values())
    ranked = borrowers.most_common()
    largest_borrower, largest_repayment = ranked[0]
    return {
        "window": [START_BLOCK, END_BLOCK],
        "contract": CDAI,
        "event_signature": SIGNATURE,
        "topic": TOPIC,
        "events": len(events),
        "borrowers": len(borrowers),
        "liquidators": len(liquidators),
        "repaid_dai_atomic": total,
        "repaid_dai": float(Decimal(total) / DAI_SCALE),
        "largest_borrower": largest_borrower,
        "largest_borrower_repaid_dai": float(Decimal(largest_repayment) / DAI_SCALE),
        "largest_borrower_fraction": largest_repayment / total,
        "top5_fraction": sum(repaid for _, repaid in ranked[:5]) / total,
        "borrower_repayment_hhi": sum((amount / total)**2 for amount in borrowers.values()),
        "largest_liquidator_fraction": max(liquidators.values()) / total,
        "by_collateral_ctoken": collateral,
        "borrowers_ranked": [
            {"account": account, "repaid_dai": float(Decimal(repaid) / DAI_SCALE), "share": repaid / total}
            for account, repaid in ranked
        ],
        "full_range_returned": True,
        "event_accounting": (
            "Repayment amounts are DAI token quantities. Seized amounts remain in each collateral cToken "
            "raw accounting units. Source-chain event window and debt contract define the sample."
        ),
    }


def read_proposal_balances(path):
    # The retained file is a JavaScript object literal with two bare keys and trailing commas.
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^(\s*)(addresses|total):", r'\1"\2":', text)
    text = re.sub(r",\s*}", "}", text)
    balances = {}
    for address, amount in json.loads(text)["addresses"].items():
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address) or address.lower() in balances:
            raise ValueError(f"Invalid or duplicate address in proposal balances: {address}")
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", amount):
            raise ValueError(f"Invalid amount for proposal account {address}")
        balances[address.lower()] = Decimal(amount)
    return balances


def reconcile_proposal(events, balances):
    compensation = Counter()
    for event in events:
        compensation[event.borrower] += event.repaid_dai_atomic * 8 // 100
    if balances.keys() != compensation.keys():
        raise ValueError("Proposal and event ledger contain different borrower addresses")
    with localcontext() as context:
        context.prec = 100
        repaid = Decimal(sum(event.repaid_dai_atomic for event in events)) / DAI_SCALE
        max_difference = max(
            abs(amount - Decimal(compensation[borrower]) / DAI_SCALE)
            for borrower, amount in balances.items()
        )
        if max_difference >= Decimal("0.000001"):
            raise ValueError(f"At least one compensation amount differs by {max_difference} DAI")
        return {
            "addresses": len(balances),
            "distribution_sum": str(sum(balances.values())),
            "maximum_address_difference_dai": str(max_difference.normalize()),
            "event_repaid_dai": str(repaid),
            "prose_difference_dai": str(repaid - PROPOSAL_PROSE_TOTAL),
            "method": "Each event compensation uses floor(repayAtomic*8/100), then aggregates by borrower.",
        }


def rebuild(logs, balances, output):
    events = read_events(logs)
    summary = summarize(events)
    proposal = reconcile_proposal(events, read_proposal_balances(balances))
    output.mkdir(parents=True, exist_ok=True)
    for filename, data in [
        ("compound-event-study.json", summary),
        ("compound-reconciliation.json", proposal),
    ]:
        (output / filename).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    rows = [asdict(event) for event in events]
    with (output / "compound-events.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return summary, proposal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs", type=Path, default=RESEARCH / "raw/compound-liquidation-logs.json")
    parser.add_argument("--balances", type=Path, default=RESEARCH / "raw/compound-proposal-balances.json")
    parser.add_argument("--output", type=Path, default=RESEARCH / "generated")
    args = parser.parse_args()
    summary, proposal = rebuild(args.logs, args.balances, args.output)
    dai_repaid = Decimal(proposal["event_repaid_dai"])
    print(f"Reconstructed {summary['events']} cDAI liquidations and {dai_repaid:,} DAI repaid.")
    print(f"Reconciled compensation for {proposal['addresses']} borrower addresses.")


if __name__ == "__main__":
    main()
