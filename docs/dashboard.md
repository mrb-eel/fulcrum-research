# Fulcrum dashboard

This dashboard traces dependencies across Morpho lending markets and evaluates price or oracle scenarios against saved evidence. The [research companion](../README.md) documents the working paper, its evidence and its replication commands.

## Run locally

Use Node.js 20 or later. The dashboard has no npm dependencies.

```sh
npm test
npm start
```

Open [the vault book](http://127.0.0.1:4173/book.html). The application serves the saved examples from disk and recalculates slider changes locally. The browser loads fonts from Google Fonts, with local fallbacks. The 3D tour also loads Three.js from a CDN.

| Page | Path | Purpose |
| --- | --- | --- |
| Vault book | `/book.html` | View shared dependencies and stress a hypothetical portfolio with equal allocations across ten Morpho vaults. |
| Vault viewer | `/xray.html` | Open a saved vault, import an evidence packet or capture a Morpho V1 vault by address. |
| Vault details | `/vault.html?id=steakhouse-usdc` | Inspect borrower exposures, oracle inputs, recovery estimates and available cash. |
| PT case | `/case.html` | Inspect the PT-sUSDe borrowing position, including the saved oracle trace and route quotes. |
| Workspace | `/portfolio.html` | Import positions or read Morpho Blue positions by wallet address, then calculate scenarios and exit steps. |
| Project tour | `/` and `/how.html` | Walk through the original dashboard and presentation. |

## API and evidence

| Method and path | Result |
| --- | --- |
| `GET /api/health` | Local server status. |
| `GET /api/book`, `POST /api/book/evaluate` | Saved vault models, common dependencies and scenario comparisons. |
| `GET /api/vault?id=steakhouse-usdc`, `POST /api/vault/evaluate` | Vault model, scenario result and reverse stress. |
| `GET /api/vault/evidence?id=steakhouse-usdc`, `GET /api/vault/graph?id=steakhouse-usdc` | Source packet and dependency graph. |
| `GET /api/book/enrichment`, `GET /api/book/history`, `GET /api/lending` | Retained oracle inputs, price history and the Aave v3 and Spark oracle scans. |
| `GET /api/demo-analysis`, `GET /api/portfolio`, `POST /api/evaluate` | Saved PT case, sample portfolio and portfolio scenario calculations. |

`GET /api/live-analysis` and `GET /api/discover` query public providers. `POST /api/vault/capture` takes a vault address in a JSON body and fetches data over the network. `POST /api/vault/import` takes a saved packet and attempts live oracle enrichment, with a fallback to the supplied packet. Imported and captured custom vaults are held in process memory.

The saved dashboard inputs live in [`data/book/`](../data/book/) and [`data/snapshots/`](../data/snapshots/). Use a separate checkout for new captures because the capture commands write to these paths.

## Limits

Borrower-level loss modeling covers Morpho V1 vaults with direct markets. Aave v3 and Spark coverage is limited to oracle inspection. The dashboard compares a sudden price gap with a gradual path that assumes timely liquidation whenever the oracle responds and disposal is profitable. Its probability inputs are historical window frequencies or user estimates. Vault weights and position sizes in the example book are hypothetical.

The paper's simulation assigns an explicit daily repayment capacity and tests the effect of oracle lag. Its PT execution results come from receipts on a historical local fork. The dashboard's PT quotes and exit rehearsals are estimates.
