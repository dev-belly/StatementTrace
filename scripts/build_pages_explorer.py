"""Stage the financial explorer with checked historical cutoffs for GitHub Pages."""

import argparse
from importlib.resources import files
from pathlib import Path

from statementtrace.cashflow import AMOUNTS, compare, demo_case, sql_crosscheck
from statementtrace.contracts import canonical, digest


def snapshot_view(case, cutoff):
    result = compare(case, cutoff)
    sql_crosscheck(result)
    periods = {}
    cashflow = []
    for row in result["rows"]:
        periods.setdefault(row["symbol"], []).append(row["period"])
        cashflow.append(
            {
                **{key: row[key] for key in ("symbol", "period", "start", "end", "status")},
                "amounts": {key: str(row[key]) if row[key] is not None else None for key in AMOUNTS},
            }
        )
    facts = [
        {
            **fact,
            "value_usd": str(fact["value_usd"]) if fact["value_usd"] is not None else None,
            "filed": fact["filed"] or None,
        }
        for fact in result["sources"]
    ]
    payload = {"cashflow": cashflow, "facts": facts}
    return {
        "snapshot": {"as_of": cutoff, "snapshot_id": digest(canonical({"as_of": cutoff, **payload}))},
        "issuers": [{"symbol": symbol, "periods": years} for symbol, years in periods.items()],
        **payload,
    }


def build(destination: Path) -> None:
    case = demo_case()
    views = [snapshot_view(case, cutoff) for cutoff in (case["as_of"], "2025-02-04")]
    assets = files("statementtrace").joinpath("data", "explorer")
    destination.mkdir(parents=True, exist_ok=False)
    index = assets.joinpath("index.html").read_text(encoding="utf-8")
    (destination / "index.html").write_text(index.replace('data-mode="api"', 'data-mode="snapshot"'), encoding="utf-8")
    for name in ("explorer.css", "explorer.js"):
        (destination / name).write_bytes(assets.joinpath(name).read_bytes())
    (destination / "snapshots.json").write_bytes(canonical({"schema_version": 1, "views": views}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    build(parser.parse_args().destination)
