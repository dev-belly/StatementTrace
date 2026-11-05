"""Exercise report selectors in the runner's real Chrome, without Python extras.

Requires Google Chrome and a matching chromedriver on PATH, or the
CHROMEWEBDRIVER directory supplied by GitHub's Ubuntu runner image.
"""

import csv
import io
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ASSERT_VIEW = r"""
function assertView(expected, exactAddress, unavailable) {
    const selected = Array.from(document.querySelectorAll('section[data-period]')).filter(s => !s.hidden);
    if (selected.length !== 1 || selected[0].dataset.cutoff !== expected.as_of ||
        JSON.parse(selected[0].dataset.period) !== expected.period)
        throw new Error('Incorrect visible cutoff/period');
    const values = Array.from(selected[0].querySelectorAll('table')[0].querySelectorAll('tbody tr'),
        row => Array.from(row.querySelectorAll('td')).slice(0,4).map(cell => cell.textContent));
    if (JSON.stringify(values) !== JSON.stringify(expected.metrics)) throw new Error('Financial metrics differ');
    const sources = Array.from(selected[0].querySelectorAll('table')[1].querySelectorAll('a'), a => a.href);
    if (JSON.stringify(sources) !== JSON.stringify(expected.sources)) throw new Error('Source links differ');
    for (const [kind, selector] of [['metrics', '.view-csv'], ['facts', '.view-facts-csv']]) {
        const download = selected[0].querySelector(selector);
        if (!download || download.download !== expected.csv_filenames[kind] ||
            !download.href.startsWith('data:text/csv;charset=utf-8;base64,'))
            throw new Error('Missing current-view ' + kind + ' CSV download');
    }
    const link = document.getElementById('view-link');
    const url = new URL(link.href);
    const params = new URLSearchParams(url.hash.slice(1));
    if (params.get('as_of') !== expected.as_of || params.get('period') !== expected.period ||
        Array.from(params).length !== 2 || url.search !== '?review=1' ||
        (exactAddress && location.href !== link.href) || document.getElementById('share-view').hidden)
        throw new Error('View link differs from displayed state');
    if (Boolean(document.getElementById('view-status').textContent) !== unavailable)
        throw new Error('Unavailable-view notice differs');
    if (document.documentElement.scrollWidth > innerWidth + 1) throw new Error('Page overflows viewport');
    for (const href of ['https://github.com/dev-belly/StatementTrace', 'https://github.com/dev-belly']) {
        if (!Array.from(document.querySelectorAll('a')).some(a => a.href === href))
            throw new Error('Missing project or author route');
    }
    return link.href;
}
"""

SELECT_VIEW = (
    ASSERT_VIEW
    + r"""
const expected = arguments[0];
const option = Array.from(document.getElementById('period').options).find(
    o => JSON.parse(o.value) === expected.period
);
document.getElementById('period').value = option.value;
document.getElementById('cutoff').value = expected.as_of;
document.getElementById(arguments[1]).dispatchEvent(new Event('change', {bubbles:true}));
return assertView(expected, true, false);
"""
)

CHECK_VIEW = ASSERT_VIEW + "return assertView(arguments[0], arguments[1], arguments[2]);"
WAIT_VIEW = (
    ASSERT_VIEW
    + r"""
try { assertView(arguments[0], arguments[1], arguments[2]); return true; }
catch { return false; }
"""
)


