"""Chronological return-model estimation, held-out evaluation and reproducible simulation."""

import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import numpy as np
from scipy import optimize, stats

RAW = ROOT / "data/book"
SEED = 20261119


def date(t):
    import datetime

    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime(
        "%Y-%m-%d"
    )


def fit_t(x):
    def objective(theta):
        nu = 2.01 + np.exp(theta[0])
        scale = np.exp(theta[1])
        return -np.sum(stats.t.logpdf(x, nu, loc=0, scale=scale))

    r = optimize.minimize(
        objective,
        [np.log(5), np.log(np.std(x))],
        method="Nelder-Mead",
        options={"maxiter": 1800, "xatol": 1e-8},
    )
    assert r.success, r.message
    return float(2.01 + np.exp(r.x[0])), float(np.exp(r.x[1]))


def ewma(r, lam, v0):
    v = np.empty(len(r))
    state = float(v0)
    for i, x in enumerate(r):
        v[i] = state
        state = lam * state + (1 - lam) * x * x
    return v, state


def logterm(n, p):
    if n == 0:
        return 0.0
    if p == 0:
        return -np.inf
    return n * np.log(p)


def coverage(hit, alpha):
    hit = np.asarray(hit, dtype=int)
    n = len(hit)
    x = int(hit.sum())
    p = x / n
    lo = 0.0 if x == 0 else float(stats.beta.ppf(0.025, x, n - x + 1))
    hi = 1.0 if x == n else float(stats.beta.ppf(0.975, x + 1, n - x))
    lr = max(
        0,
        -2
        * (
            logterm(x, alpha)
            + logterm(n - x, 1 - alpha)
            - logterm(x, p)
            - logterm(n - x, 1 - p)
        ),
    )
    counts = np.array(
        [[np.sum((hit[:-1] == i) & (hit[1:] == j)) for j in range(2)] for i in range(2)]
    )
    pooled = counts[:, 1].sum() / counts.sum()
    common = sum(
        logterm(int(counts[i, j]), pooled if j else 1 - pooled)
        for i in range(2)
        for j in range(2)
    )
    conditional = 0.0
    for i in range(2):
        row = counts[i]
        pi = row[1] / row.sum() if row.sum() else 0
        conditional += sum(logterm(int(row[j]), pi if j else 1 - pi) for j in range(2))
    ind = max(0, -2 * (common - conditional))
    return {
        "hits": x,
        "n": n,
        "fraction": p,
        "binomial_95_interval": [lo, hi],
        "kupiec_lr": float(lr),
        "kupiec_p": float(stats.chi2.sf(lr, 1)),
        "transition_counts": counts.tolist(),
        "independence_lr": float(ind),
        "independence_p": float(stats.chi2.sf(ind, 1)),
    }


def mean_block_interval(x, block=30, draws=2000, seed=SEED):
    x = np.asarray(x)
    rng = np.random.default_rng(seed)
    k = math.ceil(len(x) / block)
    starts = rng.integers(0, len(x), (draws, k))
    ix = (starts[:, :, None] + np.arange(block)) % len(x)
    b = x[ix.reshape(draws, -1)[:, : len(x)]].mean(axis=1)
    return [float(v) for v in np.quantile(b, [0.025, 0.975])]


