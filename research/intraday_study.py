"""Replay severe intraday price paths on the captured Morpho borrower books."""

import csv
import hashlib
import math
from pathlib import Path

import numpy as np
from numba import get_num_threads, set_num_threads

from depth_experiment import simulate_recovery
from reproduce_revision import read, save


HERE = Path(__file__).resolve().parent
RAW = HERE / 'raw'
COLLATERAL_FACTOR = {'WBTC': 'BTC', 'cbBTC': 'BTC', 'WETH': 'ETH'}
STABLE_LOANS = {'USDC', 'USDT'}


def depth_from_quotes():
    document = read(RAW / 'morpho-direct-depth.json')
    result = {}
    for market in document['markets']:
        measured = []
        for pool in market['pools']:
            if not pool.get('loan_out_atomic') or pool['sqrt_price_after'] != pool['sqrt_price_target']:
                continue
            before = pool['sqrt_price_before']
            end = pool['sqrt_price_after']
            ratio = (min(before, end) / max(before, end))**2
            if not math.isclose(ratio, 0.98, rel_tol=1e-9):
                continue
            amount = pool['loan_out_atomic'] / 10**market['loan']['decimals']
            measured.append({'pool': pool['pool'], 'fee': pool['fee_pips'] / 1e6,
                             'out_to_2pct': amount, 'equivalent_reserve': amount / (1 - math.sqrt(0.98)),
                             'ticks_crossed': pool['ticks_crossed']})
        result[market['market_id']] = {'block': market['block'], 'block_hash': market.get('block_hash'),
                                       'transport_error': market.get('error'), 'qualified_pools': len(measured),
                                       'direct_route': max(measured, key=lambda x: x['out_to_2pct']) if measured else None}
    return result


def anchor_depth_audit(anchor, reserve):
    depth = read(RAW / 'morpho-anchor-depth-curve.json')['quotes']
    routes = read(RAW / 'morpho-anchor-route-comparison.json')
    assert routes['block_hash'] == anchor['block_hash']
    curve = []
    for pct, snapshot in depth.items():
        assert snapshot['block_hash'] == anchor['block_hash']
        measured = {}
        for pool in snapshot['pools']:
            if pool.get('loan_out_atomic') and pool.get('sqrt_price_after') == pool['sqrt_price_target']:
                before, after = pool['sqrt_price_before'], pool['sqrt_price_after']
                assert math.isclose((min(before, after) / max(before, after))**2, 1 - int(pct) / 100,
                                    rel_tol=1e-9)
                measured[pool['fee_pips']] = pool['loan_out_atomic'] / 10**snapshot['loan']['decimals']
        model = reserve * (1 - math.sqrt(1 - int(pct) / 100))
        observed = measured[3000]
        curve.append({'decline_pct': int(pct), 'direct_30bp_usdc': observed, 'direct_5bp_usdc': measured[500],
                      'model_usdc': model, 'model_error_fraction': model / observed - 1})

    by_size = {}
    for quote in routes['quotes']:
        result = quote['response'].get('result')
        if result and int(result[2:66], 16):
            by_size.setdefault(quote['size_wbtc'], {})[quote['portion'], quote['route']] = int(result[2:66], 16) / 1e6
    routed = []
    for size, quotes in by_size.items():
        singles = {route: proceeds for (portion, route), proceeds in quotes.items() if portion == 1}
        halves = {route: proceeds for (portion, route), proceeds in quotes.items() if portion == 0.5}
        candidates = dict(singles)
        # WBTC/USDC pools are disjoint from either leg of the WETH route.
        for direct in ('500', '3000'):
            for route in halves:
                if route.startswith('WETH/'):
                    candidates[f'{direct} + {route}'] = halves[direct] + halves[route]
        candidates['500 + 3000'] = halves['500'] + halves['3000']
        best = max(candidates, key=candidates.get)
        routed.append({'size_wbtc': size, 'direct_30bp_usdc': singles['3000'], 'direct_5bp_usdc': singles['500'],
                       'best_via_weth_usdc': max(value for route, value in singles.items() if route.startswith('WETH/')),
                       'router_usdc': candidates[best], 'router_choice': best})
    return {'block': routes['block'], 'curve_at_price_limits': curve, 'historical_route_comparison': routed}


