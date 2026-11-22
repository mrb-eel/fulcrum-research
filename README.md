# Fulcrum Research

Liquidation and lender shortfall in stressed Morpho markets.

[Working paper (PDF)](paper/morpho-stress-losses.pdf) · [Replication guide](research/README.md) · [Policy grid](research/results/v2.0/intraday-policy-grid.csv) · [Citation](CITATION.cff)

## Working paper

*Liquidation and lender shortfall in stressed Morpho markets*

Mohamed Rayan Bouchaibi · Version 2.0 · November 2026

The study applies four severe historical price paths to 51 captured Morpho borrower books. A scan of each market's recorded block found usable direct Uniswap v3 quotes for 23. The other markets are included in the standardised relative-price stress. That stress holds the price path and reserves per unit of debt fixed across books.

In the anchor WBTC/USDC market, a pinned quote returned about 684,000 USDC at a 2% marginal price move. Under the resulting depth approximation and full refill, hourly liquidation checks lowered mean pool-closing shortfall by 217 basis points of opening debt compared with daily checks. Refill, oracle timing, execution depth and borrower repayments materially change that result. [Depth and sensitivity results](research/results/v2.0/intraday-study.json)

The 30-day forecast check covers 702 held-out origins. No 35% crossing occurred in that period. The paper reports conditional stress losses and leaves unconditional crash-loss forecasts uncalibrated. [Held-out forecasts](research/results/v2.0/rolling-backtest.json) · [Conditional losses](research/results/v2.0/conditional-stress.json)

## Replication

Paper replication uses `research/` and the retained inputs in `data/`. The original dashboard is optional.

```bash
python research/verify_evidence.py
python research/reproduce_study.py
```

The [replication guide](research/README.md) lists the Python dependencies, archived inputs and outputs. The [earlier working paper](paper/liquidation-and-creditor-recovery.pdf) retains the Compound and PT unwind studies and the 1% fee reserve thresholds of 72.4M and 362.2M USDC under matched spot and oracle. The [dashboard](docs/dashboard.md) and [early project notes](docs/archive/README.md) document the prototype.

## Licensing

Original code is available under the [MIT License](LICENSE). The working papers, manuscripts and original paper figures are available under [CC BY 4.0](paper/LICENSE). Third-party material and raw source records retain their applicable terms.
