"""Regenerate the lender-loss paper's forecast and intraday experiments offline."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from barrier_backtest import run as validate_barriers
from intraday_study import run as replay_history, simulated_stress
from reproduce import compare
from reproduce_revision import OUTPUT as PRICE_OUTPUT, main as reproduce_v11, read


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / 'generated/v2.0'
REFERENCE = HERE / 'results/v2.0'
REPORTS = ('rolling-backtest.json', 'intraday-study.json', 'conditional-stress.json')


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
        simulated_stress(fresh, PRICE_OUTPUT)
        for name in REPORTS:
            compare(read(REFERENCE / name), read(fresh / name), name, relative=2e-5, absolute=2e-6)
            print(f'Matched {name}', flush=True)
        for artifact in fresh.iterdir():
            artifact.replace(OUTPUT / artifact.name)


if __name__ == '__main__':
    main()