def run(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    data = json.loads((RAW / "market-history.json").read_text(encoding="utf-8"))[
        "snapshot"
    ]
    models = {}
    clean = []
    forecasts = {}
    paths_meta = {}
    for asset in ["BTC", "ETH"]:
        records = data["series"][asset.lower() + "usd"]["closes"]
        timestamps = np.array([int(x[0]) for x in records])
        closes = np.array([float(x[1]) for x in records])
        assert (
            len(np.unique(timestamps)) == len(timestamps)
            and np.all(np.diff(timestamps) == 86400)
            and np.all(closes > 0)
        )
        dates = np.array([date(t) for t in timestamps[1:]])
        r = np.diff(np.log(closes))
        sample = (dates >= "2018-01-01") & (dates <= "2025-12-31")
        ds = dates[sample]
        x = r[sample]
        train = ds < "2022-01-01"
        val = (ds >= "2022-01-01") & (ds < "2024-01-01")
        test = ds >= "2024-01-01"
        pre = ~test
        scores = {}
        v0 = float(np.mean(x[train] ** 2))
        for lam in [0.90, 0.94, 0.97, 0.99]:
            v, _ = ewma(x, lam, v0)
            scores[str(lam)] = float(
                np.mean(stats.norm.logpdf(x[val], 0, np.sqrt(v[val])))
            )
        lam = float(max(scores, key=scores.get))
        variance, _ = ewma(x, lam, v0)
        nu_c, scale_c = fit_t(x[pre])
        standardized = x[pre] / np.sqrt(variance[pre])
        fit_nu = optimize.minimize_scalar(
            lambda nu: (
                -np.sum(
                    stats.t.logpdf(
                        standardized, nu, loc=0, scale=np.sqrt((nu - 2) / nu)
                    )
                )
            ),
            bounds=(2.05, 100),
            method="bounded",
        )
        assert fit_nu.success
        nu_f = float(fit_nu.x)
        scale_f = float(np.sqrt((nu_f - 2) / nu_f))
        sigma = float(np.sqrt(np.mean(x[pre] ** 2)))
        rt = x[test]
        vt = variance[test]
        definitions = {
            "Gaussian": (
                stats.norm.logpdf(rt, 0, sigma),
                lambda a: np.full(len(rt), stats.norm.ppf(a) * sigma),
            ),
            "Student t": (
                stats.t.logpdf(rt, nu_c, 0, scale_c),
                lambda a: np.full(len(rt), stats.t.ppf(a, nu_c) * scale_c),
            ),
            "EWMA Gaussian": (
                stats.norm.logpdf(rt, 0, np.sqrt(vt)),
                lambda a: stats.norm.ppf(a) * np.sqrt(vt),
            ),
            "EWMA Student t": (
                stats.t.logpdf(rt / np.sqrt(vt), nu_f, 0, scale_f) - 0.5 * np.log(vt),
                lambda a: stats.t.ppf(a, nu_f) * scale_f * np.sqrt(vt),
            ),
        }
        summary = {}
        for name, (lp, quantile) in definitions.items():
            summary[name] = {
                "mean_log_score": float(lp.mean()),
                "coverage_1pct": coverage(rt < quantile(0.01), 0.01),
                "coverage_5pct": coverage(rt < quantile(0.05), 0.05),
            }
        difference = definitions["EWMA Student t"][0] - definitions["Gaussian"][0]
        score_ci = mean_block_interval(difference)
        full = (dates >= "2018-01-01") & (dates < "2026-10-11")
        fullr = r[full]
        fulldates = dates[full]
        fullvar, latest = ewma(fullr, lam, v0)
        model = {
            "asset": asset,
            "raw_rows": len(closes),
            "sample_rows": len(x),
            "train_rows": int(train.sum()),
            "validation_rows": int(val.sum()),
            "test_rows": int(test.sum()),
            "sample_from": str(ds[0]),
            "sample_to": str(ds[-1]),
            "train_daily_std": float(np.std(x[train], ddof=1)),
            "sample_pearson_kurtosis": float(
                stats.kurtosis(x, fisher=False, bias=False)
            ),
            "squared_return_lag1_correlation": float(
                np.corrcoef(x[:-1] ** 2, x[1:] ** 2)[0, 1]
            ),
            "lambda_validation_scores": scores,
            "selected_lambda": lam,
            "constant_sigma_pretest": sigma,
            "constant_t_nu": nu_c,
            "constant_t_scale": scale_c,
            "filtered_t_nu": nu_f,
            "filtered_t_scale": scale_f,
            "forecast_initial_variance": float(latest),
            "forecast_last_completed_bucket": str(fulldates[-1]),
            "test_metrics": summary,
            "ewma_t_minus_gaussian_log_score": float(difference.mean()),
            "paired_score_block30_95_interval": score_ci,
        }
        models[asset] = model
        for d, z in zip(ds, x):
            clean.append(
                {
                    "asset": asset,
                    "bucket_date": d,
                    "log_return": float(z),
                    "sample": "train"
                    if d < "2022-01-01"
                    else "validation"
                    if d < "2024-01-01"
                    else "test",
                }
            )
        forecasts[asset] = {
            "dates": ds[test].tolist(),
            "returns": rt.tolist(),
            "ewma_t_q01": definitions["EWMA Student t"][1](0.01).tolist(),
            "gaussian_q01": definitions["Gaussian"][1](0.01).tolist(),
            "variance": vt.tolist(),
        }
        rng = np.random.default_rng(SEED + (0 if asset == "BTC" else 1))
        n = 50000
        h = 30
        sim = np.ones((n, h + 1))
        v = np.full(n, latest)
        for t in range(1, h + 1):
            z = stats.t.rvs(nu_f, scale=scale_f, size=n, random_state=rng)
            step = np.sqrt(v) * z
            sim[:, t] = sim[:, t - 1] * np.exp(step)
            v = lam * v + (1 - lam) * step**2
        assert np.isfinite(sim).all() and (sim > 0).all()
        np.savez_compressed(output / (asset.lower() + "-price-paths.npz"), prices=sim)
        # Filtered historical simulation resamples five-day innovation blocks.
        bootstrap_innovations = (standardized - standardized.mean()) / standardized.std(
            ddof=0
        )
        boot = np.ones((n, h + 1))
        vb = np.full(n, latest)
        starts = rng.integers(0, len(standardized), (n, math.ceil(h / 5)))
        for t in range(1, h + 1):
            ix = (starts[:, (t - 1) // 5] + (t - 1) % 5) % len(standardized)
            step = np.sqrt(vb) * bootstrap_innovations[ix]
            boot[:, t] = boot[:, t - 1] * np.exp(step)
            vb = lam * vb + (1 - lam) * step**2

        def barrier(p):
            hit = p.min(axis=1) <= 0.65
            prob = float(hit.mean())
            return {
                "probability_35pct_barrier": prob,
                "mc_se": float(np.sqrt(prob * (1 - prob) / len(hit))),
                "terminal_1pct_quantile": float(np.quantile(p[:, -1], 0.01)),
                "terminal_5pct_quantile": float(np.quantile(p[:, -1], 0.05)),
            }

        paths_meta[asset] = {
            "paths": n,
            "horizon": h,
            "student_t_ewma": barrier(sim),
            "filtered_historical_block5": barrier(boot),
            "initial_variance": float(latest),
            "seed": SEED + (0 if asset == "BTC" else 1),
        }
    report = {
        "seed": SEED,
        "capture_time": data["capturedAt"],
        "data_file_sha256": hashlib.sha256(
            (RAW / "market-history.json").read_bytes()
        ).hexdigest(),
        "sample": "UTC candle bucket dates2018-01-01 through2025-12-31; timestamp is bucket start, close becomes known at the following UTC midnight. The return is assigned to its closing bucket.",
        "selection": "EWMA decay selected by validation-period Gaussian log score; parameters refit on2018-2023; forecast evaluation2024-2025. Distribution parameters frozen for test.2026 completed bars update conditional variance for the dated forward stress experiment.",
        "models": models,
        "simulations": paths_meta,
    }
    (output / "model-results.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    (output / "test-forecasts.json").write_text(json.dumps(forecasts), encoding="utf-8")
    with (output / "clean-returns.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=clean[0])
        w.writeheader()
        w.writerows(clean)
    # Publication figures use vector paths and black type.
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.ticker import PercentFormatter

    matplotlib.rcParams.update(
        {
            "svg.fonttype": "path",
            "font.family": "serif",
            "font.serif": ["DejaVu Serif"],
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.labelcolor": "black",
            "text.color": "black",
        }
    )
    fig, axes = plt.subplots(2, 1, figsize=(6.3, 5.5), layout="constrained")
    for ax, asset in zip(axes, ["BTC", "ETH"]):
        f = forecasts[asset]
        ax.plot(
            np.arange(len(f["returns"])),
            f["returns"],
            color=".65",
            lw=0.45,
            label="Realised return",
        )
        ax.plot(f["ewma_t_q01"], color="black", lw=0.8, label="EWMA t, 1% quantile")
        ax.plot(
            f["gaussian_q01"],
            color="black",
            lw=0.7,
            ls="--",
            label="Constant Gaussian, 1% quantile",
        )
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.set_ylabel(asset + " daily log return")
        ax.set_xticks(
            [0, 182, 366, 548, 730],
            ["Jan 2024", "Jul 2024", "Jan 2025", "Jul 2025", "Dec 2025"],
        )
        ax.legend(frameon=False, fontsize=8, ncol=1)
    fig.savefig(output / "forecast-validation.svg", metadata={"Date": None})
    fig.savefig(output / "forecast-validation.pdf", metadata={"CreationDate": None})
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6.3, 3.2), layout="constrained")
    m = json.loads((output / "vault-study.json").read_text(encoding="utf-8"))[
        "selected_market"
    ]
    for d, ls in [(0, "-"), (0.01, "--"), (0.04, ":"), (0.05, "-.")]:
        s = np.linspace(0, 0.6, 121)
        debt = np.array([p["debt"] for p in m["positions"]])
        c = np.array([p["collateral_value"] for p in m["positions"]])
        losses = (
            np.maximum(0, debt[None, :] - c[None, :] * (1 - s[:, None]) * (1 - d)).sum(
                axis=1
            )
            / m["debt"]
        )
        ax.plot(s, losses, color="black", ls=ls, label=f"Sale discount {d:.0%}")
    ax.set_xlabel("BTC decline")
    ax.set_ylabel("Account-level shortfall / market debt")
    ax.xaxis.set_major_formatter(PercentFormatter(1))
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    ax.legend(frameon=False, fontsize=8)
    fig.savefig(output / "borrower-loss-curve.svg", metadata={"Date": None})
    fig.savefig(output / "borrower-loss-curve.pdf", metadata={"CreationDate": None})
    plt.close(fig)
    print(
        "Saved fitted models, held-out forecasts, 50,000-path simulations and vector figures."
    )
