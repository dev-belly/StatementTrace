"""Optional Polars/Parquet/DuckDB route for the selected financial facts."""

import importlib
import json
import tempfile
from datetime import date
from fractions import Fraction
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

from .cashflow import AMOUNTS, BRIDGE, RATIOS, compare, serial_row
from .contracts import ContractError, canonical, digest, read_json

SOURCE_TYPES = {
    "symbol": "VARCHAR",
    "period": "VARCHAR",
    "start": "DATE",
    "end": "DATE",
    "as_of": "DATE",
    "metric": "VARCHAR",
    "value_usd": "BIGINT",
    "status": "VARCHAR",
    "filed": "DATE",
    "accession": "VARCHAR",
    "tag": "VARCHAR",
    "fact_id": "VARCHAR",
    "source_url": "VARCHAR",
}
MEMBERS = (
    "case.json",
    "request.json",
    "source_facts.jsonl",
    "source_facts.parquet",
    "cashflow.sql",
    "cashflow.parquet",
    "analysis.json",
    "quality.json",
)
METADATA = ("symbol", "period", "start", "end", "as_of", "days", "status")
QUALITY_SQL = {
    "unique_source_keys": """SELECT COUNT(*) FROM (
        SELECT symbol, period, start, "end", as_of, metric FROM source_facts
        GROUP BY ALL HAVING COUNT(*) <> 1)""",
    "four_inputs_per_period": """SELECT COUNT(*) FROM (
        SELECT symbol, period, start, "end", as_of FROM source_facts
        GROUP BY ALL HAVING COUNT(*) <> 4 OR COUNT(DISTINCT metric) <> 4)""",
    "known_metrics": """SELECT COUNT(*) FROM source_facts
        WHERE metric IS NULL OR metric NOT IN ('revenue', 'net_income', 'operating_cash_flow', 'capex')""",
    "filing_cutoff": "SELECT COUNT(*) FROM source_facts WHERE filed > as_of",
    "exact_periods": """SELECT COUNT(*) FROM source_facts
        WHERE start IS NULL OR "end" IS NULL OR as_of IS NULL OR start > "end"
        """,
    "explicit_missingness": """SELECT COUNT(*) FROM source_facts WHERE status IS NULL OR NOT (
        (status = 'selected' AND value_usd IS NOT NULL AND filed IS NOT NULL
            AND accession IS NOT NULL AND tag IS NOT NULL AND fact_id IS NOT NULL AND source_url IS NOT NULL)
        OR (status = 'missing_input' AND value_usd IS NULL AND filed IS NULL
            AND accession IS NULL AND tag IS NULL AND fact_id IS NULL AND source_url IS NULL))""",
    "capex_sign": "SELECT COUNT(*) FROM source_facts WHERE metric = 'capex' AND value_usd < 0",
}


def dependencies():
    try:
        return importlib.import_module("polars"), importlib.import_module("duckdb")
    except ImportError as exc:
        raise ContractError(
            'Warehouse commands require this checkout\'s extra: python -m pip install -e ".[warehouse]"'
        ) from exc


def source_rows(result):
    """Empty source metadata is NULL in the columnar schema, never a fake date."""
    return [
        {key: (None if value == "" and key not in ("symbol", "period") else value) for key, value in row.items()}
        for row in result["sources"]
    ]


def source_jsonl(rows):
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows).encode("utf-8")


def sql_text():
    return files("statementtrace").joinpath("data/warehouse_cashflow.sql").read_text(encoding="utf-8")


def quality(db):
    checks = {name: db.execute(query).fetchone()[0] for name, query in QUALITY_SQL.items()}
    failed = [name for name, count in checks.items() if count]
    if failed:
        raise ContractError("Warehouse source contracts failed: " + ", ".join(failed))
    return {"violations": checks, "source_rows": db.execute("SELECT COUNT(*) FROM source_facts").fetchone()[0]}


