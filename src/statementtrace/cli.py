"""Command line entry points."""

import argparse
import json
import sys
from importlib.resources import files
from pathlib import Path

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
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
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
