"""Exercise report selectors in the runner's real Chrome, without Python extras.

Requires Google Chrome and a matching chromedriver on PATH, or the
CHROMEWEBDRIVER directory supplied by GitHub's Ubuntu runner image.
"""

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


SCRIPT = r"""
const spec = arguments[0];
const select = document.getElementById(spec.select);
if (!select) throw new Error('Missing selector');
for (const label of spec.labels) {
    const option = Array.from(select.options).find(o => o.value && JSON.parse(o.value) === label);
    if (!option) throw new Error('Missing exact identity: ' + JSON.stringify(label));
    select.value = option.value;
    select.dispatchEvent(new Event('change', {bubbles:true}));
    if (spec.chart) {
        const expected = data.histograms[label].counts;
        const actual = Array.from(document.querySelectorAll('#histogram rect'), r => Number(r.getAttribute('height')));
        const peak = Math.max(...expected,1);
        if (actual.length !== expected.length || actual.some((v,i) => Math.abs(v-200*expected[i]/peak)>1e-10))
            throw new Error('Histogram selected another scenario');
        const sectors = data.sector_es.filter(r => r.scenario === label).length;
        if (!sectors || document.querySelectorAll('#sectors tr').length !== sectors)
            throw new Error('Sector attribution missing or selected another scenario');
    } else {
        const rows = Array.from(document.querySelectorAll(spec.rows)).filter(r => getComputedStyle(r).display !== 'none');
        if (!rows.length || rows.some(r => JSON.parse(r.dataset[spec.attribute]) !== label))
            throw new Error('Empty or incorrect filtered result: ' + JSON.stringify(label));
    }
}
return spec.labels.length;
"""


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
                        "goog:chromeOptions": {"args": ["--headless=new", "--no-sandbox", "--disable-dev-shm-usage"]},
                    }
                }
            },
        )["sessionId"]
        selections = 0
        for case in cases:
            call("POST", f"/session/{session}/url", {"url": (root / case["file"]).as_uri()})
            selections += call("POST", f"/session/{session}/execute/sync", {"script": SCRIPT, "args": [case]})
        print(json.dumps({"status": "passed", "browser": "Chrome", "reports": len(cases), "selections": selections}))
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
    from statementtrace.report import build

    pairs = [["sample\rone", "sample\none"], ["sample\x00one", "sample�one"]]
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        cases = []
        for index, labels in enumerate(pairs):
            data, request = demo_inputs()
            for row, label in zip(request["periods"], labels, strict=True):
                row["label"] = label
            filename = f"report-{index}.html"
            (root / filename).write_bytes(build(data, request)["index.html"])
            cases.append(
                {
                    "file": filename,
                    "select": "period",
                    "rows": "section[data-period]",
                    "attribute": "period",
                    "labels": labels,
                }
            )
        browser_check(cases, root)


if __name__ == "__main__":
    main()
