"""Replay the committed six-file profit/CFO bridge without rewriting evidence."""

from pathlib import Path

from statementtrace.profit_bridge import build_bridge, demo_bridge_case, verify_bridge

target = Path(__file__).resolve().parents[1] / "examples" / "profit-bridge"
expected = build_bridge(demo_bridge_case())
if not target.is_dir() or {p.name for p in target.iterdir()} != set(expected):
    raise SystemExit("Committed profit-bridge file set differs")
for name, raw in expected.items():
    if (target / name).read_bytes() != raw:
        raise SystemExit(f"Committed profit-bridge packet is stale: {name}")
print(verify_bridge(target))
