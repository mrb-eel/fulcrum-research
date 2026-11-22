# Fulcrum Research

An empirical study of how collateral valuation and liquidation capacity affect what lenders recover in DeFi.

[Working paper (PDF)](paper/liquidation-capacity-and-recoverable-value.pdf) · [Replication guide](research/README.md) · [Results](research/results) · [Citation](CITATION.cff)

## Working paper

*Liquidation capacity and recoverable value in DeFi lending*

Mohamed Rayan Bouchaibi · Working paper, version 1.0 · November 2026

A lending market can have enough collateral in aggregate and still leave creditors short. In a captured Morpho WBTC/USDC market with 614 borrowers, a 35% collateral price decline and a 1% sale discount produced **1,394,925.51 USDC** of modeled shortfall when recovery was calculated loan by loan. Pooling the collateral produced zero for the same shock. Surplus collateral in one account cannot settle another account's debt under the specified recourse rules. [Borrower ledger](research/results/borrower-ledger.csv) · [Market analysis](research/results/vault-study.json)

- Ten Morpho vault captures supply 3,547 borrower-market records across 51 markets with positive allocation. The study compares four return models for each of BTC and ETH on held-out data. The fitted BTC model supplies 5,000 common paths for the liquidation simulations. [Forecasts](research/results/model-results.json) · [Policy comparisons](research/results/liquidation-study.csv)
- A ledger of 141 Compound cDAI liquidation events records 85.22 million DAI of repayments. It reconciles the proposal's address-level compensation file and identifies a discrepancy in the proposal's prose total. [Event ledger](research/results/compound-events.csv) · [Reconciliation](research/results/compound-reconciliation.json)
- A historical fork at Ethereum block 26,162,436 records completed 1% and 10% reductions of a financed PT-sUSDe position. The tested route encountered funding and pool constraints at larger sizes. [Fork evidence](research/raw/fork-replay-curve.json)

The vault sample was selected for the project. Liquidation capacity and disposal discounts are scenario assumptions. The conclusions apply to the observed positions and the specified experiments.

## Replication

From the repository root, run the evidence checks with Python 3.12 or later. They read the retained files and require only the standard library.

```bash
python research/verify_evidence.py
```

The [replication guide](research/README.md) maps each paper result to its inputs and output tables and gives the commands to re-estimate the models and regenerate the experiments.

The [original analysis dashboard](docs/dashboard.md) and [early project notes](docs/archive/README.md) are available for reference.