def historical_paths(pair):
    daily = {int(day): float(close) for day, close in
             read(HERE.parent / 'data/book/market-history.json')['snapshot']['series'][pair]['closes']}
    doc = read(RAW / f'bitstamp-{pair}-hourly-stress.json')
    episodes, closes, lows_and_closes = [], [], []
    for episode in doc['episodes']:
        bars = episode['bars']
        assert len(bars) == 721 and all(b[0] - a[0] == 3600 for a, b in zip(bars, bars[1:]))
        anchors = np.array([float(b[4]) for b in bars])[::24]
        matched_series = [daily[b[0] - b[0] % 86400] for b in bars[::24]]
        np.testing.assert_allclose(anchors, matched_series, rtol=1e-9, atol=1e-8)
        close = np.array([float(b[4]) for b in bars]) / anchors[0]
        low = np.array([float(b[3]) for b in bars]) / anchors[0]
        interleaved = np.r_[1, np.column_stack((low[1:], close[1:])).ravel()]
        assert np.isfinite(interleaved).all() and (interleaved > 0).all() and np.all(low <= close)
        episodes.append({'origin_bucket': episode['origin_bucket'], 'last_bucket': episode['last_bucket'],
                         'daily_close_drawdown': float(1 - close[::24].min()),
                         'hourly_close_drawdown': float(1 - close.min()),
                         'hourly_low_drawdown': float(1 - interleaved.min()),
                         'end_return': float(close[-1] - 1)})
        closes.append(close)
        lows_and_closes.append(interleaved)
    all_hourly = np.array(closes)
    return episodes, {1: all_hourly[:, ::24], 24: all_hourly, 48: np.array(lows_and_closes)}


def check_clock():
    # The first borrower is solvent at spot even after a very large batch discount.
    c, d = np.array([1000.0, 100.0]), np.array([900.0, 80.0])
    steady = simulate_recovery(np.ones((1, 25)), c, d, 0.86, 0.0, 10.0, steps_per_day=24)
    np.testing.assert_allclose([steady[0][0], steady[1][0], steady[2][0]], [0, 0, 0], atol=1e-9)
    mixed = simulate_recovery(np.array([[1.0, 0.85]]), c, np.array([800.0, 95.0]),
                              0.86, 0.0, 85.0, fee=0.0, terminal_discount=0.0)
    np.testing.assert_allclose([mixed[0][0], mixed[1][0]], [10.0, 52.5], atol=1e-9)
    path = np.array([[1.0, 0.8, 0.8, 0.8, 0.8]])
    c, d = np.array([100.0]), np.array([80.0])
    capped = simulate_recovery(path, c, d, 0.86, 10.0, np.inf, steps_per_day=4)
    np.testing.assert_allclose(capped[2], [10])
    rescued = simulate_recovery(path, c, d, 0.86, np.inf, np.inf, steps_per_day=4, rescue_fraction=0.25)
    np.testing.assert_allclose(rescued[2], [0])
    np.testing.assert_allclose(rescued[6], [11.2])


def experiment(policy):
    label, steps, lag, refill, multiplier, rescue, reserve_factor, cap = policy
    return label, steps, round(steps * lag), refill, multiplier, rescue, reserve_factor, cap


