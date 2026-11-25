"""Regenerate the lender-loss paper's forecast and intraday experiments offline."""

import argparse
import csv
import math
from itertools import zip_longest
from pathlib import Path
from tempfile import TemporaryDirectory

from barrier_backtest import DRAWS, run as validate_barriers
from intraday_study import run as replay_history
from morpho_event import run as replay_event
from reproduce import compare
from reproduce_revision import OUTPUT as PRICE_OUTPUT, main as reproduce_v11, read


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / 'generated/v2.0'
REFERENCE = HERE / 'results/v2.0'
REPORTS = ('rolling-backtest.json', 'intraday-study.json', 'historical-event.json')
LEDGERS = ('rolling-barriers.csv', 'intraday-policy-grid.csv')


def compare_ledger(reference, fresh):
    with reference.open(newline='', encoding='utf-8') as a, fresh.open(newline='', encoding='utf-8') as b:
        left, right = csv.reader(a), csv.reader(b)
        columns = next(left)
        if columns != next(right):
            raise ValueError(f'{fresh.name}: columns differ')
        forecasts = fresh.name == 'rolling-barriers.csv'
        model_column = columns.index('model') if forecasts else None
        probability_column = columns.index('probability') if forecasts else None
        for line, (expected, actual) in enumerate(zip_longest(left, right), start=2):
            if expected is None or actual is None or len(expected) != len(actual):
                raise ValueError(f'{fresh.name}:{line}: row missing or incomplete')
            for column, (stored, generated) in enumerate(zip(expected, actual)):
                if stored == generated:
                    continue
                try:
                    if column == probability_column and expected[model_column] == 'GJR-GARCH Student t':
                        # Optimiser differences can switch a draw on the barrier.
                        # Allow two hit counts at each origin for this fitted challenger.
                        close = math.isclose(float(stored), float(generated), rel_tol=0,
                                             abs_tol=2 / (DRAWS + 1) + 1e-12)
                    else:
                        close = math.isclose(float(stored), float(generated), rel_tol=2e-5, abs_tol=2e-6)
                except ValueError:
                    close = False
                if not close:
                    raise ValueError(f'{fresh.name}:{line}: expected {stored!r}, got {generated!r}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reuse-paths', action='store_true', help='Use the paths from a recent v1.1 replication.')
    args = parser.parse_args()
    if not args.reuse_paths:
        reproduce_v11()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=OUTPUT, prefix='run-') as directory:
        fresh = Path(directory)
        validate_barriers(fresh, PRICE_OUTPUT)
        replay_history(fresh, PRICE_OUTPUT)
        replay_event(fresh)
        for name in REPORTS:
            compare(read(REFERENCE / name), read(fresh / name), name, relative=2e-5, absolute=2e-6)
            print(f'Matched {name}', flush=True)
        for name in LEDGERS:
            compare_ledger(REFERENCE / name, fresh / name)
            print(f'Matched {name}', flush=True)
        for artifact in fresh.iterdir():
            artifact.replace(OUTPUT / artifact.name)


if __name__ == '__main__':
    main()
