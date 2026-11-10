"""A small, source-linked cross-issuer cash-flow research packet."""

import csv
import html
import io
import math
import re
import sqlite3
from fractions import Fraction
from importlib.resources import files
from pathlib import Path

from .contracts import ContractError, canonical, display, exact, iso_date, read_json
from .engine import analyze
from .report import csv_label

INPUTS = ("revenue", "net_income", "operating_cash_flow", "capex")
AMOUNTS = (*INPUTS, "free_cash_flow", "cfo_minus_profit")
RATIOS = ("net_margin", "fcf_margin", "cash_conversion", "capex_cfo", "net_income_growth", "fcf_growth")
BRIDGE = ("delta_cfo", "negative_delta_capex", "delta_fcf", "bridge_residual")


def demo_case():
    return read_json(files("statementtrace").joinpath("data/cashflow_case.json").read_bytes())


def divide(numerator, denominator):
    return Fraction(numerator, denominator) if numerator is not None and denominator not in (None, 0) else None


def difference(left, right):
    return left - right if left is not None and right is not None else None


def compare(case, as_of=None):
    """Use the existing date/period selector; keep amounts integral and ratios exact."""
    if not isinstance(case, dict) or case.get("schema_version") != 1:
        raise ContractError("Unsupported cash-flow case schema")
    cutoff = as_of if as_of is not None else case.get("as_of")
    iso_date(cutoff, "as_of")
    companies = case.get("companies")
    if not isinstance(companies, list) or not companies:
        raise ContractError("Cash-flow case requires companies")
    seen, rows, source_rows = set(), [], []
    for company in companies:
        symbol = company.get("symbol")
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol) or symbol in seen:
            raise ContractError("Company symbols must be unique, short uppercase identifiers")
        seen.add(symbol)
        analysis = analyze(company["facts"], {"periods": company["periods"], "as_of_dates": [cutoff]})
        previous = None
        for panel in analysis["panels"]:
            period = panel["period"]
            row = {
                "symbol": symbol,
                "entity": analysis["entity"],
                "period": period["label"],
                "start": period["start"],
                "end": period["end"],
                "days": panel["duration_days"],
                "as_of": cutoff,
            }
            for name in INPUTS:
                fact = panel["facts"][name]
                value = fact["record"]["val"] if fact else None
                if value is not None and not -(2**63) <= value < 2**63:
                    raise ContractError("Cash-flow SQL comparison requires signed 64-bit USD amounts")
                if name == "capex" and value is not None and value < 0:
                    raise ContractError("capex must be a positive cash-outflow magnitude")
                row[name] = value
                record = fact["record"] if fact else {}
                source_rows.append(
                    {
                        "symbol": symbol,
                        "period": period["label"],
                        "start": period["start"],
                        "end": period["end"],
                        "as_of": cutoff,
                        "metric": name,
                        "value_usd": value,
                        "status": "selected" if fact else "missing_input",
                        "filed": record.get("filed", ""),
                        "accession": record.get("accn", ""),
                        "tag": fact["tag"] if fact else "",
                        "fact_id": fact["fact_id"] if fact else "",
                        "source_url": fact["source_url"] if fact else "",
                    }
                )
            row["status"] = "ok" if all(row[name] is not None for name in INPUTS) else "missing_input"
            row["free_cash_flow"] = difference(row["operating_cash_flow"], row["capex"])
            row["cfo_minus_profit"] = difference(row["operating_cash_flow"], row["net_income"])
            row["net_margin"] = divide(row["net_income"], row["revenue"])
            row["fcf_margin"] = divide(row["free_cash_flow"], row["revenue"])
            row["cash_conversion"] = divide(row["operating_cash_flow"], row["net_income"])
            row["capex_cfo"] = divide(row["capex"], row["operating_cash_flow"])
            adjacent = previous and (iso_date(row["start"], "start") - iso_date(previous["end"], "end")).days == 1
            for metric, amount in (("net_income_growth", "net_income"), ("fcf_growth", "free_cash_flow")):
                base = previous[amount] if adjacent else None
                row[metric] = divide(difference(row[amount], base), base)
            row["delta_cfo"] = (
                difference(row["operating_cash_flow"], previous["operating_cash_flow"]) if adjacent else None
            )
            row["negative_delta_capex"] = difference(previous["capex"], row["capex"]) if adjacent else None
            row["delta_fcf"] = difference(row["free_cash_flow"], previous["free_cash_flow"]) if adjacent else None
            row["bridge_residual"] = (
                row["delta_fcf"] - row["delta_cfo"] - row["negative_delta_capex"]
                if all(row[key] is not None for key in BRIDGE[:3])
                else None
            )
            rows.append(row)
            previous = row
    rows.sort(key=lambda row: (row["symbol"], row["start"]))
    source_rows.sort(key=lambda row: (row["symbol"], row["start"], row["metric"]))
    return {"as_of": cutoff, "rows": rows, "sources": source_rows}


