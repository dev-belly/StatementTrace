"""Start a real Uvicorn process and inspect the API over localhost HTTP."""

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def stop_server(process):
    """Stop the server and its Windows launcher descendants before closing logs."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        if result.returncode and process.poll() is None:
            raise RuntimeError("Could not stop the API process tree: " + repr(result.stderr))
        process.wait(timeout=10)
    else:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def check(directory, executable=None):
    packet = Path(directory).resolve()
    analysis = json.loads((packet / "analysis.json").read_bytes())
    expected_sources = sum(1 for line in (packet / "source_facts.jsonl").read_bytes().splitlines() if line)
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    requests = 0

    def send(path, method="GET"):
        nonlocal requests
        requests += 1
        request = urllib.request.Request(base + path, method=method)
        try:
            with opener.open(request, timeout=2) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    with tempfile.TemporaryDirectory(prefix="statementtrace-http-") as temp:
        root = Path(temp)
        log_path = root / "server.log"
        env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                [
                    str(executable or sys.executable),
                    "-m",
                    "statementtrace",
                    "serve-warehouse",
                    str(packet),
                    "--port",
                    str(port),
                ],
                cwd=root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("API exited before readiness: " + log_path.read_text(encoding="utf-8"))
                    try:
                        status, raw, _ = send("/healthz")
                        if status == 200:
                            identity = json.loads(raw)
                            break
                    except (urllib.error.URLError, TimeoutError):
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("API did not become ready: " + log_path.read_text(encoding="utf-8"))
                if identity["as_of"] != analysis["as_of"]:
                    raise RuntimeError("HTTP snapshot cutoff differs")
                for path in ("/v1/snapshot", "/v1/quality", "/v1/issuers", "/v1/cashflow", "/v1/facts"):
                    status, raw, headers = send(path)
                    if status != 200 or headers["X-StatementTrace-Snapshot"] != identity["snapshot_id"]:
                        raise RuntimeError("HTTP snapshot identity differs: " + path)
                    data = json.loads(raw)
                    if path == "/v1/cashflow":
                        if data["total"] != len(analysis["rows"]) or len(data["items"]) != min(100, data["total"]):
                            raise RuntimeError("HTTP cash-flow coverage differs")
                        for actual, expected in zip(data["items"], analysis["rows"][:100], strict=True):
                            value = expected["free_cash_flow"]
                            if actual["amounts"]["free_cash_flow"] != (None if value is None else str(value)):
                                raise RuntimeError("HTTP free cash flow lost exactness")
                    if path == "/v1/facts" and data["total"] != expected_sources:
                        raise RuntimeError("HTTP source coverage differs")
                for path, status_expected, method in (
                    ("/openapi.json", 200, "GET"),
                    ("/docs", 200, "GET"),
                    ("/v1/cashflow?as_of=1900-01-01", 422, "GET"),
                    ("/v1/facts?limit=501", 422, "GET"),
                    ("/v1/cashflow?symbol=AAPL&symbol=GOOGL", 422, "GET"),
                    ("/v1/facts", 405, "POST"),
                ):
                    status, _, _ = send(path, method)
                    if status != status_expected:
                        raise RuntimeError(f"HTTP {method} {path}: {status}, expected {status_expected}")
            finally:
                stop_server(process)
    return {"real_http": True, "routes": 6, "requests": requests, **identity}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    args = parser.parse_args()
    print(json.dumps(check(args.directory), sort_keys=True))