def browser_check(cases, root):
    driver = shutil.which("chromedriver")
    if not driver:
        candidate = Path(os.environ.get("CHROMEWEBDRIVER", "")) / "chromedriver"
        if candidate.is_file():
            driver = str(candidate.resolve())
    if not driver:
        raise RuntimeError("Install Chrome and a matching chromedriver, or set CHROMEWEBDRIVER")
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    address = f"http://127.0.0.1:{port}"

    def call(method, endpoint, payload=None):
        request = urllib.request.Request(
            address + endpoint,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)["value"]
        except urllib.error.HTTPError as error:
            raise RuntimeError(error.read().decode()) from error

    downloads = root / "downloads"
    downloads.mkdir()
    session = None
    process = subprocess.Popen([driver, f"--port={port}"], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        for _ in range(50):
            try:
                call("GET", "/status")
                break
            except urllib.error.URLError:
                if process.poll() is not None:
                    raise RuntimeError("chromedriver exited before becoming ready") from None
                time.sleep(0.1)
        else:
            raise RuntimeError("chromedriver did not become ready")
        session = call(
            "POST",
            "/session",
            {
                "capabilities": {
                    "alwaysMatch": {
                        "browserName": "chrome",
                        "goog:chromeOptions": {
                            "args": ["--headless=new", "--no-sandbox", "--disable-dev-shm-usage"],
                            "prefs": {
                                "download.default_directory": str(downloads),
                                "download.prompt_for_download": False,
                            },
                        },
                    }
                }
            },
        )["sessionId"]

        def execute(script, *args):
            return call("POST", f"/session/{session}/execute/sync", {"script": script, "args": list(args)})

        def navigate(url):
            call("POST", f"/session/{session}/url", {"url": url})

        def wait_view(view, *, exact=True, unavailable=False):
            for _ in range(40):
                if execute(WAIT_VIEW, view, exact, unavailable):
                    return execute(CHECK_VIEW, view, exact, unavailable)
                time.sleep(0.05)
            return execute(CHECK_VIEW, view, exact, unavailable)  # Preserve the actual assertion diagnostic.

        def download_view(view, kind, *, scope="section:not([hidden])"):
            path = downloads / view["csv_filenames"][kind]
            path.unlink(missing_ok=True)
            selector = scope + (" .view-csv" if kind == "metrics" else " .view-facts-csv")
            element = call("POST", f"/session/{session}/element", {"using": "css selector", "value": selector})[
                "element-6066-11e4-a52e-4f735466cecf"
            ]
            call("POST", f"/session/{session}/element/{element}/click", {})
            for _ in range(100):
                if path.is_file():
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("Chrome did not save the view CSV")
            raw = path.read_bytes()
            rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True))
            if rows != view["csv_rows" if kind == "metrics" else "fact_csv_rows"]:
                raise AssertionError("Downloaded CSV differs from the selected full-export slice")
            counts["downloads"] += 1
            counts["downloaded_metric_rows" if kind == "metrics" else "downloaded_fact_rows"] += len(rows)
            return path, raw

        counts = dict(
            visits=0,
            selections=0,
            metric_rows=0,
            round_trips=0,
            history_checks=0,
            invalid_links=0,
            downloads=0,
            downloaded_metric_rows=0,
            downloaded_fact_rows=0,
            distinct_period_downloads=0,
        )
        viewport_widths = []
        for width in (1280, 390):
            call("POST", f"/session/{session}/window/rect", {"width": width, "height": 1000})
            for case_index, case in enumerate(cases):
                base = (root / case["file"]).as_uri() + "?review=1"
                navigate(base)
                actual_width = execute("return window.innerWidth;")
                if actual_width != width:
                    raise AssertionError(f"Requested width {width}, observed {actual_width}")
                if case_index == 0:
                    viewport_widths.append(actual_width)
                counts["visits"] += 1
                latest = case["views"][-1]
                wait_view(latest, exact=False)
                for index, view in enumerate(case["views"]):
                    execute(SELECT_VIEW, view, "cutoff" if index % 2 else "period")
                    counts["selections"] += 1
                    counts["metric_rows"] += len(view["metrics"])
                for kind in ("metrics", "facts"):
                    download_view(latest, kind)
                before = next(
                    v for v in case["views"] if v["as_of"] == "2024-10-31" and v["period"] == latest["period"]
                )
                execute(SELECT_VIEW, before, "cutoff")
                for kind in ("metrics", "facts"):
                    download_view(before, kind)
                # Keep both years' files at one cutoff, rather than deleting a
                # colliding filename and allowing Chrome to add an unseen suffix.
                other_period = next(
                    view
                    for view in case["views"]
                    if view["as_of"] == latest["as_of"] and view["period"] != latest["period"]
                )
                for kind in ("metrics", "facts"):
                    execute(SELECT_VIEW, latest, "period")
                    first_path, first_raw = download_view(latest, kind)
                    execute(SELECT_VIEW, other_period, "period")
                    second_path, _ = download_view(other_period, kind)
                    if first_path == second_path or first_path.read_bytes() != first_raw:
                        raise AssertionError("Same-cutoff period downloads must remain distinct and unchanged")
                    counts["distinct_period_downloads"] += 1
                first = case["views"][0]
                shared = execute(SELECT_VIEW, first, "period")
                navigate(base)
                wait_view(latest, exact=False)
                navigate(shared)
                wait_view(first)
                counts["round_trips"] += 1
                execute(SELECT_VIEW, latest, "cutoff")
                call("POST", f"/session/{session}/back", {})
                wait_view(first)
                call("POST", f"/session/{session}/forward", {})
                wait_view(latest)
                counts["history_checks"] += 2
                for fragment in (
                    "as_of=1900-01-01&period=2024",
                    "as_of=2024-11-01&period=unknown",
                    "as_of=2024-11-01&period=2024&period=2023",
                    "as_of=2024-11-01&as_of=2024-10-31&period=2024",
                    "as_of=2024-11-01",
                    "as_of=2024-11-01&period=2024&unexpected=1",
                    "as_of=2024-11-01&period=sample%FFone",
                    "as_of=2024-11-01&period=%E0%A4",
                ):
                    navigate(base + "#" + fragment)
                    wait_view(latest, exact=False, unavailable=True)
                    counts["invalid_links"] += 1
                element = call("POST", f"/session/{session}/element", {"using": "css selector", "value": "#view-link"})[
                    "element-6066-11e4-a52e-4f735466cecf"
                ]
                call("POST", f"/session/{session}/element/{element}/click", {})
                wait_view(latest)
                if case_index == 0:
                    for kind in ("metrics", "facts"):
                        download_view(latest, kind)

        call(
            "POST",
            f"/session/{session}/goog/cdp/execute",
            {"cmd": "Emulation.setScriptExecutionDisabled", "params": {"value": True}},
        )
        try:
            navigate((root / cases[0]["file"]).as_uri() + "?no-js=1")
            visible = execute("return document.querySelectorAll('section:not([hidden])').length;")
            if visible != len(cases[0]["views"]) or not execute("return document.getElementById('share-view').hidden;"):
                raise AssertionError("No-JavaScript view must retain every saved panel")
            for kind in ("metrics", "facts"):
                download_view(cases[0]["views"][0], kind, scope="section")
        finally:
            call(
                "POST",
                f"/session/{session}/goog/cdp/execute",
                {"cmd": "Emulation.setScriptExecutionDisabled", "params": {"value": False}},
            )
        print(
            json.dumps(
                {
                    "status": "passed",
                    "browser": "Chrome",
                    "reports": len(cases),
                    "viewports": viewport_widths,
                    "no_js_panels": visible,
                    **counts,
                }
            )
        )
    finally:
        if session is not None:
            try:
                call("DELETE", f"/session/{session}")
            finally:
                process.terminate()
        else:
            process.terminate()
        process.wait(timeout=10)


