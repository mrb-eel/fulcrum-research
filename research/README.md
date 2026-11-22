# Replication guide

This guide accompanies [*Liquidation capacity and recoverable value in DeFi lending*](../paper/liquidation-capacity-and-recoverable-value.pdf), version 1.0, by Mohamed Rayan Bouchaibi. Run the commands from the repository root.

## Verify the retained evidence

```bash
python research/verify_evidence.py
```

The verifier uses the Python standard library. It checks the original capture hashes, reconciles borrower shares and Compound repayments, recalculates predictive scores from saved forecasts and checks the historical fork receipts and post-transaction balances. The [capture manifest](raw-manifest.json) records the original commit, fingerprint and capture time for each vault, oracle or price packet. The [evidence manifest](evidence-manifest.json) fingerprints the additional records used in the paper.

## Regenerate the analysis

Use Python 3.12 or later with the package versions in [requirements.txt](requirements.txt). Installing the packages requires internet access. The analysis runs offline once the packages are installed.

```bash
python -m venv .venv
```

On macOS or Linux:

```bash
.venv/bin/python -m pip install -r research/requirements.txt
.venv/bin/python research/reproduce.py
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r research/requirements.txt
.\.venv\Scripts\python.exe research/reproduce.py
```

The command writes regenerated files to `research/generated/`. It compares the main numerical reports with the retained results and matches the Compound event CSV row by row. Integer quantities and event records must match exactly. The comparison allows small differences in floating-point estimates across platforms. Generated price paths are stored locally as NumPy archives.

## Inputs and results

| Paper section | Retained inputs | Results |
| --- | --- | --- |
| 2. Data, selection and borrower accounting | [Morpho vault packets and fingerprints](raw-manifest.json), captured 11 October 2026 | [Borrower ledger](results/borrower-ledger.csv), [market summary](results/market-summary.csv), [vault summary](results/vault-summary.csv), [loss curve](results/borrower-loss-curve.svg) |
| 3. Return distributions, estimation and forecast evaluation | [Bitstamp BTC/USD and ETH/USD daily bars](../data/book/market-history.json). The test period is 2024–2025. | [Clean returns](results/clean-returns.csv), [fitted parameters and test scores](results/model-results.json), [saved forecasts](results/test-forecasts.json), [forecast figure](results/forecast-validation.svg) |
| 4. Dynamic liquidation experiment | The [selected market and opening loan book](results/vault-study.json), combined with price paths generated from the fitted BTC model | [Policy comparison](results/liquidation-study.csv), [simulation statistics](results/liquidation-study.json) |
| 5. Primary Compound liquidation evidence | [cDAI event responses](raw/compound-liquidation-logs.json), Ethereum blocks 11,332,733–11,335,286, and the [proposal's address balances](raw/compound-proposal-balances.json) | [Event ledger](results/compound-events.csv), [aggregate results](results/compound-event-study.json), [compensation reconciliation](results/compound-reconciliation.json) |
| 6. Fulcrum valuation and route execution | [Position, market and oracle reads](raw/common-block-state.json) from Ethereum block 26,162,436 | [Pinned position calculation](raw/atomic-position-analysis.json), [Curve route receipts and traces](raw/fork-replay-curve.json), [RPC journal](raw/fork-rpc-journal-curve.json) |

The borrower ledgers measure a selected group of vaults at their documented capture times. The model experiments use explicitly set capacity, oracle delay and disposal costs. Replication regenerates the numerical studies and the Compound event reconstruction. The historical fork is covered by offline checks of the saved execution evidence.
