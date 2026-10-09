"""Check committed demo bytes against a fresh build; do not update evidence in CI."""

from pathlib import Path

from statementtrace.cli import demo_inputs
from statementtrace.report import build

root = Path(__file__).resolve().parents[1] / "examples" / "demo"
expected = build(*demo_inputs())
if not root.is_dir() or {p.name for p in root.iterdir()} != set(expected):
    raise SystemExit("Committed demo file set differs from a fresh build")
for name, raw in expected.items():
    if (root / name).read_bytes() != raw:
        raise SystemExit(f"Committed demo is stale: {name}")
print(f"Replayed {len(expected)} committed report files exactly")
