# Instructions for coding agents

Design: follow ../design-brief.md (radiograph palette in public/xray.css, 4px spacing scale, 2px radius, no purple, no glows, no emoji). Run `npx impeccable detect public/` before committing UI changes.

Data: never show a number that does not come from a saved packet or a computation on one. Keep limitations in the one "Limits" section of each page, not under every figure.

Writing (UI copy, docs, slides): no "it's not X, it's Y"; no em dashes; no headings that start with What/Where/Why/How; no bold-first bullets; no arrows or other unicode decoration in prose; no "quietly", "robust", "leverage", "landscape", "seamless"; no announcing counts ("three things..."); no summary that restates the section. Plain sentences, specific numbers, sentence-case headings.

Paper inputs: keep `data/book/` and `research/raw/` fixed for replication. Take fresh dashboard captures with `node scripts/capture-book.js` in a separate checkout.

Tests: use `node --test` for the dashboard and `python research/verify_evidence.py` for paper evidence. Run `python research/reproduce.py` after changing the numerical analysis.
