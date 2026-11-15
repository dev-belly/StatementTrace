"""Source-linked net-income to CFO bridges; supplemental cash flows stay separate."""

import base64
import hashlib
import html
import re
import sqlite3
from decimal import Decimal
from importlib.resources import files
from pathlib import Path

from .cashflow import REPORT_LANGUAGES, compare, csv_bytes, demo_case, difference
from .contracts import ContractError, canonical, iso_date, read_json

SUPPLEMENTAL = (
    "tax_expense",
    "cash_taxes",
    "acquisition_line",
    "finance_lease_additions",
    "finance_lease_principal",
    "finance_lease_interest",
    "combined_lease_additions",
)
AMOUNTS = (
    "net_income",
    "adjustments",
    "operating_changes",
    "calculated_cfo",
    "operating_cash_flow",
    "reconciliation_residual",
    "capex",
    "free_cash_flow",
    *SUPPLEMENTAL,
    "fcf_less_acquisition_line",
    "fcf_less_lease_principal",
    "delta_net_income",
    "delta_adjustments",
    "delta_operating_changes",
    "delta_cfo",
    "delta_residual",
)
SOURCE_FIELDS = (
    "symbol",
    "period",
    "start",
    "end",
    "as_of",
    "category",
    "line_id",
    "label",
    "zh",
    "value_usd",
    "precision_usd",
    "status",
    "filed",
    "accession",
    "source_url",
    "section",
    "fact_id",
)


def demo_bridge_case():
    detail = read_json(files("statementtrace").joinpath("data/profit_bridge_case.json").read_bytes())
    return {"schema_version": 1, "anchor_case": demo_case(), "detail_case": detail}


def text(value, name):
    if not isinstance(value, str) or not value.strip() or re.search(r"[\x00-\x1f\x7f]", value):
        raise ContractError(f"Bridge {name} must be nonempty single-line text")
    return value


def total(values):
    return sum(values) if all(value is not None for value in values) else None


