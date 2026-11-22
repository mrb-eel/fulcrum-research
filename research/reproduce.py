"""Regenerate the paper's numerical results from retained evidence offline."""

import csv
import json
import math
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from verify_evidence import verify

RESEARCH = Path(__file__).resolve().parent
REFERENCE = RESEARCH / "results"
OUTPUT = RESEARCH / "generated"


def compare(expected, actual, location, *, relative=1e-9, absolute=1e-8):
    """Compare integers and structure exactly, allowing float roundoff."""
    if type(expected) is not type(actual):
        raise ValueError(
            f"{location}: expected {type(expected).__name__}, got {type(actual).__name__}"
        )

    if isinstance(expected, dict):
        if actual.keys() != expected.keys():
            raise ValueError(
                f"{location}: differing keys {expected.keys() ^ actual.keys()}"
            )
        for key, value in expected.items():
            compare(
                value,
                actual[key],
                f"{location}.{key}",
                relative=relative,
                absolute=absolute,
            )
        return
    if isinstance(expected, list):
        if len(expected) != len(actual):
            raise ValueError(
                f"{location}: expected {len(expected)} rows, got {len(actual)}"
            )
        for index, (left, right) in enumerate(zip(expected, actual)):
            compare(
                left,
                right,
                f"{location}[{index}]",
                relative=relative,
                absolute=absolute,
            )
        return

    matches = expected == actual
    if isinstance(expected, float):
        matches = math.isclose(expected, actual, rel_tol=relative, abs_tol=absolute)
    if not matches:
        raise ValueError(f"{location}: expected {expected!r}, got {actual!r}")


def read_result(directory, name):
    return json.loads((directory / name).read_text(encoding="utf-8"))


def compare_outputs(generated):
    for name in (
        "vault-study.json",
        "model-results.json",
        "test-forecasts.json",
        "liquidation-study.json",
        "compound-event-study.json",
        "compound-reconciliation.json",
    ):
        expected = read_result(REFERENCE, name)
        actual = read_result(generated, name)
        # The archived report used a Windows path to the in-place NPZ file.
        if name == "liquidation-study.json":
            expected["price_paths_file"] = (
                expected["price_paths_file"].replace("\\", "/").split("/")[-1]
            )

        relative, absolute = 1e-9, 1e-8
        if name == "model-results.json":
            # Fitted parameters can differ slightly between numerical libraries.
            relative, absolute = 2e-6, 1e-8
        elif name == "test-forecasts.json":
            relative, absolute = 2e-6, 1e-8
        elif name == "liquidation-study.json":
            # Price-path roundoff can reach a fraction of a USDC in tail loss.
            relative, absolute = 2e-6, 1e-6
        compare(expected, actual, name, relative=relative, absolute=absolute)
        print(f"Matched {name}", flush=True)

    with (REFERENCE / "compound-events.csv").open(
        encoding="utf-8", newline=""
    ) as expected:
        with (generated / "compound-events.csv").open(
            encoding="utf-8", newline=""
        ) as actual:
            compare(
                list(csv.reader(expected)),
                list(csv.reader(actual)),
                "compound-events.csv",
            )
    print("Matched compound-events.csv", flush=True)


def main():
    evidence = verify()
    print(
        f"Verified {evidence['offline_checks_passed']} retained-evidence checks.",
        flush=True,
    )

    import empirical_models
    import liquidation_study
    import vault_study

    OUTPUT.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=OUTPUT, prefix="replication-") as temp:
        generated = Path(temp)
        subprocess.run(
            [
                sys.executable,
                "-B",
                str(RESEARCH / "rebuild_compound.py"),
                "--output",
                str(generated),
            ],
            check=True,
        )
        vault_study.run(generated)
        empirical_models.run(generated)
        liquidation_study.self_test()
        liquidation_study.run(generated / "btc-price-paths.npz", generated)
        compare_outputs(generated)
        for artifact in generated.iterdir():
            artifact.replace(OUTPUT / artifact.name)
    print("Regenerated research outputs in research/generated/.", flush=True)


if __name__ == "__main__":
    main()