def main():
    from statementtrace.cli import demo_inputs
    from statementtrace.engine import analyze
    from statementtrace.report import build, csv_label, view_csv_filename

    pairs = [
        ["2023", "2024"],
        ["sample\rone", "sample\none"],
        ["sample\x00one", "sample�one"],
        [' 年报 +&%#?/ " 🧾 ', "\tAnnual <2024>\n"],
        ["=1+1", "text: =1+1"],
    ]
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        cases = []
        for index, labels in enumerate(pairs):
            data, request = demo_inputs()
            for row, label in zip(request["periods"], labels, strict=True):
                row["label"] = label
            filename = f"report-{index}.html"
            outputs = build(data, request)
            (root / filename).write_bytes(outputs["index.html"])
            all_metrics = list(
                csv.DictReader(io.StringIO(outputs["metrics.csv"].decode("utf-8"), newline=""), strict=True)
            )
            all_facts = list(
                csv.DictReader(io.StringIO(outputs["selected_facts.csv"].decode("utf-8"), newline=""), strict=True)
            )
            views = [
                {
                    "as_of": panel["as_of"],
                    "period": panel["period"]["label"],
                    "metrics": [[m[key] for key in ("metric", "display", "unit", "status")] for m in panel["metrics"]],
                    "sources": [fact["source_url"] for fact in panel["facts"].values() if fact is not None],
                    "csv_filenames": {kind: view_csv_filename(panel, kind) for kind in ("metrics", "facts")},
                    "csv_rows": [
                        row
                        for row in all_metrics
                        if row["as_of"] == panel["as_of"] and row["period"] == csv_label(panel["period"]["label"])
                    ],
                    "fact_csv_rows": [
                        row
                        for row in all_facts
                        if row["as_of"] == panel["as_of"] and row["period"] == csv_label(panel["period"]["label"])
                    ],
                }
                for panel in analyze(data, request)["panels"]
            ]
            cases.append({"file": filename, "views": views})
        browser_check(cases, root)


if __name__ == "__main__":
    main()
