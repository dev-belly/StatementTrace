"""Generate the README preview directly from the bundled analysis."""

import argparse
from pathlib import Path

from statementtrace.cli import demo_inputs
from statementtrace.contracts import display
from statementtrace.engine import analyze


def preview():
    analysis = analyze(*demo_inputs())
    final = analysis["panels"][-1]
    metrics = {m["metric"]: m for m in final["metrics"]}
    revenue = final["facts"]["revenue"]["record"]["val"] // 1000000
    fcf = final["facts"]["operating_cash_flow"]["record"]["val"] - final["facts"]["capex"]["record"]["val"]
    from fractions import Fraction

    margin = display(Fraction(metrics["net_margin"]["exact"]) * 100, 2)
    values = [
        ("Revenue · USD millions", f"{revenue:,}"),
        ("Net margin", f"{margin}%"),
        ("Free cash flow · USD millions", f"{fcf // 1000000:,}"),
    ]
    cards = []
    for i, (label, value) in enumerate(values):
        x = 36 + i * 304
        cards.append(
            f'<rect x="{x}" y="130" width="286" height="108" rx="12" fill="#ffffff"/>'
            f'<text x="{x + 18}" y="160" font-size="14" fill="#587082">{label}</text>'
            f'<text x="{x + 18}" y="207" font-size="32" font-weight="700">{value}</text>'
        )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="980" height="400" viewBox="0 0 980 400" '
        'role="img" aria-label="StatementTrace financial statement evidence preview">'
        '<rect width="980" height="400" rx="16" fill="#edf5f7"/>'
        '<g font-family="system-ui,sans-serif" fill="#172c42">'
        '<text x="36" y="54" font-size="32" font-weight="700">StatementTrace</text>'
        '<text x="36" y="88" font-size="17">Apple FY2024 · SEC filed-date cutoff 2024-11-01</text>'
        + "".join(cards)
        + '<text x="36" y="284" font-size="17" fill="#128a82">'
        "33 curated records · 6 as-of panels · 9 metrics per panel</text>"
        '<text x="36" y="321" font-size="16">Exact fiscal periods → selected facts → formulas → source filings</text>'
        '<text x="36" y="356" font-size="14">'
        "Offline public-filing excerpt · missing values remain missing · replayable lineage</text>"
        "</g></svg>\n"
    ).encode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / "docs" / "preview.svg"
    raw = preview()
    if args.check:
        if not target.is_file() or target.read_bytes() != raw:
            raise SystemExit("README preview differs from bundled evidence")
    else:
        target.write_bytes(raw)


if __name__ == "__main__":
    main()