def analyze_bridge(case, as_of=None):
    if not isinstance(case, dict) or type(case.get("schema_version")) is not int or case["schema_version"] != 1:
        raise ContractError("Unsupported profit-bridge schema")
    anchor_case, detail_case = case.get("anchor_case"), case.get("detail_case")
    if (
        not isinstance(anchor_case, dict)
        or not isinstance(detail_case, dict)
        or type(detail_case.get("schema_version")) is not int
        or detail_case["schema_version"] != 1
    ):
        raise ContractError("Bridge requires anchor_case and detail_case")
    anchors = compare(anchor_case, as_of)
    cutoff = anchors["as_of"]
    companies = detail_case.get("companies")
    if not isinstance(companies, list) or not companies:
        raise ContractError("Bridge requires detail companies")
    anchor_rows = {(row["symbol"], row["period"]): row for row in anchors["rows"]}
    anchor_sources = {(r["symbol"], r["period"], r["metric"]): r for r in anchors["sources"]}
    seen, rows, sources = set(), [], []
    for company in companies:
        if not isinstance(company, dict):
            raise ContractError("Bridge company must be an object")
        symbol = company.get("symbol")
        if not isinstance(symbol, str) or symbol in seen or symbol not in {key[0] for key in anchor_rows}:
            raise ContractError("Bridge company coverage must match unique anchor companies")
        seen.add(symbol)
        filed, accession = company.get("filed"), company.get("accession")
        iso_date(filed, "bridge filed")
        if not isinstance(accession, str) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
            raise ContractError("Bridge accession must identify the source filing")
        url = company.get("source_url")
        if not isinstance(url, str) or not re.fullmatch(
            r"https://www\.sec\.gov/Archives/edgar/data/\d+/" + accession.replace("-", "") + r"/[\w.-]+\.htm",
            url,
        ):
            raise ContractError("Bridge source URL must match the SEC accession")
        text(company.get("operating_section"), "operating section")
        lines, supplemental = company.get("lines"), company.get("supplemental")
        if not isinstance(lines, list) or not lines or not isinstance(supplemental, list):
            raise ContractError("Bridge requires operating and supplemental line lists")
        periods = {period for issuer, period in anchor_rows if issuer == symbol}
        if any(not isinstance(period, str) or not re.fullmatch(r"\d{4}", period) for period in periods):
            raise ContractError("Bridge supports four-digit fiscal-year labels")
        ids, supplement_ids, groups = set(), set(), set()
        for category, entries in ((None, lines), ("supplemental", supplemental)):
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ContractError("Bridge line must be an object")
                line_id = entry.get("id")
                if not isinstance(line_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", line_id) or line_id in ids:
                    raise ContractError("Bridge line IDs must be unique identifiers")
                ids.add(line_id)
                group = category or entry.get("group")
                if group not in {"adjustments", "operating_changes", "supplemental"}:
                    raise ContractError("Unknown operating bridge group")
                if group == "supplemental":
                    supplement_ids.add(line_id)
                    text(entry.get("section"), "supplemental section")
                else:
                    groups.add(group)
                text(entry.get("label"), "source label")
                text(entry.get("zh"), "Chinese label")
                values = entry.get("values_millions")
                precision = entry.get("precision_millions", 1)
                if type(precision) is not int or precision not in {1, 100}:
                    raise ContractError("Bridge precision must preserve millions or rounded 0.1 billions")
                if not isinstance(values, dict) or set(values) != periods:
                    raise ContractError("Bridge line must explicitly cover every anchor period")
                for value in values.values():
                    if value is not None and (
                        type(value) is not int
                        or not -(2**63) < value * 1_000_000 < 2**63
                        or value % precision
                        or (group == "supplemental" and value < 0)
                    ):
                        raise ContractError("Bridge amounts must be signed integer millions at reported precision")
        required = set(SUPPLEMENTAL) - {"combined_lease_additions"}
        if groups != {"adjustments", "operating_changes"} or not required <= supplement_ids <= set(SUPPLEMENTAL):
            raise ContractError("Bridge group or supplemental coverage differs")
        previous = None
        for anchor in sorted((r for r in anchor_rows.values() if r["symbol"] == symbol), key=lambda r: r["start"]):
            period = anchor["period"]
            if filed <= anchor["end"]:
                raise ContractError("Bridge filing must follow the fiscal period")
            visible = filed <= cutoff
            row = {key: anchor[key] for key in ("symbol", "period", "start", "end", "as_of")}
            row.update(dict.fromkeys(SUPPLEMENTAL))
            for metric in ("net_income", "operating_cash_flow", "capex"):
                fact = anchor_sources[(symbol, period, metric)]
                if visible and (fact["accession"] != accession or fact["filed"] != filed):
                    raise ContractError("Bridge and anchor selected filing identities differ")
                row[metric] = anchor[metric]
                sources.append(
                    {
                        **{key: row[key] for key in ("symbol", "period", "start", "end", "as_of")},
                        "category": "anchor",
                        "line_id": metric,
                        "label": metric,
                        "zh": metric,
                        "value_usd": anchor[metric],
                        "precision_usd": 1_000_000,
                        "status": fact["status"],
                        "filed": fact["filed"],
                        "accession": fact["accession"],
                        "source_url": fact["source_url"],
                        "section": "Selected original cash-flow study anchor",
                        "fact_id": fact["fact_id"],
                    }
                )
            selected = {"adjustments": [], "operating_changes": []}
            for category, entries in ((None, lines), ("supplemental", supplemental)):
                for entry in entries:
                    group = category or entry["group"]
                    raw = entry["values_millions"][period]
                    value = raw * 1_000_000 if visible and raw is not None else None
                    status = (
                        "not_available_at_cutoff" if not visible else "not_extracted" if raw is None else "selected"
                    )
                    source = {
                        **{key: row[key] for key in ("symbol", "period", "start", "end", "as_of")},
                        "category": group,
                        "line_id": entry["id"],
                        "label": entry["label"],
                        "zh": entry["zh"],
                        "value_usd": value,
                        "precision_usd": entry.get("precision_millions", 1) * 1_000_000,
                        "status": status,
                        "filed": filed,
                        "accession": accession,
                        "source_url": url,
                        "section": entry["section"] if category else company["operating_section"],
                    }
                    identity = {key: val for key, val in source.items() if key != "as_of"}
                    source["fact_id"] = hashlib.sha256(canonical(identity)).hexdigest() if value is not None else ""
                    sources.append(source)
                    if group == "supplemental":
                        row[entry["id"]] = value
                    else:
                        selected[group].append(value)
            row["adjustments"], row["operating_changes"] = (total(selected[key]) for key in selected)
            known = [row["net_income"], *selected["adjustments"], *selected["operating_changes"]]
            if sum(abs(value) for value in known if value is not None) >= 2**63:
                raise ContractError("Bridge aggregate exceeds exact SQLite integer range")
            row["calculated_cfo"] = total([row["net_income"], row["adjustments"], row["operating_changes"]])
            row["reconciliation_residual"] = difference(row["operating_cash_flow"], row["calculated_cfo"])
            if row["reconciliation_residual"] not in (None, 0):
                raise ContractError(f"CFO bridge does not reconcile: {symbol} / {period}")
            row["status"] = "ok" if row["reconciliation_residual"] == 0 else "missing_input"
            row["free_cash_flow"] = difference(row["operating_cash_flow"], row["capex"])
            row["fcf_less_acquisition_line"] = difference(row["free_cash_flow"], row["acquisition_line"])
            row["fcf_less_lease_principal"] = difference(row["free_cash_flow"], row["finance_lease_principal"])
            adjacent = previous and (iso_date(row["start"], "start") - iso_date(previous["end"], "end")).days == 1
            for name in ("net_income", "adjustments", "operating_changes", "operating_cash_flow"):
                key = "delta_cfo" if name == "operating_cash_flow" else "delta_" + name
                row[key] = difference(row[name], previous[name]) if adjacent else None
            row["delta_residual"] = difference(
                row["delta_cfo"],
                total([row["delta_net_income"], row["delta_adjustments"], row["delta_operating_changes"]]),
            )
            if any(value is not None and not -(2**63) < value < 2**63 for value in (row[key] for key in AMOUNTS)):
                raise ContractError("Bridge output exceeds exact SQLite integer range")
            rows.append(row)
            previous = row
    if seen != {key[0] for key in anchor_rows}:
        raise ContractError("Bridge detail company coverage differs from anchors")
    rows.sort(key=lambda r: (r["symbol"], r["start"]))
    sources.sort(key=lambda r: (r["symbol"], r["start"], r["category"], r["line_id"]))
    return {"as_of": cutoff, "rows": rows, "sources": sources}


def crosscheck_bridge(result):
    query = files("statementtrace").joinpath("data/profit_bridge.sql").read_text(encoding="utf-8")
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE facts(symbol, period, start, end, category, line_id, value_usd INTEGER)")
        db.executemany(
            "INSERT INTO facts VALUES(:symbol,:period,:start,:end,:category,:line_id,:value_usd)", result["sources"]
        )
        actual = list(db.execute(query))
    if len(actual) != len(result["rows"]):
        raise ContractError("Bridge SQL coverage differs")
    cells = 0
    for left, right in zip(result["rows"], actual, strict=True):
        for key in ("symbol", "period", *AMOUNTS):
            if left[key] != right[key]:
                raise ContractError(f"Bridge SQL differs: {left['symbol']} / {left['period']} / {key}")
            cells += 1
    return {"rows": len(actual), "cells": cells}


def render_bridge(result, downloads, language):
    zh = language == "zh-CN"
    e = html.escape

    def label(chinese, english):
        return chinese if zh else english

    def amount(value, rounded=False):
        if value is None:
            return label("不可得 / 未单列", "Unavailable / not isolated")
        number = Decimal(value).scaleb(-9)
        return f"≈{number:,.1f}" if rounded else f"{number:,.3f}"

    def table(headers, values):
        return (
            '<div class="table-wrap"><table><thead><tr>'
            + "".join(f'<th scope="col">{e(header)}</th>' for header in headers)
            + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td>{e(str(cell))}</td>" for cell in row) + "</tr>" for row in values)
            + "</tbody></table></div>"
        )

    name = label("公司 / 财年", "Issuer / FY")
    summary = table(
        [
            name,
            label("净利润", "Net income"),
            label("非现金及其他调节", "Adjustments"),
            label("经营资产负债变动", "Operating changes"),
            "CFO",
            label("勾稽差额", "Residual"),
        ],
        [
            [
                f"{r['symbol']} / {r['period']}",
                *[
                    amount(r[k])
                    for k in (
                        "net_income",
                        "adjustments",
                        "operating_changes",
                        "operating_cash_flow",
                        "reconciliation_residual",
                    )
                ],
            ]
            for r in result["rows"]
        ],
    )
    changes = table(
        [
            name,
            label("净利润增量", "Net-income change"),
            label("调节项增量", "Adjustment change"),
            label("经营资产负债变动的增量", "Operating-change difference"),
            label("CFO 增量", "CFO change"),
            label("差额", "Residual"),
        ],
        [
            [
                f"{r['symbol']} / {r['period']}",
                *[
                    amount(r[k])
                    for k in (
                        "delta_net_income",
                        "delta_adjustments",
                        "delta_operating_changes",
                        "delta_cfo",
                        "delta_residual",
                    )
                ],
            ]
            for r in result["rows"]
            if r["period"] != min(s["period"] for s in result["rows"] if s["symbol"] == r["symbol"])
        ],
    )
    tax_rows, capital_rows, deduction_rows = [], [], []
    for row in result["rows"]:
        source_map = {
            s["line_id"]: s for s in result["sources"] if (s["symbol"], s["period"]) == (row["symbol"], row["period"])
        }
        tax_rows.append(
            [
                f"{row['symbol']} / {row['period']}",
                amount(row["tax_expense"]),
                amount(row["cash_taxes"], source_map["cash_taxes"]["precision_usd"] > 1_000_000),
            ]
        )
        capital_rows.append(
            [
                f"{row['symbol']} / {row['period']}",
                *[
                    amount(row[k])
                    for k in (
                        "capex",
                        "free_cash_flow",
                        "acquisition_line",
                        "finance_lease_additions",
                        "finance_lease_principal",
                    )
                ],
            ]
        )
        deduction_rows.append(
            [
                f"{row['symbol']} / {row['period']}",
                amount(row["fcf_less_acquisition_line"]),
                amount(row["fcf_less_lease_principal"]),
            ]
        )
    taxes = table(
        [
            name,
            label("所得税费用", "Income-tax expense"),
            label("所得税净现金支付（已在 CFO 内）", "Cash taxes (already in CFO)"),
        ],
        tax_rows,
    )
    capital = table(
        [
            name,
            label("现金 capex", "Cash capex"),
            "FCF",
            label("收购等现金支出", "Acquisition-related line"),
            label("非现金融资租赁增加", "Noncash finance-lease additions"),
            label("租赁本金现金支付", "Lease principal cash"),
        ],
        capital_rows,
    )
    capital += table(
        [
            name,
            label("FCF 减收购等支出（单独情景）", "FCF less acquisition line (separate)"),
            label("FCF 减租赁本金（单独情景）", "FCF less lease principal (separate)"),
        ],
        deduction_rows,
    )
    details = []
    for symbol in sorted({r["symbol"] for r in result["rows"]}):
        selected = [
            s
            for s in result["sources"]
            if s["symbol"] == symbol and s["category"] in {"adjustments", "operating_changes"}
        ]
        periods = sorted({s["period"] for s in selected})
        line_ids = sorted({s["line_id"] for s in selected})
        values = []
        for line_id in line_ids:
            points = [
                next(s for s in selected if s["period"] == period and s["line_id"] == line_id) for period in periods
            ]
            values.append([points[0]["zh"] if zh else points[0]["label"], *[amount(s["value_usd"]) for s in points]])
        details.append(
            f"<details><summary>{e(symbol)} · {label('逐项检查', 'Inspect each line')}</summary>"
            + table([label("现金流调节行", "Cash-flow line"), *periods], values)
            + "</details>"
        )
    source_links = "".join(
        f'<li><a href="{e(url, quote=True)}">{e(symbol)} · 10-K · {e(filed)}</a></li>'
        for symbol, filed, url in sorted(
            {
                (s["symbol"], s["filed"], s["source_url"])
                for s in result["sources"]
                if s["category"] != "anchor" and s["status"] == "selected"
            }
        )
    )
    download_links = "".join(
        f'<a download="{e(filename, quote=True)}" href="data:application/octet-stream;base64,'
        f'{base64.b64encode(raw).decode("ascii")}">{e(filename)}</a>'
        for filename, raw in downloads.items()
    )
    template = files("statementtrace").joinpath("data/profit_bridge_report.html").read_text(encoding="utf-8")
    replacements = {
        "@@LANG@@": language,
        "@@NAV_RESEARCH@@": label("StatementTrace / 财报研究", "StatementTrace / Research"),
        "@@NAV_OVERVIEW@@": label("回到自由现金流总览", "FCF overview"),
        "@@CUTOFF_LABEL@@": label("申报日截止", "FILED-DATE CUTOFF"),
        "@@FOOTER_NOTES@@": label("研究解读与复现", "Research notes and replay"),
        "@@OFFLINE@@": label(
            "UTF-8 · 可离线下载 · 无需 JavaScript · Python 3.11+",
            "UTF-8 · Offline downloads · No JavaScript · Python 3.11+",
        ),
        "@@TITLE@@": label("利润到现金，中间发生了什么？", "What turns profit into operating cash?"),
        "@@LEAD@@": label(
            "沿三份年报，拆开净利润、非现金调节与经营资产负债变动，再检查税款、收购和租赁的现金边界。",
            "Trace net income, adjustments and operating balance changes through three filings, "
            "then inspect tax, acquisition and lease boundaries.",
        ),
        "@@CUTOFF@@": e(result["as_of"]),
        "@@SCOPE@@": label(
            "金额单位：十亿美元。三家公司财年不同；Apple FY2023 含 53 周。"
            "使用各自同比，不作同期排名。缺失与零分开保留。",
            "Amounts: USD billions. Fiscal windows differ; Apple FY2023 has 53 weeks. "
            "Compare each issuer over time. Missing is not zero.",
        ),
        "@@SUMMARY_TITLE@@": label("01 / 从净利润走到经营现金流", "01 / Reconcile profit to operating cash"),
        "@@SUMMARY_NOTE@@": label(
            "CFO = 净利润 + 非现金及其他调节 + 经营资产负债变动。"
            "最后一组包含长期项目，不等同于狭义营运资本。股份支付加回也不代表没有股权成本。",
            "CFO = net income + adjustments + operating asset/liability changes. "
            "The last group includes long-term items. Adding back stock compensation does not remove its equity cost.",
        ),
        "@@CHANGES_TITLE@@": label("02 / CFO 增长由谁贡献？", "02 / What explains the CFO change?"),
        "@@TAX_TITLE@@": label("03 / 税费不等于当年现金支付", "03 / Tax expense differs from cash paid"),
        "@@TAX_NOTE@@": label(
            "所得税净现金支付已体现在 CFO，不能再次扣除。≈ 表示来源只披露至 1 亿美元，CSV 保留披露精度。"
            "所得税费用与现金支付之差不能单独解释全部经营现金流变化。",
            "Cash taxes are already reflected in CFO; do not subtract them again. "
            "≈ marks disclosures rounded to USD 0.1bn; CSV preserves precision. "
            "The expense/payment gap alone does not explain CFO.",
        ),
        "@@CAPITAL_TITLE@@": label(
            "04 / 把现金支出与非现金投入分开", "04 / Separate cash spending from noncash additions"
        ),
        "@@CAPITAL_NOTE@@": label(
            "FCF 仍定义为 CFO 减现金 capex。新增融资租赁资产是非现金投入，不能当作当期现金支出；"
            "租赁利息已经在 CFO 内。两个扣减情景各自从原始 FCF 出发，仅用于说明口径，"
            "不是公司披露的标准 FCF。收购行包含无形资产等项目，不是纯收购金额。",
            "FCF remains CFO less cash capex. Finance-lease asset additions are noncash; interest is already in CFO. "
            "Each illustrative deduction starts from original FCF; neither is issuer-defined FCF. "
            "Acquisition lines also include intangible/other assets.",
        ),
        "@@MISSING_NOTE@@": label(
            "Apple 的选中摘录未分离融资租赁增加、本金、利息和纯收购支出，因此保留缺失；"
            "不能把其投资现金流的 Other 全部当作收购。来源包另存租赁使用权资产合并增加额，"
            "它不等同于融资租赁增加额。",
            "The selected Apple excerpt does not isolate finance-lease additions, principal, interest or acquisitions; "
            "retain missing values. Its investing Other line is not pure acquisitions. "
            "Combined ROU additions are saved separately, not treated as finance-only additions.",
        ),
        "@@EVIDENCE_TITLE@@": label("05 / 逐项查来源，下载后重算", "05 / Inspect sources and replay"),
        "@@METHOD_NOTE@@": label(
            "年报比较列由人工整理；仍采用原研究的申报日截止规则。"
            "Python 与 SQLite 从选中行分别重算六个年度及同比桥。"
            "算术一致性不能独立认证抄录和分类，也不能识别一份被整体一致替换的来源包。",
            "Comparative filing columns are manually curated under the original filed-date cutoff. "
            "Python and SQLite separately recompute selected rows and year-over-year bridges. "
            "Arithmetic agreement does not independently certify transcription/classification "
            "or detect a coherently replaced source packet.",
        ),
        "@@SUMMARY@@": summary,
        "@@CHANGES@@": changes,
        "@@TAXES@@": taxes,
        "@@CAPITAL@@": capital,
        "@@DETAILS@@": "".join(details),
        "@@SOURCES@@": source_links,
        "@@DOWNLOADS@@": download_links,
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template.encode("utf-8")


def build_bridge(case, as_of=None, language="zh-CN"):
    if language not in REPORT_LANGUAGES:
        raise ContractError("Report language must be en or zh-CN")
    result = analyze_bridge(case, as_of)
    checks = crosscheck_bridge(result)
    analysis = {
        "schema_version": 1,
        "language": language,
        "as_of": result["as_of"],
        "sql_crosscheck": checks,
        "rows": result["rows"],
    }
    packet = {
        "case.json": canonical(case),
        "analysis.json": canonical(analysis),
        "bridge.csv": csv_bytes(result["rows"], ("symbol", "period", "start", "end", "as_of", "status", *AMOUNTS)),
        "sources.csv": csv_bytes(result["sources"], SOURCE_FIELDS),
        "bridge.sql": files("statementtrace").joinpath("data/profit_bridge.sql").read_bytes(),
    }
    packet["index.html"] = render_bridge(result, packet, language)
    return packet


def write_bridge(case, out, as_of=None, language="zh-CN"):
    packet = build_bridge(case, as_of, language)
    target = Path(out)
    if target.is_symlink() or (target.exists() and (not target.is_dir() or any(target.iterdir()))):
        raise ContractError("Bridge output must be a new or empty directory")
    target.mkdir(parents=True, exist_ok=True)
    for name, raw in packet.items():
        (target / name).write_bytes(raw)
    analysis = read_json(packet["analysis.json"])
    return {
        "output": str(target),
        "as_of": analysis["as_of"],
        "issuer_years": len(analysis["rows"]),
        "sql_crosscheck": analysis["sql_crosscheck"],
    }


def verify_bridge(directory):
    target = Path(directory)
    names = {"case.json", "analysis.json", "bridge.csv", "sources.csv", "bridge.sql", "index.html"}
    if target.is_symlink() or not target.is_dir() or {p.name for p in target.iterdir()} != names:
        raise ContractError("Bridge file set differs")
    if any(p.is_symlink() or not p.is_file() for p in target.iterdir()):
        raise ContractError("Bridge files must be real regular files")
    saved = read_json((target / "analysis.json").read_bytes())
    expected = build_bridge(read_json((target / "case.json").read_bytes()), saved["as_of"], saved["language"])
    for name, raw in expected.items():
        if (target / name).read_bytes() != raw:
            raise ContractError(f"Bridge replay differs: {name}")
    return {"verified": True, "issuer_years": len(saved["rows"]), "as_of": saved["as_of"]}
