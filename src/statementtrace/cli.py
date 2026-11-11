"""Command line entry points."""

import argparse
import json
import sys
from importlib.resources import files
from pathlib import Path

from .cashflow import demo_case, verify_comparison, write_comparison
from .contracts import ContractError, read_json
from .report import verify, write_report


def demo_inputs():
    resources = files("statementtrace").joinpath("data")
    return (
        read_json(resources.joinpath("apple_excerpt.json").read_bytes()),
        read_json(resources.joinpath("demo_request.json").read_bytes()),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Replayable public financial statement analysis")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Build the offline Apple filing excerpt demo")
    demo.add_argument("--out", required=True)
    run = commands.add_parser("run", help="Analyze a saved SEC CompanyFacts-shaped JSON")
    run.add_argument("--facts", required=True)
    run.add_argument("--request", required=True)
    run.add_argument("--out", required=True)
    check = commands.add_parser("verify", help="Recompute all outputs, including HTML and lineage")
    check.add_argument("directory")
    comparison = commands.add_parser("compare", help="Build the historical three-issuer cash-flow study")
    comparison.add_argument("--out", required=True)
    comparison.add_argument("--as-of", help="Override the default 2025-02-05 filed-date cutoff")
    comparison_check = commands.add_parser("verify-comparison", help="Recompute a saved cash-flow comparison")
    comparison_check.add_argument("directory")
    warehouse = commands.add_parser("warehouse", help="Build a typed Polars/Parquet/DuckDB financial packet")
    warehouse.add_argument("--out", required=True)
    warehouse.add_argument("--case", help="Saved cash-flow case JSON; default: the three-issuer historical case")
    warehouse.add_argument("--as-of", help="Override the case's filed-date cutoff")
    warehouse_check = commands.add_parser("verify-warehouse", help="Check hashes, source replay and exact SQL parity")
    warehouse_check.add_argument("directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "warehouse":
            from .warehouse import write_warehouse

            case = read_json(Path(args.case).read_bytes()) if args.case else demo_case()
            result = write_warehouse(case, args.out, args.as_of)
        elif args.command == "verify-warehouse":
            from .warehouse import verify_warehouse

            result = verify_warehouse(args.directory)
        elif args.command == "compare":
            result = write_comparison(demo_case(), args.out, args.as_of)
        elif args.command == "verify-comparison":
            result = verify_comparison(args.directory)
        elif args.command == "verify":
            result = verify(args.directory)
        else:
            if args.command == "demo":
                data, request = demo_inputs()
            else:
                data = read_json(Path(args.facts).read_bytes())
                request = read_json(Path(args.request).read_bytes())
            analysis = write_report(data, request, args.out)
            result = {
                "output": str(Path(args.out)),
                "fact_count": analysis["fact_count"],
                "panels": len(analysis["panels"]),
                "verified": verify(args.out)["verified"],
            }
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ContractError, OSError, KeyError, AttributeError, TypeError) as exc:
        print(f"statementtrace: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
