"""Install the real warehouse wheel and replay it outside the source checkout."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from check_api import check as check_api

ROOT = Path(__file__).resolve().parents[1]


def check():
    # Use native paths and argv on Windows; Git Bash can reinterpret drive paths.
    with tempfile.TemporaryDirectory(prefix="statementtrace-wheel-") as temp:
        root = Path(temp)
        wheels, installed, packet = root / "wheels", root / "installed", root / "packet"
        env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        for argv in (
            ["uv", "build", "--wheel", "--out-dir", str(wheels)],
            ["uv", "venv", "--python", sys.executable, str(installed)],
        ):
            subprocess.run(argv, cwd=ROOT, env=env, check=True)
        wheel_files = list(wheels.glob("*.whl"))
        if len(wheel_files) != 1:
            raise RuntimeError("Expected exactly one project wheel")
        executable = installed / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run(
            ["uv", "pip", "install", "--python", str(executable), f"{wheel_files[0]}[warehouse,api]"],
            cwd=root,
            env=env,
            check=True,
        )
        for arguments in (["warehouse", "--out", str(packet)], ["verify-warehouse", str(packet)]):
            run = subprocess.run(
                [str(executable), "-m", "statementtrace", *arguments],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            result = json.loads(run.stdout)
            if result.get("source_rows") != 24 or result.get("python_duckdb") != {"rows": 6, "cells": 138}:
                raise RuntimeError("Installed wheel returned unexpected financial results")
        if result.get("verified") is not True:
            raise RuntimeError("Installed wheel did not verify its packet")
        http = check_api(packet, executable)
    return {"installed_wheel": True, "outside_checkout": True, "source_rows": 24, "verified": True, "api": http}


if __name__ == "__main__":
    print(json.dumps(check(), sort_keys=True))