def sql_crosscheck(result):
    """Recompute arithmetic from selected source facts, not from Python's ratios."""
    query = files("statementtrace").joinpath("data/cashflow_compare.sql").read_text(encoding="utf-8")
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE facts(symbol TEXT, period TEXT, start TEXT, end TEXT, metric TEXT, value_usd INTEGER)")
        db.executemany(
            "INSERT INTO facts VALUES(:symbol, :period, :start, :end, :metric, :value_usd)", result["sources"]
        )
        sql_rows = list(db.execute(query))
    if len(sql_rows) != len(result["rows"]):
        raise ContractError("SQL comparison coverage differs")
    cells = 0
    for expected, actual in zip(result["rows"], sql_rows, strict=True):
        for name in ("symbol", "period", *AMOUNTS, *RATIOS, *BRIDGE):
            left, right = expected[name], actual[name]
            matches = (
                right is not None and math.isclose(float(left), right, rel_tol=1e-12, abs_tol=1e-12)
                if isinstance(left, Fraction)
                else left == right
            )
            if not matches:
                raise ContractError(f"SQL differs for {expected['symbol']} / {expected['period']} / {name}")
            cells += 1
    return {"rows": len(sql_rows), "cells": cells}


def csv_bytes(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: csv_label(value) if isinstance(value, str) else value
                for key in fields
                for value in [row.get(key, "")]
            }
        )
    return stream.getvalue().encode("utf-8")


def serial_row(row):
    return {key: exact(value) if isinstance(value, Fraction) else value for key, value in row.items()}


