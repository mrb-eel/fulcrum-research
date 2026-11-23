"""Capture public hourly BTC candles and pinned, read-only direct-pool depth quotes."""

import argparse
import csv
import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import sleep
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


HERE = Path(__file__).resolve().parent
RAW = HERE / 'raw'
RPC = 'https://ethereum.reth.rs/rpc'
FACTORY = '0x1F98431c8aD98523631AE4a59f267346ea31F984'
QUOTER = '0x61fFE014bA17989E743c5F6cB21bF9697530B21e'
ENDPOINT = 'https://www.bitstamp.net/api/v2/ohlc/'
NUMBER_OF_EPISODES = 4


def get(url, body=None):
    headers = {'User-Agent': 'Fulcrum-Research/2.0', 'Content-Type': 'application/json'}
    request = Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with urlopen(request, timeout=45) as response:
        return json.load(response)


def write_once(name, record):
    with (RAW / name).open('x', encoding='utf-8', newline='\n') as file:
        json.dump(record, file, separators=(',', ':'))
        file.write('\n')


def episode_windows():
    with (HERE / 'results/v1.1/historical-btc-windows.csv').open(encoding='utf-8', newline='') as file:
        ranked = sorted(csv.DictReader(file), key=lambda row: float(row['minimum_low_ratio']))
    selected = []
    for row in ranked:
        anchor = date.fromisoformat(row['anchor_bucket'])
        last = date.fromisoformat(row['last_bucket'])
        # The anchor candle and the complete following 30 days may appear once.
        if any(anchor <= end and first <= last for first, end in selected):
            continue
        selected.append((anchor, last))
        if len(selected) == NUMBER_OF_EPISODES:
            return selected
    raise ValueError('Too few non-overlapping historical stress windows.')


def stamp(day):
    return int(datetime.combine(day, datetime.min.time(), UTC).timestamp())


def capture_hourly(pair='btcusd'):
    name = f'bitstamp-{pair}-hourly-stress.json'
    if (RAW / name).exists():
        raise FileExistsError('Retained hourly observations already exist.')
    episodes = []
    for anchor, end in episode_windows():
        start_stamp = stamp(anchor) + 23 * 3600
        last_stamp = stamp(end) + 23 * 3600
        url = f'{ENDPOINT}{pair}/?' + urlencode({'step': 3600, 'limit': 1000, 'start': start_stamp,
                                           'end': last_stamp + 3600, 'exclude_current_candle': 'true'})
        result = get(url)['data']['ohlc']
        records = sorted([[int(x['timestamp']), x['open'], x['high'], x['low'], x['close']] for x in result
                          if start_stamp <= int(x['timestamp']) <= last_stamp])
        if [row[0] for row in records] != list(range(start_stamp, last_stamp + 3600, 3600)):
            raise ValueError(f'Incomplete hourly series for {anchor}: {len(records)} observations')
        episodes.append({'origin_bucket': str(anchor), 'last_bucket': str(end), 'source': url, 'bars': records})
        print(f'{anchor} to {end}: {len(records)} hourly bars', flush=True)
    write_once(name, {'captured_utc': datetime.now(UTC).isoformat(),
              'bar_columns': ['bucket', 'open', 'high', 'low', 'close'], 'episodes': episodes})


def word(value):
    return (value[2:] if isinstance(value, str) else format(value, 'x')).zfill(64)


def capture_depth():
    if (RAW / 'morpho-direct-depth.json').exists():
        raise FileExistsError('Retained depth observations already exist.')
    study = json.loads((HERE / 'results/vault-study.json').read_text(encoding='utf-8'))
    snapshots = {}
    arguments = []
    for market in study['markets']:
        source = market['source_file']
        if source not in snapshots:
            packet = json.loads((HERE.parent / 'data/book' / source).read_text(encoding='utf-8'))
            snapshots[source] = {a['market']['marketId'].lower(): a['market']
                                 for a in packet['snapshot']['vault']['state']['allocation']}
        raw = snapshots[source][market['market_id']]
        arguments.append((market['market_id'], int(market['market_block']), raw['collateralAsset'], raw['loanAsset']))
    records = []
    for args in arguments:
        try:
            records.append(quote_market(args))
        except (OSError, KeyError, ValueError) as error:
            market_id, block, collateral, loan = args
            records.append({'market_id': market_id, 'block': block, 'collateral': collateral,
                            'loan': loan, 'pools': [], 'error': str(error)})
        if len(records) % 10 == 0:
            print(f'{len(records)} market blocks processed.', flush=True)
    write_once('morpho-direct-depth.json', {'chain_id': 1, 'source': RPC, 'pool_factory': FACTORY,
               'captured_utc': datetime.now(UTC).isoformat(), 'quoter': QUOTER, 'markets': records})
    print(f'{len(records)} market blocks inspected.', flush=True)


