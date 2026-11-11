"""Build the actual dbt DAG, check exact Python parity, then reject a future filing."""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from statementtrace.cashflow import compare
from statementtrace.contracts import ContractError, canonical, read_json
from statementtrace.warehouse import crosscheck_mart, dependencies, records, verify_warehouse

ROOT = Path(__file__).resolve().parents[1]


def dbt_build(facts, root, name):
    target = root / name
    env = {
        **os.environ,
        "STATEMENTTRACE_FACTS": str(facts.resolve()),
        "STATEMENTTRACE_DUCKDB": str((root / f"{name}.duckdb").resolve()),
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
        "DBT_USE_COLORS": "false",
        "DBT_PARTIAL_PARSE": "false",
    }
    run = subprocess.run(
        [
            sys.executable,
            "-c",
            "from dbt.cli.main import cli; cli()",
            "build",
            "--project-dir",
            str(ROOT / "warehouse_dbt"),
            "--profiles-dir",
            str(ROOT / "warehouse_dbt"),
            "--target-path",
            str(target),
            "--log-path",
            str(root / f"{name}-logs"),
        ],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    artifact = target / "run_results.json"
    if not artifact.is_file():
        raise ContractError("dbt produced no run_results.json:\n" + run.stdout[-6000:] + run.stderr[-2000:])
    return run, read_json(artifact.read_bytes())["results"]


def check(directory):
    packet = Path(directory).resolve()
    verify_warehouse(packet)
    pl, duckdb = dependencies()
    case = read_json((packet / "case.json").read_bytes())
    expected = compare(case, read_json((packet / "request.json").read_bytes())["as_of"])
    with tempfile.TemporaryDirectory(prefix="statementtrace-dbt-") as temp:
        root = Path(temp)
        run, results = dbt_build(packet / "source_facts.parquet", root, "valid")
        if run.returncode or any(row["status"] not in ("success", "pass") for row in results):
            raise ContractError("dbt valid packet failed:\n" + run.stdout[-8000:] + run.stderr[-2000:])
        with duckdb.connect(str(root / "valid.duckdb"), read_only=True, config={"threads": 2}) as db:
            parity, _ = crosscheck_mart(expected, records(db, "SELECT * FROM mart_cashflow"))
        # Rehashing a bad source cannot bypass the dbt cutoff test.
        bad = root / "future_filing.parquet"
        (
            pl.read_parquet(packet / "source_facts.parquet")
            .with_row_index()
            .with_columns(
                pl.when(pl.col("index") == 0)
                .then(pl.col("as_of") + pl.duration(days=1))
                .otherwise(pl.col("filed"))
                .alias("filed")
            )
            .drop("index")
            .write_parquet(bad)
        )
        rejected, bad_results = dbt_build(bad, root, "invalid")
        cutoff = next((row for row in bad_results if row["unique_id"].endswith(".filing_cutoff")), None)
        if rejected.returncode == 0 or not cutoff or cutoff["status"] != "fail" or cutoff["failures"] != 1:
            raise ContractError("dbt did not reject the single future filing:\n" + rejected.stdout[-6000:])
    return {
        "dbt_models": sum(row["unique_id"].startswith("model.") for row in results),
        "dbt_tests": sum(row["unique_id"].startswith("test.") for row in results),
        "python_dbt": parity,
        "future_filing_rejected": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    args = parser.parse_args()
    print(canonical(check(args.directory)).decode(), end="")
