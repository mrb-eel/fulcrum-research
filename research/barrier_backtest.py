"""Evaluate 30-day BTC barrier forecasts on complete 2024-2025 windows."""

import csv
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from numba import njit, prange
from scipy.optimize import minimize

from empirical_models import ewma
from reproduce_revision import read, save


RAW = Path(__file__).resolve().parent / 'raw'
THRESHOLDS = np.array([0.15, 0.25, 0.35])
HORIZON = 30
DRAWS = 20_000
SEED = 20261122


@njit
def gjr_variances(returns, initial, coefficients):
    omega, alpha, gamma, beta = coefficients
    output = np.empty(len(returns))
    variance = initial
    for i, value in enumerate(returns):
        output[i] = variance
        variance = omega + (alpha + gamma * (value < 0)) * value**2 + beta * variance
    return output


@njit
def gjr_cost(parameters, returns, initial):
    df = parameters[4]
    constant = math.lgamma((df + 1) / 2) - math.lgamma(df / 2) - math.log(math.pi * (df - 2)) / 2
    h = gjr_variances(returns, initial, parameters[:4])
    loss = 0.0
    for i in range(len(returns)):
        loss -= constant - 0.5 * np.log(h[i]) - ((df + 1) / 2) * np.log1p(returns[i]**2 / (h[i] * (df - 2)))
    return loss / len(returns)


def fit_gjr(returns, initial):
    def stability(params):
        return 0.999 - params[1] - params[2] / 2 - params[3]

    fits = [minimize(gjr_cost, guess, args=(returns, initial), method='SLSQP',
                     bounds=((1e-6, 50), (0, 0.8), (0, 1), (0, 0.999), (2.05, 100)),
                     constraints={'type': 'ineq', 'fun': stability},
                     options={'maxiter': 750, 'ftol': 1e-11})
            for guess in ([0.2, 0.08, 0.08, 0.85, 4], [0.5, 0.04, 0.12, 0.85, 7],
                          [1.0, 0.08, 0.02, 0.80, 9])]
    feasible = [fit for fit in fits if fit.success and stability(fit.x) >= -1e-8]
    if not feasible:
        raise RuntimeError('GJR-GARCH estimation did not converge inside the feasible set.')
    return min(feasible, key=lambda fit: fit.fun).x


@njit(parallel=True)
def projected_barriers(initial, coefficients, shocks, intraday, barriers):
    """Simulate minimum log prices using pre-test innovations across all origins."""
    omega, alpha, gamma, beta = coefficients
    close_hits = np.zeros((len(initial), len(barriers)), dtype=np.int64)
    low_hits = np.zeros((len(initial), len(barriers)), dtype=np.int64)
    with_lows = intraday.size > 0
    for i in prange(len(initial)):
        for j in range(shocks.shape[0]):
            h = initial[i]
            level = 0.0
            close_min = 0.0
            low_min = 0.0
            for k in range(shocks.shape[1]):
                scale = np.sqrt(h)
                value = scale * shocks[j, k]
                if with_lows:
                    low_min = min(low_min, level + scale * intraday[j, k])
                level += value
                close_min = min(close_min, level)
                h = omega + (alpha + gamma * (value < 0)) * value**2 + beta * h
            for k in range(len(barriers)):
                close_hits[i, k] += close_min <= barriers[k]
                low_hits[i, k] += low_min <= barriers[k]
    return close_hits, low_hits


def outcomes(origins, closes, lows):
    close = np.array([np.min(closes[i + 1:i + HORIZON + 1]) / closes[i] for i in origins])
    low = np.array([np.min(lows[i + 1:i + HORIZON + 1]) / closes[i] for i in origins])
    return close[:, None] <= 1 - THRESHOLDS, low[:, None] <= 1 - THRESHOLDS


def runs(values):
    return int(np.count_nonzero(values & ~np.r_[False, values[:-1]]))


def smooth(hits, draws):
    return (hits + 0.5) / (draws + 1)