def records(db, query):
    cursor = db.execute(query)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def crosscheck_mart(expected, actual):
    """Check exact SQL amounts and rational pairs against the Python selector/math."""
    actual = sorted(actual, key=lambda row: (row["symbol"], row["start"]))
    if len(actual) != len(expected["rows"]):
        raise ContractError("Warehouse mart coverage differs")
    checked, saved = 0, []
    for left, raw in zip(expected["rows"], actual, strict=True):
        right = {name: value.isoformat() if isinstance(value, date) else value for name, value in raw.items()}
        for name in (*AMOUNTS, *BRIDGE):
            value = right[name]
            if value is not None and value != int(value):
                raise ContractError(f"Warehouse amount is not integral: {name}")
            right[name] = int(value) if value is not None else None
        for name in RATIOS:
            numerator, denominator = raw[name + "_numerator"], raw[name + "_denominator"]
            if (numerator is None) != (denominator is None) or denominator == 0:
                raise ContractError(f"Warehouse ratio pair is invalid: {name}")
            if any(value is not None and value != int(value) for value in (numerator, denominator)):
                raise ContractError(f"Warehouse ratio pair is not integral: {name}")
            right[name] = Fraction(int(numerator), int(denominator)) if numerator is not None else None
        for name in (*METADATA, *AMOUNTS, *RATIOS, *BRIDGE):
            if left[name] != right[name]:
                raise ContractError(f"Warehouse differs for {left['symbol']} / {left['period']} / {name}")
            checked += 1
        saved.append(serial_row({name: right[name] for name in (*METADATA, *AMOUNTS, *RATIOS, *BRIDGE)}))
    return {"rows": len(saved), "cells": checked}, saved


def _check_source_parquet(db, expected):
    columns = db.execute("DESCRIBE source_facts").fetchall()
    if {row[0]: row[1] for row in columns} != SOURCE_TYPES:
        raise ContractError("Warehouse source schema differs")
    actual = records(db, "SELECT * FROM source_facts ORDER BY symbol, start, metric")
    normalized = [
        {key: value.isoformat() if isinstance(value, date) else value for key, value in row.items()} for row in actual
    ]
    if normalized != source_rows(expected):
        raise ContractError("Warehouse selected source facts differ")


def _check_mart_schema(db):
    expected = {
        "symbol": "VARCHAR",
        "period": "VARCHAR",
        "start": "DATE",
        "end": "DATE",
        "as_of": "DATE",
        "days": "BIGINT",
        "status": "VARCHAR",
        **{name: "DECIMAL(38,0)" for name in (*AMOUNTS, *BRIDGE)},
        **{name + suffix: "DECIMAL(38,0)" for name in RATIOS for suffix in ("_numerator", "_denominator")},
    }
    if {row[0]: row[1] for row in db.execute("DESCRIBE cashflow").fetchall()} != expected:
        raise ContractError("Warehouse mart schema differs; exact DECIMAL amounts are required")


def write_warehouse(case, out, as_of=None):
    pl, duckdb = dependencies()
    try:
        return _write_warehouse(case, out, as_of, pl, duckdb)
    except (duckdb.Error, pl.exceptions.PolarsError) as exc:
        raise ContractError(f"Warehouse engine rejected the packet: {exc}") from exc


