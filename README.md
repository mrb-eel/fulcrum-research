# Fulcrum Research

An empirical study of how collateral valuation and liquidation capacity affect what lenders recover in DeFi.

[Working paper (PDF)](paper/liquidation-and-creditor-recovery.pdf) · [Replication guide](research/README.md) · [Revision results](research/results/v1.1) · [Citation](CITATION.cff)

## Working paper

*Liquidation and creditor recovery in selected DeFi lending positions*

Mohamed Rayan Bouchaibi · Working paper, version 1.1 · November 2026

A lending market can have enough collateral in aggregate and still leave creditors short. In a captured Morpho WBTC/USDC market with 614 borrowers, a 35% collateral price decline and a 1% sale discount produced **1,394,925.51 USDC** of modeled shortfall when recovery was calculated loan by loan. Pooling the collateral produced zero for the same shock. Surplus collateral in one account cannot settle another account's debt under the specified recourse rules. [Borrower ledger](research/results/borrower-ledger.csv) · [Market analysis](research/results/vault-study.json)

- Ten Morpho vault captures supply 3,547 borrower-market records across 51 markets with positive allocation. In the selected WBTC/USDC market, the 100,000-path experiment finds that assumed pool depth binds before a 5% daily repayment cap under its base reserve. [Forecasts](research/results/v1.1/model-results.json) · [Policy comparisons](research/results/v1.1/depth-study.json)
- A ledger of 141 Compound cDAI liquidation events records 85.22 million DAI of repayments. It reconciles the proposal's address-level compensation file and identifies a discrepancy in the proposal's prose total. [Event ledger](research/results/compound-events.csv) · [Reconciliation](research/results/compound-reconciliation.json)
- On a historical fork, a financed 10% PT-sUSDe reduction raised health from 1.0533 to 1.0637 at the opening oracle mark and consumed 21,565 USDC of marked equity before gas. Larger tests encountered constraints on the chosen route. [Fork evidence](research/raw/fork-replay-curve.json) · [Cost calculations](research/results/v1.1/fork-costs.json)

The repo covers a selected sample of vaults, one market for the dynamic experiment and one account for the fork test. Pool reserves and daily repayment caps are scenario assumptions. The retained aggregator quote includes its proposed proceeds and summary. Its router calldata was unavailable for a historical replay.

## Replication

From the repository root, run the evidence checks with Python 3.12 or later. They read the retained files and require only the standard library.

```bash
python research/verify_evidence.py
```

The [replication guide](research/README.md) maps each paper result to its inputs and output tables and gives the commands to re-estimate the models and regenerate the experiments.

The [original analysis dashboard](docs/dashboard.md) and [early project notes](docs/archive/README.md) are available for reference.
