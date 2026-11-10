"""Replay the committed historical research packet without changing it."""

from pathlib import Path

from statementtrace.cashflow import build, demo_case

target = Path(__file__).resolve().parents[1] / "examples" / "cashflow"
expected = build(demo_case())
if not target.is_dir() or {path.name for path in target.iterdir()} != set(expected):
    raise SystemExit("Committed cash-flow packet file set differs from a fresh build")
for name, raw in expected.items():
    if (target / name).read_bytes() != raw:
        raise SystemExit(f"Committed cash-flow packet is stale: {name}")
print("Replayed six research files, 24 selected source facts and six Python/SQL comparison rows")