def render(result):
    e = html.escape

    def amount(value):
        return "unavailable" if value is None else f"{value / 1_000_000_000:,.3f}"

    def percent(value):
        return "unavailable" if value is None else display(value * 100, 2) + "%"

    def table(headers, rows):
        return (
            "<div class='table-wrap'><table><thead><tr>"
            + "".join(f"<th scope='col'>{e(label)}</th>" for label in headers)
            + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td>{e(str(cell))}</td>" for cell in row) + "</tr>" for row in rows)
            + "</tbody></table></div>"
        )

    latest = [
        row
        for i, row in enumerate(result["rows"])
        if i == len(result["rows"]) - 1 or row["symbol"] != result["rows"][i + 1]["symbol"]
    ]
    overview = table(
        ["FY2024", "Profit growth", "FCF growth", "FCF margin", "Cash capex / CFO"],
        [
            [
                row["symbol"],
                *[percent(row[key]) for key in ("net_income_growth", "fcf_growth", "fcf_margin", "capex_cfo")],
            ]
            for row in latest
        ],
    )
    bridges = []
    for row in latest:
        baseline = next((r for r in result["rows"] if r["symbol"] == row["symbol"] and r is not row), None)
        if baseline and row["delta_fcf"] is not None:
            scale = max(abs(row["delta_cfo"]), abs(row["negative_delta_capex"]), abs(row["delta_fcf"]), 1)
            bars = []
            for label, key in [
                ("Operating cash-flow change", "delta_cfo"),
                ("Cash-capex effect", "negative_delta_capex"),
                ("Free cash-flow change", "delta_fcf"),
            ]:
                value = row[key]
                width = abs(value) / scale * 100
                bar_class = "bar negative" if value < 0 else "bar"
                bars.append(
                    f"<div class='bar-row'><span>{label}</span><div class='track'>"
                    f"<div class='{bar_class}' style='width:{width:.3f}%'></div></div>"
                    f"<b>{amount(value)}</b></div>"
                )
            bridges.append(
                f"<article><div class='eyebrow'>{e(row['symbol'])} · FY2023 → FY2024</div>"
                f"<h3>{amount(baseline['free_cash_flow'])} → {amount(row['free_cash_flow'])}"
                f"<small> USD bn FCF</small></h3>{''.join(bars)}"
                "<p class='muted'>ΔFCF = ΔCFO − Δcash capex. Reconciliation residual: "
                f"{amount(row['bridge_residual'])}.</p></article>"
            )
    details = table(
        ["Issuer / FY", "Fiscal window", "Days", "Revenue", "Net income", "CFO", "Cash capex", "FCF"],
        [
            [
                f"{row['symbol']} / {row['period']}",
                f"{row['start']} → {row['end']}",
                row["days"],
                *[
                    amount(row[key])
                    for key in ("revenue", "net_income", "operating_cash_flow", "capex", "free_cash_flow")
                ],
            ]
            for row in result["rows"]
        ],
    )
    sources = sorted(
        {(row["symbol"], row["filed"], row["source_url"]) for row in result["sources"] if row["source_url"]}
    )
    source_links = "".join(
        f"<li><a href='{e(url, quote=True)}'>{e(symbol)} · SEC filing {e(filed)}</a></li>"
        for symbol, filed, url in sources
    )
    template = files("statementtrace").joinpath("data/cashflow_report.html").read_text(encoding="utf-8")
    replacements = {
        "@@AS_OF@@": e(result["as_of"]),
        "@@OVERVIEW@@": overview,
        "@@BRIDGES@@": "".join(bridges) or "<p>No adjacent, available periods at this cutoff.</p>",
        "@@DETAILS@@": details,
        "@@SOURCES@@": source_links,
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template.encode("utf-8")


def build(case, as_of=None):
    result = compare(case, as_of)
    checks = sql_crosscheck(result)
    serialized = [serial_row(row) for row in result["rows"]]
    fields = ("symbol", "entity", "period", "start", "end", "days", "as_of", "status", *AMOUNTS, *RATIOS, *BRIDGE)
    return {
        "case.json": canonical(case),
        "analysis.json": canonical(
            {"schema_version": 1, "as_of": result["as_of"], "sql_crosscheck": checks, "rows": serialized}
        ),
        "comparison.csv": csv_bytes(serialized, fields),
        "source_facts.csv": csv_bytes(result["sources"], tuple(result["sources"][0])),
        "comparison.sql": files("statementtrace").joinpath("data/cashflow_compare.sql").read_bytes(),
        "index.html": render(result),
    }


def write_comparison(case, out, as_of=None):
    packet = build(case, as_of)
    target = Path(out)
    if target.is_symlink() or (target.exists() and (not target.is_dir() or any(target.iterdir()))):
        raise ContractError("Comparison output must be a new or empty directory")
    target.mkdir(parents=True, exist_ok=True)
    for name, content in packet.items():
        (target / name).write_bytes(content)
    result = read_json(packet["analysis.json"])
    return {
        "output": str(target),
        "as_of": result["as_of"],
        "issuer_years": len(result["rows"]),
        "sql_crosscheck": result["sql_crosscheck"],
    }


def verify_comparison(directory):
    target = Path(directory)
    if target.is_symlink() or not target.is_dir():
        raise ContractError("Comparison must be a real directory")
    case = read_json((target / "case.json").read_bytes())
    saved = read_json((target / "analysis.json").read_bytes())
    expected = build(case, saved["as_of"])
    if {path.name for path in target.iterdir()} != set(expected):
        raise ContractError("Comparison file set differs")
    for name, raw in expected.items():
        path = target / name
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            raise ContractError(f"Comparison replay differs: {name}")
    return {"verified": True, "issuer_years": len(saved["rows"]), "as_of": saved["as_of"]}
