# Replication guide

This guide accompanies [*Liquidation and lender shortfall in stressed Morpho markets*](../paper/morpho-stress-losses.pdf), version 2.0, by Mohamed Rayan Bouchaibi. Run the commands from the repository root.

## Evidence and replication

Use Python 3.12 or later. The evidence audit uses the standard library, and the numerical study uses [the pinned dependencies](requirements.txt). Installing dependencies needs internet access. Replication uses the retained inputs offline.

```bash
python research/verify_evidence.py
python -m venv .venv
```

On macOS or Linux:

```bash
.venv/bin/python -m pip install -r research/requirements.txt
.venv/bin/python research/reproduce_study.py
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r research/requirements.txt
.\.venv\Scripts\python.exe research/reproduce_study.py
```

The command regenerates the price inputs and runs the rolling forecast test, four historical crash replays and the 10 October 2025 event benchmark. It checks the reference JSON and CSV outputs before writing to `research/generated/v2.0/`. The CSVs retain every forecast origin and every historical policy observation.

## Main paper evidence

| Evidence | Input | Output |
| --- | --- | --- |
| Borrower books | [Vault capture manifest](raw-manifest.json) | [Reconciled borrower ledger](results/borrower-ledger.csv) |
| Direct pool and route audit | [Market scan](raw/morpho-direct-depth.json), [anchor depth curve](raw/morpho-anchor-depth-curve.json) and [historical route quotes](raw/morpho-anchor-route-comparison.json) | [Depth audit](results/v2.0/intraday-study.json) |
| Historical stresses | [BTC/USD hours](raw/bitstamp-btcusd-hourly-stress.json) and [ETH/USD hours](raw/bitstamp-ethusd-hourly-stress.json) | [Policy grid](results/v2.0/intraday-policy-grid.csv) |
| 30-day forecasts | [Daily bars](raw/bitstamp-btcusd-daily.json) and [retained fitted baseline](results/v1.1/model-results.json) | [Forecasts and outcomes by origin](results/v2.0/rolling-barriers.csv) and [score summary](results/v2.0/rolling-backtest.json) |
| 10 October 2025 | [Fork block, positions, oracle samples, spot prices and event logs](raw/morpho-wbtc-2025-10-10.json) | [Model and realised execution comparison](results/v2.0/historical-event.json) |

At the horizon, borrowers with collateral worth less than their debt at spot sell their collateral. In the pool case they share a pro-rata execution price based on the pool inventory after the last intervention. Performing claims are carried at par. Each policy's loss change uses a control with the same reserve. The grid crosses four episodes and fourteen policies with ten standardised WBTC, cbBTC and WETH books against USDC or USDT and eight additional direct-pool variants.

The event capture used Anvil at Ethereum block 23,543,615 with the opening book reconciled to on-chain borrow shares. Its Python replay keeps that opening book fixed apart from modelled liquidations and compares against the day's Morpho liquidation logs. Observed event bad debt is compared with modelled same-day write-offs.

## Earlier editions

[Version 1.2](../paper/archive/liquidation-and-creditor-recovery.pdf) preserves the Compound event extraction and PT unwind. Its full-book terminal model is superseded. Run `python research/reproduce_settlement.py` to regenerate its [archived results](results/v1.2/). Once the current study has generated the same price paths, `--reuse-paths` reuses them.

[Version 1.1](https://github.com/mrb-eel/fulcrum-research/blob/75b6feaabc61515a35a323bbc6b82bb62cd54912/paper/liquidation-and-creditor-recovery.pdf) uses the original flat closing convention. Run `python research/reproduce_revision.py` for [its archived outputs](results/v1.1/). The [first version](../paper/archive/liquidation-capacity-and-recoverable-value.pdf) can be checked with `python research/reproduce.py`, which includes the independent Compound event reconstruction. The [initial v2.0 commit](https://github.com/mrb-eel/fulcrum-research/tree/b51217c42225018e20eab625746e5f86d1d7ec31) preserves the withdrawn run.
