"""Windows API smoke cleanup must release inherited server-log handles."""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from scripts.check_api import stop_server


@unittest.skipUnless(os.name == "nt", "Windows process-tree and file-handle regression")
class ApiProcessCleanupTests(unittest.TestCase):
    def test_launcher_descendants_release_server_log(self):
        child_code = (
            "import os,sys,time; from pathlib import Path; "
            "Path(sys.argv[1]).write_text(str(os.getpid()),encoding='ascii'); time.sleep(60)"
        )
        parent_code = (
            "import subprocess,sys,time; "
            "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); time.sleep(60)"
        )
        with tempfile.TemporaryDirectory(prefix="statementtrace-http-cleanup-") as temp:
            root = Path(temp)
            ready = root / "ready"
            log_path = root / "server.log"
            child_pid = None
            with log_path.open("wb") as log:
                process = subprocess.Popen(
                    [sys.executable, "-c", parent_code, child_code, str(ready)],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                try:
                    deadline = time.monotonic() + 10
                    while not ready.exists() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    self.assertTrue(ready.exists(), "The descendant did not start")
                    child_pid = int(ready.read_text(encoding="ascii"))
                    stop_server(process)
                    log.close()
                    # Windows rejects this while any descendant still owns stdout.
                    log_path.unlink()
                finally:
                    if child_pid is not None:
                        subprocess.run(
                            ["taskkill", "/PID", str(child_pid), "/T", "/F"],
                            capture_output=True,
                            check=False,
                        )
                    if process.poll() is None:
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            capture_output=True,
                            check=False,
                        )
                    process.wait(timeout=10)