def quote_market(args, decline_pct=2):
    market_id, block, collateral, loan = args
    token_in = collateral['address'].lower()
    token_out = loan['address'].lower()
    collateral_is_token0 = int(token_in, 16) < int(token_out, 16)
    journal = []

    def batch(calls):
        requests = [{'jsonrpc': '2.0', 'id': len(journal) + i + 1, 'method': method, 'params': params}
                    for i, (method, params) in enumerate(calls)]
        if not requests:
            return []
        for attempt in range(4):
            try:
                sleep(0.75)
                by_id = {record['id']: record for record in get(RPC, requests)}
                responses = [by_id[request['id']] for request in requests]
                break
            except HTTPError as error:
                if error.code != 429 or attempt == 3:
                    raise
                retry_after = error.headers.get('Retry-After', '')
                sleep(int(retry_after) if retry_after.isdecimal() else 4 * (attempt + 1))
            except (OSError, KeyError, TypeError):
                if attempt == 3:
                    raise
        journal.extend({'request': req, 'response': res} for req, res in zip(requests, responses))
        return [response.get('result') for response in responses]

    def contract(address, data):
        return 'eth_call', [{'to': address, 'data': data}, hex(block)]

    def words(value):
        return [int(value[i:i+64], 16) for i in range(2, len(value), 64)]

    fees = (100, 500, 3000, 10000)
    header, *factory_calls = batch([('eth_getBlockByNumber', [hex(block), False])] + [
        contract(FACTORY, '0x1698ee82' + word(token_in) + word(token_out) + word(fee)) for fee in fees
    ])
    if not header or int(header['number'], 16) != block:
        raise ValueError('Missing capture block header.')
    results = [{'fee_pips': fee, 'pool': '0x' + addr[-40:] if addr and len(addr) == 66 and int(addr, 16) else None,
                'factory_error': not bool(addr)} for fee, addr in zip(fees, factory_calls)]
    existing = [record for record in results if record['pool']]
    prices = batch([contract(record['pool'], '0x3850c7bd') for record in existing])
    quote_calls, measured = [], []
    for record, result in zip(existing, prices):
        if not result or result == '0x' or not words(result)[0]:
            record['slot0_unavailable'] = True
            continue
        price = words(result)[0]
        remaining_pct = 100 - decline_pct
        target = (math.isqrt(price * price * remaining_pct // 100) if collateral_is_token0
                  else math.isqrt(price * price * 100 // remaining_pct) + 1)
        # A large read-only input ensures the price target, rather than the input,
        # stops the quote. QuoterV2 returns the resulting price and proceeds.
        quantity = 10**int(collateral['decimals']) * 10**10
        data = '0xc6a5026a' + ''.join(word(x) for x in (token_in, token_out, quantity, record['fee_pips'], target))
        quote_calls.append(contract(QUOTER, data))
        measured.append(record)
        record.update(sqrt_price_before=price, sqrt_price_target=target)
    for record, result in zip(measured, batch(quote_calls)):
        if not result:
            record['quote_failed'] = True
            continue
        out, end_price, crossed, _ = words(result)
        record.update(sqrt_price_after=end_price, loan_out_atomic=out, ticks_crossed=crossed)
    return {'market_id': market_id, 'block': block, 'block_hash': header['hash'], 'collateral': collateral,
            'loan': loan, 'pools': results, 'journal': journal}


def capture_anchor_depth():
    prior = json.loads((RAW / 'morpho-direct-depth.json').read_text(encoding='utf-8'))
    study = json.loads((HERE / 'results/vault-study.json').read_text(encoding='utf-8'))
    anchor_id = study['selected_market']['market_id']
    anchor = next(row for row in prior['markets'] if row['market_id'] == anchor_id)
    args = (anchor_id, anchor['block'], anchor['collateral'], anchor['loan'])
    quotes = {'2': anchor}
    for decline_pct in (5, 10, 20, 40):
        quotes[str(decline_pct)] = quote_market(args, decline_pct)
        sleep(1)
    write_once('morpho-anchor-depth-curve.json', {'source': RPC, 'captured_utc': datetime.now(UTC).isoformat(),
                'quotes': quotes})


def capture_anchor_routes():
    """Compare direct and routed execution on the same historical state."""
    from morpho_event import call, rpc

    quotes = json.loads((RAW / 'morpho-anchor-depth-curve.json').read_text(encoding='utf-8'))['quotes']['2']
    collateral, loan = (quotes[key]['address'].lower()[2:] for key in ('collateral', 'loan'))
    weth = 'c02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
    block = quotes['block']
    paths = {str(fee): collateral + f'{fee:06x}' + loan for fee in (500, 3000)}
    for left in (500, 3000):
        for right in (500, 3000):
            paths[f'WETH/{left}/{right}'] = collateral + f'{left:06x}' + weth + f'{right:06x}' + loan

    cases, results = [], []
    for size in (1, 10, 50, 100, 200):
        for portion in (0.5, 1.0):
            amount = int(size * portion * 10**quotes['collateral']['decimals'])
            for name, path in paths.items():
                # quoteExactInput(bytes,uint256), path offset then quantity and padded path.
                data = '0xcdca1753' + word(64) + word(amount) + word(len(path) // 2) + path.ljust(128, '0')
                cases.append((size, portion, name, data))
    for start in range(0, len(cases), 10):
        requests = [{'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params}
                    for i, (method, params) in enumerate(call(QUOTER, row[3], block) for row in cases[start:start+10])]
        for attempt in range(5):
            try:
                batch = sorted(get(RPC, requests), key=lambda row: row['id'])
                break
            except HTTPError as error:
                if error.code != 429 or attempt == 4:
                    raise
                sleep(4 * (attempt + 1))
        results.extend(batch)
    header = next(rpc([('eth_getBlockByNumber', [hex(block), False])]))
    assert header['hash'] == quotes['block_hash']
    write_once('morpho-anchor-route-comparison.json', {'source': RPC, 'block': block,
        'block_hash': header['hash'], 'quoter': QUOTER, 'paths': paths,
        'quotes': [{'size_wbtc': size, 'portion': portion, 'route': route, 'calldata': data, 'response': response}
                   for (size, portion, route, data), response in zip(cases, results)]})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', choices=['hourly', 'eth-hourly', 'depth', 'anchor-depth', 'anchor-routes'])
    args = parser.parse_args()
    {'hourly': capture_hourly, 'eth-hourly': lambda: capture_hourly('ethusd'),
     'depth': capture_depth, 'anchor-depth': capture_anchor_depth, 'anchor-routes': capture_anchor_routes}[args.source]()