POLICIES = tuple(map(experiment, (
    ('No liquidation', 24, 0, 1.0, 1.0, 0.0, 1.0, 0.0),
    ('No liquidation, half reserve', 24, 0, 1.0, 1.0, 0.0, 0.5, 0.0),
    ('No liquidation, double reserve', 24, 0, 1.0, 1.0, 0.0, 2.0, 0.0),
    ('Daily, prompt', 1, 0, 1.0, 1.0, 0.0, 1.0, math.inf),
    ('Hourly, prompt', 24, 0, 1.0, 1.0, 0.0, 1.0, math.inf),
    ('Hourly lows and closes', 48, 0, 1.0, 1.0, 0.0, 1.0, math.inf),
    ('Hourly, 1% daily cap', 24, 0, 1.0, 1.0, 0.0, 1.0, 0.01),
    ('Hourly, 25% refill', 24, 0, 0.25, 1.0, 0.0, 1.0, math.inf),
    ('Hourly, no refill', 24, 0, 0.0, 1.0, 0.0, 1.0, math.inf),
    ('Hourly, one-day lag', 24, 1, 1.0, 1.0, 0.0, 1.0, math.inf),
    ('Hourly, oracle 2% high', 24, 0, 1.0, 1.02, 0.0, 1.0, math.inf),
    ('Hourly, borrower rescue', 24, 0, 1.0, 1.0, 0.05, 1.0, math.inf),
    ('Hourly, half reserve', 24, 0, 1.0, 1.0, 0.0, 0.5, math.inf),
    ('Hourly, double reserve', 24, 0, 1.0, 1.0, 0.0, 2.0, math.inf),
)))