def run(output: Path, forecast_results: Path):
    from numba import get_num_threads, set_num_threads
    set_num_threads(min(8, get_num_threads()))
    bars = read(RAW / 'bitstamp-btcusd-daily.json')['bars']
    closes = np.array([float(bar['close']) for bar in bars])
    lows = np.array([float(bar['low']) for bar in bars])
    labels = [datetime.fromtimestamp(int(bar['timestamp']), UTC).date().isoformat() for bar in bars]
    boundary = labels.index('2023-12-31')
    # Returns are scaled to percentage points only for numerical conditioning.
    rets = 100 * np.diff(np.log(closes))
    train = labels.index('2021-12-31')
    initial = float(np.mean(rets[:train]**2))
    pre = rets[:boundary]
    origins = np.arange(boundary, len(closes) - HORIZON)
    pre_origins = np.arange(0, boundary - HORIZON + 1)
    test_labels = [labels[i] for i in origins]
    assert len(origins) == 702 and len(pre) == 2191
    y_close, y_low = outcomes(origins, closes, lows)
    reference_close, reference_low = outcomes(pre_origins, closes, lows)
    model = read(forecast_results / 'model-results.json')['models']['BTC']
    decay, df = model['selected_lambda'], model['filtered_t_nu']
    ewma_path, _ = ewma(rets, decay, initial)
    gjr = fit_gjr(pre, initial)
    gjr_path = gjr_variances(rets, initial, gjr[:4])

    random = np.random.default_rng(SEED)
    limits = 100 * np.log1p(-THRESHOLDS)
    empty = np.empty((0, 0))
    ewma_shocks = random.standard_t(df, size=(DRAWS, HORIZON)) * np.sqrt((df - 2) / df)
    gjr_shocks = random.standard_t(gjr[4], size=(DRAWS, HORIZON)) * np.sqrt((gjr[4] - 2) / gjr[4])
    ewma_coefficients = np.array([0, 1 - decay, 0, decay])
    ew_close, _ = projected_barriers(ewma_path[origins], ewma_coefficients, ewma_shocks, empty, limits)
    gj_close, _ = projected_barriers(gjr_path[origins], gjr[:4], gjr_shocks, empty, limits)

    innovations = pre / np.sqrt(ewma_path[:boundary])
    centering = innovations.mean()
    scale = innovations.std(ddof=0)
    historical_low = 100 * np.log(lows[1:boundary + 1] / closes[:boundary]) / np.sqrt(ewma_path[:boundary])
    starts = random.integers(0, boundary, size=(DRAWS, HORIZON // 5))
    indices = ((starts[:, :, None] + np.arange(5)) % boundary).reshape(DRAWS, HORIZON)
    bootstrap_close = ((innovations - centering) / scale)[indices]
    bootstrap_low = ((historical_low - centering) / scale)[indices]
    hist_close, hist_low = projected_barriers(ewma_path[origins], ewma_coefficients,
                                               bootstrap_close, bootstrap_low, limits)
    variants = [
        ('Pre-test empirical', 'close', np.tile(smooth(reference_close.sum(axis=0), len(pre_origins)), (len(origins), 1)), y_close),
        ('EWMA Student t', 'close', smooth(ew_close, DRAWS), y_close),
        ('GJR-GARCH Student t', 'close', smooth(gj_close, DRAWS), y_close),
        ('Five-day filtered blocks', 'close', smooth(hist_close, DRAWS), y_close),
        ('Pre-test empirical', 'low', np.tile(smooth(reference_low.sum(axis=0), len(pre_origins)), (len(origins), 1)), y_low),
        ('Five-day filtered blocks', 'low', smooth(hist_low, DRAWS), y_low),
    ]
    output.mkdir(parents=True, exist_ok=True)
    summary = []
    with (output / 'rolling-barriers.csv').open('w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['origin_bucket', 'last_bucket', 'model', 'event', 'decline', 'probability', 'observed'])
        for model_name, event, forecast, actual in variants:
            for j, barrier in enumerate(THRESHOLDS):
                prediction = forecast[:, j]
                truth = actual[:, j]
                brier = np.mean((prediction - truth)**2)
                loss = -np.mean(np.where(truth, np.log(prediction), np.log1p(-prediction)))
                row = {'model': model_name, 'event': event, 'decline': float(barrier),
                       'events': int(truth.sum()), 'hit_runs': runs(truth),
                       'mean_probability': float(prediction.mean()), 'expected_events': float(prediction.sum()),
                       'brier': float(brier), 'log_loss': float(loss)}
                summary.append(row)
                writer.writerows((label, labels[i + HORIZON], model_name, event, barrier, probability, actual_hit)
                                 for label, i, probability, actual_hit in zip(test_labels, origins, prediction, truth))
    save(output / 'rolling-backtest.json', {
        'origins': len(origins), 'start_origin': test_labels[0], 'last_outcome_bucket': labels[-1],
        'horizon_days': HORIZON, 'draws_per_origin': DRAWS, 'seed': SEED,
        'gjr': dict(zip(('omega_pct_squared', 'alpha', 'gamma', 'beta', 'degrees_of_freedom'), map(float, gjr))),
        'gjr_variance_persistence': float(gjr[1] + gjr[2] / 2 + gjr[3]),
        'pre_test_origins': len(pre_origins), 'summary': summary,
    })
    print(f'Rolling validation complete: {len(origins)} held-out origins.', flush=True)
