"""Self-contained HTML, CSV, and semantic replay of a deterministic report."""

import base64
import csv
import html
import io
import json
import re
from pathlib import Path

from .contracts import ContractError, canonical, digest, read_json
from .engine import METRICS, analyze

FILES = {
    "facts.json",
    "request.json",
    "analysis.json",
    "selected_facts.csv",
    "metrics.csv",
    "lineage.csv",
    "decisions.csv",
    "index.html",
}

METRIC_FIELDS = ("as_of", "period", "metric", "formula", "unit", "status", "exact", "display", "missing")
FACT_FIELDS = (
    "as_of",
    "period",
    "metric",
    "status",
    "value_usd",
    "start",
    "end",
    "filed",
    "tag",
    "accession",
    "fact_id",
    "source_url",
)

VIEW_SCRIPT = r"""
const cutoff = document.querySelector('#cutoff');
const period = document.querySelector('#period');
const panels = Array.from(document.querySelectorAll('section[data-period]'));
const viewLink = document.querySelector('#view-link');
const viewStatus = document.querySelector('#view-status');
const defaultCutoff = cutoff.options[cutoff.options.length - 1].value;
const defaultPeriod = period.options[period.options.length - 1].value;

function refresh() {
    panels.forEach(panel => {
        panel.hidden = panel.dataset.cutoff !== cutoff.value || panel.dataset.period !== period.value;
    });
    const params = new URLSearchParams({as_of: cutoff.value, period: JSON.parse(period.value)});
    const url = new URL(window.location.href);
    url.hash = params.toString();
    viewLink.href = url.href;
    document.querySelector('#share-view').hidden = false;
}

function restore() {
    cutoff.value = defaultCutoff;
    period.value = defaultPeriod;
    viewStatus.textContent = '';
    if (window.location.hash) {
        try {
            const fragment = window.location.hash.slice(1);
            // Reject malformed escapes/UTF-8 before URLSearchParams can replace them.
            decodeURIComponent(fragment.replace(/\+/g, ' '));
            const params = new URLSearchParams(fragment);
            const selected = Array.from(period.options).find(
                option => JSON.parse(option.value) === params.get('period')
            );
            if (Array.from(params).length !== 2 || params.getAll('as_of').length !== 1 ||
                params.getAll('period').length !== 1 || !selected || !panels.some(
                    panel => panel.dataset.cutoff === params.get('as_of') &&
                        panel.dataset.period === selected.value
                )) throw new Error('Unavailable view');
            cutoff.value = params.get('as_of');
            period.value = selected.value;
        } catch {
            viewStatus.textContent = 'Saved view unavailable; showing the latest configured view.';
        }
    }
    refresh();
}

function selectView() {
    viewStatus.textContent = '';
    refresh();
    if (window.location.href !== viewLink.href) history.pushState(null, '', viewLink.href);
}

cutoff.addEventListener('change', selectView);
period.addEventListener('change', selectView);
window.addEventListener('popstate', restore);
window.addEventListener('hashchange', restore);
restore();
"""


def csv_bytes(rows, fields):
    stream = io.StringIO(newline="")
    # A CRLF writer quotes lone CR characters as well as LF. Normalize only
    # its final record terminator, preserving embedded CR/CRLF in quoted cells.
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\r\n")

    def record(row):
        stream.seek(0)
        stream.truncate(0)
        writer.writerow({key: csv_label(value) if key == "period" else value for key, value in row.items()})
        return stream.getvalue()[:-2] + "\n"

    return (record(dict(zip(fields, fields, strict=True))) + "".join(record(row) for row in rows)).encode("utf-8")


def csv_label(value):
    """Display untrusted labels as text; raw identities remain in JSON."""
    prefix = "text: "
    if value.startswith((prefix, "\t", "\r", "\n", "\x00", "\ufeff")) or value.lstrip(
        " \t\r\n\v\f\x00\ufeff"
    ).startswith(("=", "+", "-", "@", "＝", "＋", "－", "＠")):
        # A visible, ordinary text prefix avoids relying on a leading quote
        # that spreadsheet software can remove when the CSV is saved again.
        return prefix + value
    return value


def metric_rows(panel):
    return [
        {
            "as_of": panel["as_of"],
            "period": panel["period"]["label"],
            **{key: metric[key] for key in ("metric", "formula", "unit", "status", "exact", "display")},
            "missing": ";".join(metric["missing"]),
        }
        for metric in panel["metrics"]
    ]


def selected_fact_rows(panel):
    rows = []
    for name in METRICS:
        fact = panel["facts"][name]
        record = fact["record"] if fact else {}
        rows.append(
            {
                "as_of": panel["as_of"],
                "period": panel["period"]["label"],
                "metric": name,
                "status": "ok" if fact else "missing",
                "value_usd": record.get("val", ""),
                "start": record.get("start", ""),
                "end": record.get("end", ""),
                "filed": record.get("filed", ""),
                "tag": fact["tag"] if fact else "",
                "accession": record.get("accn", ""),
                "fact_id": fact["fact_id"] if fact else "",
                "source_url": fact["source_url"] if fact else "",
            }
        )
    return rows