def run(output: Path, price_dir: Path):
    set_num_threads(min(4, get_num_threads()))
    check_clock()
    study = read(price_dir / 'vault-study.json')
    depths = depth_from_quotes()
    assert len(depths) == len(study['markets']) == 51
    selected = study['selected_market']
    selected_depth = depths[selected['market_id']]['direct_route']
    if selected_depth is None:
        raise ValueError('The selected WBTC/USDC market requires a pinned, positive direct-pool measurement.')
    anchor_c = np.array([position['collateral_value'] for position in selected['positions']])
    anchor_d = np.array([position['debt'] for position in selected['positions']])
    at_open = simulate_recovery(np.ones((1, 25)), anchor_c, anchor_d, selected['lltv'], 0.0,
                                selected_depth['equivalent_reserve'], steps_per_day=24)
    np.testing.assert_allclose([at_open[0][0], at_open[1][0]], [0, 0], atol=1e-9)
    common_depth = selected_depth['equivalent_reserve'] / selected['borrow_assets_sum']
    inputs = {factor: historical_paths(pair) for factor, pair in (('BTC', 'btcusd'), ('ETH', 'ethusd'))}
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    outputs = {}
    for market in study['markets']:
        factor = COLLATERAL_FACTOR.get(market['collateral'])
        if factor is None or market['loan'] not in STABLE_LOANS:
            continue
        episodes, time_grids = inputs[factor]
        identifier = market['market_id']
        measurement = depths[identifier]
        assert measurement['block'] == market['market_block']
        collateral = np.array([p['collateral_value'] for p in market['positions']])
        debt = np.array([p['debt'] for p in market['positions']])
        opening = float(debt.sum())
        loan_usd = opening * market['loan_usd_mark']
        assert opening > 0
        scenarios = [('Standardised', common_depth * opening, selected_depth['fee'])]
        direct = measurement['direct_route']
        if direct:
            scenarios.append(('Direct pool', direct['equivalent_reserve'], direct['fee']))
        for scope, starting_reserve, fee in scenarios:
            for label, steps, lag, refill, basis, rescue, size, cap in POLICIES:
                reserve = size * starting_reserve
                result = simulate_recovery(time_grids[steps], collateral, debt, market['lltv'],
                                           cap * opening, reserve, lag, fee, fee, refill, steps, basis, rescue)
                flat, pool, repaid, _, premium, _, borrower = result
                control_key = identifier, scope, size
                if cap == 0:
                    outputs[control_key] = flat, pool
                none_flat, none_pool = outputs[control_key]
                for i, episode in enumerate(episodes):
                    rows.append({'market_id': identifier, 'collateral': market['collateral'], 'loan': market['loan'],
                                 'opening_debt_loan_tokens': opening, 'opening_debt_usd': loan_usd,
                                 'scope': scope, 'collateral_factor': factor,
                                 'episode': episode['origin_bucket'], 'policy': label,
                                 'quote_reserve_loan_tokens': reserve, 'reserve_multiplier': size, 'fee': fee,
                                 'checks_per_day': steps, 'oracle_lag_days': lag / steps,
                                 'refill_fraction': refill, 'oracle_multiplier': basis,
                                 'borrower_rescue_fraction': rescue, 'daily_cap_fraction': None if math.isinf(cap) else cap,
                                 'flat_loss_bp': flat[i] / opening * 1e4, 'pool_loss_bp': pool[i] / opening * 1e4,
                                 'flat_delta_bp': (flat[i] - none_flat[i]) / opening * 1e4,
                                 'pool_delta_bp': (pool[i] - none_pool[i]) / opening * 1e4,
                                 'pool_net_recovery_bp': (1 - pool[i] / opening) * 1e4,
                                 'liquidated_debt_bp': repaid[i] / opening * 1e4,
                                 'outside_repayment_bp': borrower[i] / opening * 1e4,
                                 'insolvent_premium_bp': premium[i] / opening * 1e4})

    with (output / 'intraday-policy-grid.csv').open('w', encoding='utf-8', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    def summary(group):
        return {key: float(np.mean([row[key] for row in group]))
                for key in ('flat_loss_bp', 'pool_loss_bp', 'flat_delta_bp', 'pool_delta_bp',
                            'liquidated_debt_bp', 'outside_repayment_bp', 'insolvent_premium_bp',
                            'pool_net_recovery_bp')}

    selected_rows = [r for r in rows if r['market_id'] == selected['market_id'] and r['scope'] == 'Direct pool']
    selected_summary = {p[0]: summary([r for r in selected_rows if r['policy'] == p[0]]) for p in POLICIES}
    book_summary = {}
    for factor in inputs:
        book_rows = [r for r in rows if r['scope'] == 'Standardised' and r['collateral_factor'] == factor]
        book_summary[factor] = {
            'markets': len({r['market_id'] for r in book_rows}),
            'policy_medians_bp': {p[0]: {key: float(np.median([row[key] for row in book_rows if row['policy'] == p[0]]))
                                         for key in ('flat_loss_bp', 'pool_loss_bp', 'flat_delta_bp', 'pool_delta_bp')}
                                  for p in POLICIES},
        }
    save(output / 'intraday-study.json', {
        'scanned_markets': len(depths), 'replayed_markets': len({r['market_id'] for r in rows}), 'rows': len(rows),
        'replayed_direct_quotes': len({r['market_id'] for r in rows if r['scope'] == 'Direct pool'}),
        'positive_direct_quotes': sum(bool(m['direct_route']) for m in depths.values()),
        'transport_errors': sum(bool(m['transport_error']) for m in depths.values()),
        'standardised_reserve_per_debt': common_depth, 'standardised_fee': selected_depth['fee'],
        'episodes_by_factor': {factor: series[0] for factor, series in inputs.items()},
        'selected_depth': depths[selected['market_id']], 'depth_by_market': depths,
        'anchor_depth_audit': anchor_depth_audit(depths[selected['market_id']], selected_depth['equivalent_reserve']),
        'selected_policy_means_bp': selected_summary,
        'standardised_by_factor': book_summary,
        'inputs_sha256': {name: hashlib.sha256((RAW / name).read_bytes()).hexdigest() for name in
                          ('morpho-direct-depth.json', 'bitstamp-btcusd-hourly-stress.json',
                           'bitstamp-ethusd-hourly-stress.json', 'morpho-anchor-depth-curve.json',
                           'morpho-anchor-route-comparison.json')},
    })
    print(f'Intraday grid complete: {len(rows):,} market-policy-episode observations.', flush=True)
