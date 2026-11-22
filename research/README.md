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

The command regenerates the validated price inputs and runs the rolling forecast test, the four historical replays and the conditional simulated stress. It checks the archived JSON results before writing to `research/generated/v2.0/`. The detailed CSVs retain every forecast origin and every market-policy-episode combination.

## Main paper evidence

| Evidence | Input | Output |
| --- | --- | --- |
| Borrower books | [Vault capture manifest](raw-manifest.json) | [Reconciled borrower ledger](results/borrower-ledger.csv) |
| Direct pool scan | [Pinned factory, pool and quoter responses](raw/morpho-direct-depth.json) | [Depth by market and market-level summary](results/v2.0/intraday-study.json) |
| Historical stresses | [BTC/USD hourly observations](raw/bitstamp-btcusd-hourly-stress.json) and [daily bars](raw/bitstamp-btcusd-daily.json) | [Market-policy-episode results](results/v2.0/intraday-policy-grid.csv) |
| 30-day forecasts | [Daily bars](raw/bitstamp-btcusd-daily.json) and [retained fitted baseline](results/v1.1/model-results.json) | [Forecasts and outcomes by origin](results/v2.0/rolling-barriers.csv) and [score summary](results/v2.0/rolling-backtest.json) |
| Simulated crash subset | The regenerated 100,000 daily BTC paths | [Losses conditional on a 35% crossing](results/v2.0/conditional-stress.json) |

The matching pool batch and flat haircut are separate terminal scenarios. At the horizon every unpaid account in the pool scenario shares one clearing price and applies its proceeds to its own debt. The pool calculation uses the inventory remaining after the last interim intervention. The standardised market grid applies the same relative shock to each captured book as a conditional exercise. Direct-pool rows require a pinned, positive quote that reached the 2% marginal price limit. Each row's loss change uses a control with the same reserve.

## Earlier editions

[Version 1.2](../paper/liquidation-and-creditor-recovery.pdf) preserves the Compound event extraction and PT unwind, alongside the detailed flat versus pool terminal comparison, reserve thresholds and the distressed-loan premium ledger. Run `python research/reproduce_settlement.py` to verify its [results](results/v1.2/). Once v2.0 has generated the same price paths, `--reuse-paths` reuses them.

[Version 1.1](https://github.com/mrb-eel/fulcrum-research/blob/75b6feaabc61515a35a323bbc6b82bb62cd54912/paper/liquidation-and-creditor-recovery.pdf) uses the original flat closing convention. Run `python research/reproduce_revision.py` for [its archived outputs](results/v1.1/). The [first version](../paper/liquidation-capacity-and-recoverable-value.pdf) can be checked with `python research/reproduce.py`, which includes the independent Compound event reconstruction.