def _write_warehouse(case, out, as_of, pl, duckdb):
    result = compare(case, as_of)
    target = Path(out)
    if target.is_symlink() or (target.exists() and (not target.is_dir() or any(target.iterdir()))):
        raise ContractError("Warehouse output must be a new or empty directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Publish only after both engines agree. A failed build leaves no partial packet.
    with tempfile.TemporaryDirectory(prefix=".statementtrace-", dir=target.parent) as temp:
        stage = Path(temp) / "packet"
        stage.mkdir()
        (stage / "case.json").write_bytes(canonical(case))
        (stage / "request.json").write_bytes(canonical({"schema_version": 1, "as_of": result["as_of"]}))
        (stage / "source_facts.jsonl").write_bytes(source_jsonl(source_rows(result)))
        schema = {name: pl.Int64 if name == "value_usd" else pl.String for name in SOURCE_TYPES}
        (
            pl.scan_ndjson(stage / "source_facts.jsonl", schema=schema)
            .with_columns(pl.col("start", "end", "as_of", "filed").str.to_date("%Y-%m-%d", strict=True))
            .sort(["symbol", "start", "metric"])
            .sink_parquet(stage / "source_facts.parquet", compression="zstd")
        )
        query = sql_text()
        (stage / "cashflow.sql").write_text(query, encoding="utf-8", newline="\n")
        with duckdb.connect(":memory:", config={"threads": 2}) as db:
            db.read_parquet(str(stage / "source_facts.parquet")).create_view("source_facts")
            _check_source_parquet(db, result)
            checks = quality(db)
            db.execute("CREATE TABLE cashflow AS " + query)
            _check_mart_schema(db)
            parity, rows = crosscheck_mart(result, records(db, "SELECT * FROM cashflow"))
            db.execute("COPY cashflow TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(stage / "cashflow.parquet")])
        checks["python_duckdb"] = parity
        (stage / "quality.json").write_bytes(canonical(checks))
        (stage / "analysis.json").write_bytes(canonical({"as_of": result["as_of"], "rows": rows, "schema_version": 1}))
        manifest = {
            "schema_version": 1,
            "tools": {name: version(name) for name in ("statementtrace", "polars", "duckdb")},
            "sha256": {name: digest((stage / name).read_bytes()) for name in MEMBERS},
        }
        (stage / "manifest.json").write_bytes(canonical(manifest))
        verify_warehouse(stage)
        if target.exists():
            # rmdir rejects a destination that became nonempty while building.
            target.rmdir()
        stage.rename(target)
    return {
        "output": str(target),
        "as_of": result["as_of"],
        "source_rows": checks["source_rows"],
        "python_duckdb": parity,
    }


def verify_warehouse(directory):
    pl, duckdb = dependencies()
    try:
        return _verify_warehouse(directory, duckdb)
    except (duckdb.Error, pl.exceptions.PolarsError) as exc:
        raise ContractError(f"Warehouse engine rejected the packet: {exc}") from exc


def _verify_warehouse(directory, duckdb):
    target = Path(directory)
    if target.is_symlink() or not target.is_dir():
        raise ContractError("Warehouse must be a real directory")
    expected_files = {*MEMBERS, "manifest.json"}
    if {path.name for path in target.iterdir()} != expected_files:
        raise ContractError("Warehouse file set differs")
    for name in expected_files:
        path = target / name
        if path.is_symlink() or not path.is_file():
            raise ContractError(f"Warehouse member must be a real file: {name}")
    manifest = read_json((target / "manifest.json").read_bytes())
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or not isinstance(manifest.get("sha256"), dict)
        or set(manifest["sha256"]) != set(MEMBERS)
    ):
        raise ContractError("Warehouse manifest schema differs")
    for name in MEMBERS:
        if digest((target / name).read_bytes()) != manifest["sha256"][name]:
            raise ContractError(f"Warehouse hash differs: {name}")
    request = read_json((target / "request.json").read_bytes())
    if not isinstance(request, dict) or set(request) != {"schema_version", "as_of"} or request["schema_version"] != 1:
        raise ContractError("Warehouse request schema differs")
    result = compare(read_json((target / "case.json").read_bytes()), request["as_of"])
    if (target / "source_facts.jsonl").read_bytes() != source_jsonl(source_rows(result)):
        raise ContractError("Warehouse source replay differs")
    if (target / "cashflow.sql").read_bytes() != sql_text().encode("utf-8"):
        raise ContractError("Warehouse SQL differs")
    with duckdb.connect(":memory:", config={"threads": 2}) as db:
        db.read_parquet(str(target / "source_facts.parquet")).create_view("source_facts")
        _check_source_parquet(db, result)
        checks = quality(db)
        # Recompute from sources and separately inspect the saved mart.
        crosscheck_mart(result, records(db, sql_text()))
        db.read_parquet(str(target / "cashflow.parquet")).create_view("cashflow")
        _check_mart_schema(db)
        parity, rows = crosscheck_mart(result, records(db, "SELECT * FROM cashflow"))
    checks["python_duckdb"] = parity
    analysis = {"as_of": result["as_of"], "rows": rows, "schema_version": 1}
    for name, value in (("analysis.json", analysis), ("quality.json", checks)):
        if (target / name).read_bytes() != canonical(value):
            raise ContractError(f"Warehouse replay differs: {name}")
    return {"verified": True, "as_of": result["as_of"], "source_rows": checks["source_rows"], "python_duckdb": parity}
