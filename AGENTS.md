# Instructions for coding agents

Data: base reported numbers on retained source records or reproducible calculations.

Documentation: distinguish captured observations, fitted estimates and scenario assumptions. Give the input, units and code for each reported result.

Paper inputs: keep `data/book/` and `research/raw/` fixed for replication. Take fresh dashboard captures with `node scripts/capture-book.js` in a separate checkout.

Tests: use `node --test` for the dashboard and `python research/verify_evidence.py` for paper evidence. Run `python research/reproduce_study.py` after changing the current numerical analysis.
