# Replication guide

This guide accompanies [*Liquidation and creditor recovery in selected DeFi lending positions*](../paper/liquidation-and-creditor-recovery.pdf), version 1.1, by Mohamed Rayan Bouchaibi. Run the commands from the repository root. The [first version](../paper/liquidation-capacity-and-recoverable-value.pdf) is retained alongside the revision.

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
.venv/bin/python research/reproduce_revision.py
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r research/requirements.txt
.\.venv\Scripts\python.exe research/reproduce_revision.py
```

The revision command regenerates the expanded decay grid, 100,000 BTC paths, size-dependent liquidation experiment, closing-price and intraday-low windows, and marked fork costs. It compares the reports with [the archived results](results/v1.1/) before writing to `research/generated/v1.1/`. The comparison allows small floating-point differences across platforms. Generated price paths are stored locally as NumPy archives. Run `python research/reproduce.py` to rebuild the original numerical tables and compare the Compound event CSV row by row.

## Inputs and results

| Paper section | Retained inputs | Results |
| --- | --- | --- |
| 2. Data, selection and borrower accounting | [Morpho vault packets and fingerprints](raw-manifest.json), captured 11 October 2026 | [Borrower ledger](results/borrower-ledger.csv), [market summary](results/market-summary.csv), [vault summary](results/vault-summary.csv), [loss curve](results/borrower-loss-curve.svg) |
| 3. Return distributions, estimation and forecast evaluation | [Bitstamp BTC/USD and ETH/USD closes](../data/book/market-history.json) and [BTC/USD OHLC bars](raw/bitstamp-btcusd-daily.json) | [Fitted parameters and test scores](results/v1.1/model-results.json), [forecasts](results/v1.1/test-forecasts.json), [historical threshold counts](results/v1.1/historical-btc-barriers.json) |
| 4. Liquidation with size-dependent execution | The [selected market and opening loan book](results/vault-study.json), combined with BTC paths and stated pool reserves | [Policy comparisons and paired errors](results/v1.1/depth-study.json) |
| 5. Primary Compound liquidation evidence | [cDAI event responses](raw/compound-liquidation-logs.json), Ethereum blocks 11,332,733–11,335,286, and the [proposal's address balances](raw/compound-proposal-balances.json) | [Event ledger](results/compound-events.csv), [aggregate results](results/compound-event-study.json), [compensation reconciliation](results/compound-reconciliation.json) |
| 6. Valuation and execution in a financed PT-sUSDe position | [Position, market and oracle reads](raw/common-block-state.json) from Ethereum block 26,162,436 | [Curve receipts and traces](raw/fork-replay-curve.json), [RPC journal](raw/fork-rpc-journal-curve.json), [equity and health calculations](results/v1.1/fork-costs.json) |

The borrower ledgers measure a selected group of vaults at their documented capture times. The model varies assumed reserves, repayment capacity and oracle delay in one market. The historical fork is covered by offline verification of the recorded evidence. The original provider discarded the transaction calldata for the aggregator quote. The capture code now retains the unsigned router transaction when the provider includes it.
