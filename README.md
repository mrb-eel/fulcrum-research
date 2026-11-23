# Fulcrum Research

Liquidation and lender shortfall in stressed Morpho markets.

[Working paper (PDF)](paper/morpho-stress-losses.pdf) · [Replication guide](research/README.md) · [Policy grid](research/results/v2.0/intraday-policy-grid.csv) · [Citation](CITATION.cff)

## Working paper

*Liquidation and lender shortfall in stressed Morpho markets*

Mohamed Rayan Bouchaibi · Version 2.0 · November 2026

Hourly liquidation checks reduced mean lender shortfall by 78 basis points of opening debt relative to daily checks in the WBTC/USDC anchor book, under the flat recovery haircut. The corresponding distressed-only pool sale gave a 145 basis point reduction. Both comparisons use four historical crash paths and full daily refill. [Policy results](research/results/v2.0/intraday-study.json)

The study replays ten BTC- and ETH-collateral books with stablecoin debt, using each asset's own observed prices over the same dates. The pinned anchor quotes show approximately 7.1 million USDC of proceeds at a 40% marginal move against 15.3 million from the curve fitted at 2%. The route audit compares two direct fee tiers, WETH routes and splits. [Depth results](research/results/v2.0/intraday-study.json)

An event benchmark compares a pre-drop reconstruction of the same Morpho market with its 10 October 2025 liquidations. The rolling 30-day forecast check estimates 110 hits at the 15% closing barrier against 101 observed, with weaker agreement at more severe thresholds. [Historical event](research/results/v2.0/historical-event.json) · [Held-out forecasts](research/results/v2.0/rolling-backtest.json)

## Replication

Paper replication uses `research/` and the retained inputs in `data/`. The original dashboard is optional.

```bash
python research/verify_evidence.py
python research/reproduce_study.py
```

The [replication guide](research/README.md) lists the Python dependencies, archived inputs and outputs. The [paper archive](paper/archive/) contains the Compound ledger and PT unwind. The [dashboard](docs/dashboard.md) and [early project notes](docs/archive/README.md) document the prototype.

## Licensing

Original code is available under the [MIT License](LICENSE). The working papers, manuscripts and original paper figures are available under [CC BY 4.0](paper/LICENSE). Third-party material and raw source records retain their applicable terms.
