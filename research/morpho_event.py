"""Capture and replay the WBTC/USDC Morpho market on 10 October 2025."""

import argparse
from datetime import UTC, datetime
from pathlib import Path
from time import sleep
from urllib.error import HTTPError
from urllib.parse import urlencode

from capture_stress_inputs import ENDPOINT, RPC, get, quote_market, word, write_once
from reproduce_revision import read, save


RAW = Path(__file__).resolve().parent / 'raw'
SOURCE = RAW / 'morpho-wbtc-2025-10-10.json'
MARKET = '0x3a85e619751152991742810df6ec69ce473daef99e28a64ab2340d7b7ccfee49'
MORPHO = '0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb'
BORROW = '0x570954540bed6b1304a87dfe815a5eda4a648f7097a16240dcd85c9b5fd42a43'
LIQUIDATE = '0xa4946ede45d0c6f06a0f5ce92c9ad3b4751452d2fe0e25010783bcab57a67e41'
OPEN, CLOSE = 23543615, 23550763
FORK = 'http://127.0.0.1:18547'
UNIT = 10**6
WAD = 10**18


def words(data):
    return [int(data[i:i+64], 16) for i in range(2, len(data), 64)]


def rpc(methods, endpoint=RPC, size=10):
    for start in range(0, len(methods), size):
        batch = methods[start:start + size]
        requests = [{'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params}
                    for i, (method, params) in enumerate(batch)]
        for attempt in range(6):
            try:
                response = {entry['id']: entry for entry in get(endpoint, requests)}
                break
            except HTTPError as error:
                if error.code not in (429, 502, 503, 504) or attempt == 5:
                    raise
                after = error.headers.get('Retry-After', '')
                sleep(int(after) if after.isdecimal() else 3 * (attempt + 1))
        for i in range(len(batch)):
            if 'error' in response[i]:
                raise RuntimeError(f'{batch[i][0]}: {response[i]["error"]}')
            yield response[i]['result']


def call(target, data, block):
    return 'eth_call', [{'to': target, 'data': data}, hex(block)]


def header(block):
    return 'eth_getBlockByNumber', [hex(block), False]


def chain_logs(topic, start, end, step):
    filters = [('eth_getLogs', [{'fromBlock': hex(left), 'toBlock': hex(min(left + step - 1, end)),
                                 'address': MORPHO, 'topics': [topic, MARKET]}])
               for left in range(start, end + 1, step)]
    return [log for chunk in rpc(filters, size=4) for log in chunk]


def accrual(market, rate, timestamp):
    elapsed = timestamp - market[4]
    first = rate * elapsed
    second = first * first // (2 * WAD)
    third = second * first // (3 * WAD)
    return market[2] + market[2] * (first + second + third) // WAD


def capture():
    if SOURCE.exists():
        raise FileExistsError(SOURCE)
    metadata = '0x2c3c9157' + word(MARKET)
    market_call = '0x5c60e39a' + word(MARKET)
    fork_head, fork_market, fork_params = list(rpc([header(OPEN), call(MORPHO, market_call, OPEN),
                                                    call(MORPHO, metadata, OPEN)], FORK))
    params, market_state, archive_head = list(rpc([call(MORPHO, metadata, OPEN),
                                                  call(MORPHO, market_call, OPEN),
                                                  header(OPEN)]))
    assert fork_head['hash'] == archive_head['hash']
    assert fork_market == market_state and fork_params == params
    market = words(market_state)
    loan, collateral, oracle, irm = ['0x' + f'{field:040x}' for field in words(params)[:4]]
    assert loan.lower() == '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'
    assert collateral.lower() == '0x2260fac5e5542a773aa44fbcfedf7c193bc2c599'
    assert int(fork_head['number'], 16) == OPEN
    history = chain_logs(BORROW, 18_800_000, OPEN, 100_000)
    # Borrow indexes (market, onBehalf, receiver). Caller is in the data.
    addresses = sorted({'0x' + row['topics'][2][-40:] for row in history})
    print(f'Found {len(addresses)} distinct historical borrowers.', flush=True)
    position_calls = [call(MORPHO, '0x93c52062' + word(MARKET) + word(address), OPEN) for address in addresses]
    positions = [[address, value] for address, value in zip(addresses, rpc(position_calls, size=18))
                 if words(value)[1]]
    assert sum(words(value)[1] for _, value in positions) == market[3]
    sample = [positions[0], positions[len(positions) // 2], positions[-1]]
    sample_calls = [call(MORPHO, '0x93c52062' + word(MARKET) + word(address), OPEN) for address, _ in sample]
    rate = next(rpc([call(irm, '0x8c00bf6b' + params[2:] + market_state[2:], OPEN)]))
    event_logs = chain_logs(LIQUIDATE, OPEN + 1, CLOSE, 100_000)
    close = next(rpc([header(CLOSE)]))
    header_data = lambda h: [int(h['number'], 16), h['hash'], int(h['timestamp'], 16)]
    day_start = int(datetime(2025, 10, 10, tzinfo=UTC).timestamp())
    assert header_data(fork_head)[2] < day_start <= header_data(fork_head)[2] + 30
    assert day_start + 86400 - 30 <= header_data(close)[2] < day_start + 86400
    blocks = sorted({OPEN, CLOSE, *range(OPEN, CLOSE, 25)})
    path_headers = [header_data(block) for block in rpc([header(b) for b in blocks], size=15)]
    print(f'Captured {len(path_headers)} block timestamps.', flush=True)
    oracle_states = list(rpc([call(oracle, '0xa035b1fe', b) for b in blocks], size=15))
    assert list(rpc([*sample_calls, call(oracle, '0xa035b1fe', OPEN)], FORK)) == [
        *[value for _, value in sample], oracle_states[0]]
    candles, urls = {}, []
    for offset in (0, 12 * 3600):
        start = day_start + offset - 120
        url = ENDPOINT + 'btcusd/?' + urlencode({'step': 60, 'start': start,
                'end': start + 12 * 3600 + 180, 'limit': 1000, 'exclude_current_candle': 'true'})
        urls.append(url)
        candles.update({int(row['timestamp']): row['close'] for row in get(url)['data']['ohlc']})
    for block, _, timestamp in path_headers:
        if timestamp - timestamp % 60 - 60 not in candles:
            raise ValueError(f'No completed minute candle for block {block}.')
    depth = quote_market((MARKET, OPEN, {'address': collateral, 'decimals': 8}, {'address': loan, 'decimals': 6}))
    assert depth['block_hash'] == fork_head['hash']
    write_once(SOURCE.name, {'source': RPC, 'captured_utc': datetime.now(UTC).isoformat(),
        'local_fork': {'client': next(rpc([('web3_clientVersion', [])], FORK)),
                       'opening_block': header_data(fork_head), 'matched_positions': sample,
                       'matched_market_state': fork_market, 'matched_oracle_state': oracle_states[0]},
        'market_id': MARKET, 'params': params, 'market_state': market_state, 'borrow_rate': rate,
        'candidate_count': len(addresses), 'history_range': [18800000, OPEN], 'positions': positions,
        'observed_liquidations': event_logs, 'block_path': [row + [oracle_state] for row, oracle_state in
                           zip(path_headers, oracle_states)], 'minute_spot_urls': urls, 'minute_spot': candles,
        'opening_depth': depth})
    print(f'Retained {len(positions)} opening debt positions and {len(event_logs)} liquidation logs.', flush=True)


def run(output):
    import math

    import numpy as np

    from depth_experiment import simulate_recovery

    doc = read(SOURCE)
    first = doc['block_path'][0]
    assert first[:3] == doc['local_fork']['opening_block']
    market = words(doc['market_state'])
    positions = {address: words(data) for address, data in doc['positions']}
    assert sum(p[1] for p in positions.values()) == market[3]
    borrow_assets = accrual(market, int(doc['borrow_rate'], 16), first[2])
    # Borrow balance rounds upward, with 1 virtual asset and 10^6 virtual shares.
    denom = market[3] + UNIT
    debts = [(p[1] * (borrow_assets + 1) + denom - 1) // denom for p in positions.values()]
    opening_oracle = int(first[3], 16)
    collateral = np.array([p[2] * opening_oracle / 10**36 / UNIT for p in positions.values()])
    debt = np.array(debts) / UNIT
    oracle = np.array([[int(row[3], 16) / opening_oracle for row in doc['block_path']]])
    spot = np.array([[float(doc['minute_spot'][str(row[2] - row[2] % 60 - 60)]) for row in doc['block_path']]])
    spot *= (spot[0, 0] ** -1)
    observed = {}
    for event in doc['observed_liquidations']:
        assert event['topics'][:2] == [LIQUIDATE, MARKET]
        borrower = '0x' + event['topics'][3][-40:]
        repaid, _, seized, bad_debt, _ = words(event['data'])
        assert repaid > 0 and seized > 0
        previous = observed.get(borrower, (0, 0))
        observed[borrower] = previous[0] + repaid, previous[1] + bad_debt
    pools = [p for p in doc['opening_depth']['pools'] if p.get('loan_out_atomic')
             and p['sqrt_price_target'] == p.get('sqrt_price_after')]
    direct = max(pools, key=lambda p: p['loan_out_atomic'])
    reserve = direct['loan_out_atomic'] / UNIT / (1 - math.sqrt(.98))
    fee = direct['fee_pips'] / 1e6
    modes = []
    for name, size, refill_steps in [('Direct pool, open depth', reserve, spot.size - 1),
                                     ('Direct pool, hourly refill', reserve, 12),
                                     ('Unbounded execution', np.inf, spot.size - 1)]:
        paid = np.zeros((1, len(positions)))
        flat, pool, repayment, _, _, writeoff, _ = simulate_recovery(
            spot, collateral, debt, words(doc['params'])[4] / WAD, np.inf, size, fee=fee,
            terminal_discount=fee, steps_per_day=refill_steps, oracle_paths=oracle, account_repaid=paid)
        predicted = {address for address, value in zip(positions, paid[0]) if value > 1e-6}
        modes.append({'policy': name, 'borrowers_liquidated': len(predicted),
                      'actual_borrowers_also_predicted': len(predicted.intersection(observed)),
                      'repayment_usdc': float(repayment[0]), 'writeoff_usdc': float(writeoff[0]),
                      'terminal_loss_usdc': float(pool[0]), 'addresses': sorted(predicted)})
    save(output / 'historical-event.json', {
        'date_utc': '2025-10-10', 'market_id': MARKET, 'opening_block': first[:3],
        'closing_block': doc['block_path'][-1][:3], 'observed_book_borrowers': len(positions),
        'opening_debt_usdc': float(debt.sum()), 'observed_total_borrow_shares': str(market[3]),
        'oracle_path_marks': oracle.size, 'minimum_oracle_return': float(oracle.min() - 1),
        'minimum_spot_return': float(spot.min() - 1), 'direct_reserve_usdc': reserve, 'direct_fee': fee,
        'observed': {'liquidations': len(doc['observed_liquidations']), 'borrowers': len(observed),
                     'borrowers_in_opening_book': len(set(positions).intersection(observed)),
                     'repayment_usdc': sum(p[0] for p in observed.values()) / UNIT,
                     'bad_debt_usdc': sum(p[1] for p in observed.values()) / UNIT},
        'model': modes,
    })


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--output', type=Path, default=SOURCE.parent.parent / 'generated/v2.0')
    args = parser.parse_args()
    if args.capture:
        capture()
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        run(args.output)