def view_csv_filename(panel, kind):
    """Keep filenames readable, path-safe and distinct for exact period identities."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", panel["period"]["label"]).strip("-")[:32] or "period"
    identity = digest(canonical(panel["period"]))[:16]
    return f"statementtrace-{kind}-{panel['as_of']}-{slug}-{identity}.csv"


def render(analysis):
    esc = html.escape
    panels = []
    for panel in analysis["panels"]:
        facts = []
        for name, fact in panel["facts"].items():
            if fact is None:
                facts.append(f"<tr><td>{esc(name)}</td><td colspan='4'>Missing at this cutoff</td></tr>")
            else:
                row = fact["record"]
                facts.append(
                    f"<tr><td>{esc(name)}</td><td>{row['val']:,}</td>"
                    f"<td>{esc(row['filed'])}</td><td>{esc(fact['tag'])}</td>"
                    f"<td><a href='{esc(fact['source_url'], quote=True)}'>"
                    f"{esc(row['accn'])}</a></td></tr>"
                )
        metrics = []
        for metric in panel["metrics"]:
            source_ids = ", ".join(item["fact_id"][:12] for item in metric["inputs"])
            metrics.append(
                f"<tr><td>{esc(metric['metric'])}</td><td>{esc(metric['display'])}</td>"
                f"<td>{esc(metric['unit'])}</td><td>{esc(metric['status'])}</td>"
                f"<td><code>{esc(metric['formula'])}</code><br>"
                f"<small>Fact IDs: {source_ids}</small></td></tr>"
            )
        label, cutoff = esc(panel["period"]["label"]), esc(panel["as_of"])
        period_key = esc(json.dumps(panel["period"]["label"], ensure_ascii=True), quote=True)
        metric_csv = base64.b64encode(csv_bytes(metric_rows(panel), METRIC_FIELDS)).decode("ascii")
        fact_csv = base64.b64encode(csv_bytes(selected_fact_rows(panel), FACT_FIELDS)).decode("ascii")
        panels.append(
            f"<section data-period='{period_key}' data-cutoff='{cutoff}'>"
            f"<h2>FY {label} · as of {cutoff}</h2><p>"
            f"{esc(panel['period']['start'])} → {esc(panel['period']['end'])} · "
            f"{panel['duration_days']} inclusive days · amounts in USD</p>"
            "<h3>Financial metrics / 财务指标</h3>"
            f"<p><a class='view-csv' href='data:text/csv;charset=utf-8;base64,{metric_csv}' "
            f"download='{view_csv_filename(panel, 'metrics')}'>Download these metrics · CSV</a>"
            " · Includes this cutoff/year, formulas, exact values and missing-input statuses.</p>"
            "<div class='scroll'><table>"
            "<thead><tr><th>Metric</th><th>Value</th><th>Unit</th><th>Status</th>"
            "<th>Formula and lineage</th></tr></thead><tbody>" + "".join(metrics) + "</tbody></table></div>"
            "<h3>Selected facts / 原始数据</h3>"
            f"<p><a class='view-facts-csv' href='data:text/csv;charset=utf-8;base64,{fact_csv}' "
            f"download='{view_csv_filename(panel, 'facts')}'>Download selected facts · CSV</a>"
            " · This panel's selected facts, including missing rows and full source metadata. "
            "For the growth metric's prior-period input, use <a href='lineage.csv'>Full lineage</a> "
            "with the complete report.</p><div class='scroll'><table>"
            "<thead><tr><th>Fact</th><th>USD</th><th>Filed</th><th>Concept</th>"
            "<th>SEC filing</th></tr></thead><tbody>" + "".join(facts) + "</tbody></table></div></section>"
        )
    cutoffs = sorted({p["as_of"] for p in analysis["panels"]})
    periods = list(dict.fromkeys(p["period"]["label"] for p in analysis["panels"]))

    def options(values, *, identities=False):
        return "".join(
            f"<option value='{esc(json.dumps(v, ensure_ascii=True) if identities else v, quote=True)}'>"
            f"{esc(v)}</option>"
            for v in values
        )

    return (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>StatementTrace · financial statement evidence</title><style>"
        "*{box-sizing:border-box}body{margin:0;background:#f5f7fa;color:#172c42;"
        "font:15px/1.6 system-ui}header,main{max-width:1200px;margin:auto;padding:28px}"
        "header{border-bottom:4px solid #128a82}h1{font-size:42px;margin:0}"
        "h2{margin-top:0}p{max-width:90ch}.eyebrow{color:#128a82;font-weight:700}"
        "section,.toolbar{padding:24px;background:white;border:1px solid #dae3e9;"
        "border-radius:12px;margin:20px 0}.scroll{overflow-x:auto}"
        "table{border-collapse:collapse;width:100%;font-size:13px}"
        "th,td{padding:12px;text-align:left;border-bottom:1px solid #e2e8ed;vertical-align:top}"
        "th{background:#edf5f7}a{color:#0a766e}select{font:inherit;padding:8px;min-width:0;max-width:100%}"
        ".selectors{display:flex;flex-wrap:wrap;gap:12px 20px}"
        ".selectors label{display:flex;align-items:center;gap:8px;min-width:0;max-width:100%}"
        "code,small{overflow-wrap:anywhere}section[hidden]{display:none}"
        "@media(max-width:640px){h1{font-size:30px}header,main{padding:16px}}"
        "</style><header><p class='eyebrow'>PUBLIC FILING → PERIOD CONTRACT → SOURCE LINEAGE</p>"
        f"<h1>StatementTrace</h1><p>{esc(analysis['entity'])} · CIK {analysis['cik']}</p>"
        "<p>公开财报指标追溯。切换申报截止日，观察当时可用的数据。"
        "Saved financial facts are replayed locally; the demo uses a curated filing excerpt."
        " Cutoffs use the SEC filed date, with no intraday availability assumption.</p>"
        "<p><a href='https://github.com/dev-belly/StatementTrace'>GitHub project</a> · "
        "<a href='https://github.com/dev-belly/StatementTrace/blob/main/docs/METHODOLOGY.md'>Method</a> · "
        "<a href='https://github.com/dev-belly'>Author profile</a></p></header>"
        "<main><div class='toolbar'><div class='selectors'><label>As of <select id='cutoff'>"
        + options(cutoffs)
        + "</select></label><label>Fiscal year <select id='period'>"
        + options(periods, identities=True)
        + "</select></label></div><p id='share-view' hidden><a id='view-link'>Link to this view</a> · "
        "The address bar follows your selection. Open or copy this link to share it.</p>"
        "<p id='view-status' role='status'></p>"
        "<noscript><p>JavaScript is off; all saved cutoff/year panels are shown below.</p></noscript>"
        "<p><a href='selected_facts.csv'>Facts CSV</a> · "
        "<a href='metrics.csv'>All metrics CSV</a> · <a href='lineage.csv'>Full lineage</a> · "
        "<a href='decisions.csv'>Selection decisions</a> · "
        "<a href='manifest.json'>SHA-256 manifest</a></p></div>"
        + "".join(panels)
        + "<p>Missing is not zero. Ratios are exact rational values; display is rounded. "
        "Replay locally: <code>statementtrace verify examples/demo</code>. "
        "The verifier checks consistency with bundled inputs; hashes do not authenticate SEC data."
        "</p></main><script>" + VIEW_SCRIPT + "</script></html>\n"
    ).encode("utf-8")


def build(data, request):
    analysis = analyze(data, request)
    selected, metrics, lineage = [], [], []
    for panel in analysis["panels"]:
        base = {"as_of": panel["as_of"], "period": panel["period"]["label"]}
        selected.extend(selected_fact_rows(panel))
        metrics.extend(metric_rows(panel))
        for metric in panel["metrics"]:
            lineage.extend({**base, "metric": metric["metric"], **item} for item in metric["inputs"])
    files = {
        "facts.json": canonical(data),
        "request.json": canonical(request),
        "analysis.json": canonical(analysis),
        "index.html": render(analysis),
        "selected_facts.csv": csv_bytes(selected, FACT_FIELDS),
        "metrics.csv": csv_bytes(metrics, list(metrics[0])),
        "lineage.csv": csv_bytes(lineage, ["as_of", "period", "metric", "role", "fact_id"]),
        "decisions.csv": csv_bytes(analysis["decisions"], ["as_of", "period", "metric", "fact_id", "reason"]),
    }
    files["manifest.json"] = canonical(
        {"schema_version": 1, "files": {name: digest(raw) for name, raw in sorted(files.items())}}
    )
    return files


def write_report(data, request, directory):
    files = build(data, request)
    target = Path(directory)
    if target.is_symlink() or (target.exists() and any(target.iterdir())):
        raise ContractError("Output must be a new or empty directory")
    target.mkdir(parents=True, exist_ok=True)
    for name, raw in files.items():
        (target / name).write_bytes(raw)
    return read_json(files["analysis.json"])


def verify(directory):
    target = Path(directory)
    if target.is_symlink() or not target.is_dir():
        raise ContractError("Report must be a regular directory")
    expected = FILES | {"manifest.json"}
    if {p.name for p in target.iterdir()} != expected:
        raise ContractError("Report file set does not match the schema")
    if any(p.is_symlink() or not p.is_file() for p in target.iterdir()):
        raise ContractError("Report members must be regular files, not symlinks")
    manifest = read_json((target / "manifest.json").read_bytes())
    actual = {name: digest((target / name).read_bytes()) for name in sorted(FILES)}
    if manifest != {"schema_version": 1, "files": actual}:
        raise ContractError("Report hash manifest mismatch")
    data = read_json((target / "facts.json").read_bytes())
    request = read_json((target / "request.json").read_bytes())
    replay = build(data, request)
    for name, raw in replay.items():
        if (target / name).read_bytes() != raw:
            raise ContractError(f"Semantic replay mismatch: {name}")
    return {"verified": True, "files": len(replay), "panels": len(analyze(data, request)["panels"])}
