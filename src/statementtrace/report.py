"""Self-contained HTML, CSV, and semantic replay of a deterministic report."""

import csv
import html
import io
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


def csv_bytes(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


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
        panels.append(
            f"<section data-period='{label}' data-cutoff='{cutoff}'>"
            f"<h2>FY {label} · as of {cutoff}</h2><p>"
            f"{esc(panel['period']['start'])} → {esc(panel['period']['end'])} · "
            f"{panel['duration_days']} inclusive days · amounts in USD</p>"
            "<h3>Financial metrics / 财务指标</h3><div class='scroll'><table>"
            "<thead><tr><th>Metric</th><th>Value</th><th>Unit</th><th>Status</th>"
            "<th>Formula and lineage</th></tr></thead><tbody>" + "".join(metrics) + "</tbody></table></div>"
            "<h3>Selected facts / 原始数据</h3><div class='scroll'><table>"
            "<thead><tr><th>Fact</th><th>USD</th><th>Filed</th><th>Concept</th>"
            "<th>SEC filing</th></tr></thead><tbody>" + "".join(facts) + "</tbody></table></div></section>"
        )
    cutoffs = sorted({p["as_of"] for p in analysis["panels"]})
    periods = list(dict.fromkeys(p["period"]["label"] for p in analysis["panels"]))

    def options(values):
        return "".join(f"<option>{esc(v)}</option>" for v in values)

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
        "th{background:#edf5f7}a{color:#0a766e}select{font:inherit;padding:8px;margin:0 20px 0 6px}"
        "code,small{overflow-wrap:anywhere}section[hidden]{display:none}"
        "@media(max-width:640px){h1{font-size:30px}header,main{padding:16px}}"
        "</style><header><p class='eyebrow'>PUBLIC FILING → PERIOD CONTRACT → SOURCE LINEAGE</p>"
        f"<h1>StatementTrace</h1><p>{esc(analysis['entity'])} · CIK {analysis['cik']}</p>"
        "<p>公开财报指标追溯。切换申报截止日，观察当时可用的数据。"
        "Saved financial facts are replayed locally; the demo uses a curated filing excerpt."
        " Cutoffs use the SEC filed date, with no intraday availability assumption.</p></header>"
        "<main><div class='toolbar'><label>As of <select id='cutoff'>"
        + options(cutoffs)
        + "</select></label><label>Fiscal year <select id='period'>"
        + options(periods)
        + "</select></label><p><a href='selected_facts.csv'>Facts CSV</a> · "
        "<a href='metrics.csv'>Metrics CSV</a> · <a href='lineage.csv'>Full lineage</a> · "
        "<a href='decisions.csv'>Selection decisions</a> · "
        "<a href='manifest.json'>SHA-256 manifest</a></p></div>"
        + "".join(panels)
        + "<p>Missing is not zero. Ratios are exact rational values; display is rounded. "
        "Replay locally: <code>statementtrace verify examples/demo</code>. "
        "The verifier checks consistency with bundled inputs; hashes do not authenticate SEC data."
        "</p></main><script>const cutoff=document.querySelector('#cutoff');"
        "const period=document.querySelector('#period');function refresh(){"
        "document.querySelectorAll('section').forEach(s=>{s.hidden="
        "s.dataset.cutoff!==cutoff.value||s.dataset.period!==period.value;});}"
        "cutoff.value=cutoff.options[cutoff.options.length-1].value;"
        "period.value=period.options[period.options.length-1].value;"
        "cutoff.addEventListener('change',refresh);period.addEventListener('change',refresh);"
        "refresh();</script></html>\n"
    ).encode("utf-8")


def build(data, request):
    analysis = analyze(data, request)
    selected, metrics, lineage = [], [], []
    for panel in analysis["panels"]:
        base = {"as_of": panel["as_of"], "period": panel["period"]["label"]}
        for name in METRICS:
            fact = panel["facts"][name]
            row = fact["record"] if fact else {}
            selected.append(
                {
                    **base,
                    "metric": name,
                    "status": "ok" if fact else "missing",
                    "value_usd": row.get("val", ""),
                    "start": row.get("start", ""),
                    "end": row.get("end", ""),
                    "filed": row.get("filed", ""),
                    "tag": fact["tag"] if fact else "",
                    "accession": row.get("accn", ""),
                    "fact_id": fact["fact_id"] if fact else "",
                    "source_url": fact["source_url"] if fact else "",
                }
            )
        for metric in panel["metrics"]:
            metrics.append(
                {
                    **base,
                    **{key: metric[key] for key in ("metric", "formula", "unit", "status", "exact", "display")},
                    "missing": ";".join(metric["missing"]),
                }
            )
            lineage.extend({**base, "metric": metric["metric"], **item} for item in metric["inputs"])
    files = {
        "facts.json": canonical(data),
        "request.json": canonical(request),
        "analysis.json": canonical(analysis),
        "index.html": render(analysis),
        "selected_facts.csv": csv_bytes(selected, list(selected[0])),
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
