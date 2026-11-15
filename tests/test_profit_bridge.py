"""Financial, temporal, missing-value and independent replay contracts."""

import base64
import copy
import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from statementtrace.cli import main
from statementtrace.contracts import ContractError, read_json
from statementtrace.profit_bridge import (
    analyze_bridge,
    build_bridge,
    crosscheck_bridge,
    demo_bridge_case,
    verify_bridge,
    write_bridge,
)


class ProfitBridgeTests(unittest.TestCase):
    def test_six_filed_table_reconciliations_and_144_independent_sql_cells(self):
        expected = {
            ("AAPL", "2023"): (96995, 20125, -6577, 110543),
            ("AAPL", "2024"): (93736, 20867, 3651, 118254),
            ("GOOGL", "2023"): (73795, 31796, -3845, 101746),
            ("GOOGL", "2024"): (100118, 33587, -8406, 125299),
            ("MSFT", "2023"): (72361, 17609, -2388, 87582),
            ("MSFT", "2024"): (88136, 28588, 1824, 118548),
        }
        case = demo_bridge_case()
        before = copy.deepcopy(case)
        result = analyze_bridge(case)
        self.assertEqual(case, before)
        self.assertEqual(len(result["rows"]), 6)
        self.assertEqual(len(result["sources"]), 124)
        self.assertEqual(sum(s["status"] == "selected" for s in result["sources"]), 116)
        for row in result["rows"]:
            key = row["symbol"], row["period"]
            self.assertEqual(
                tuple(row[k] for k in ("net_income", "adjustments", "operating_changes", "operating_cash_flow")),
                tuple(v * 1_000_000 for v in expected[key]),
            )
            self.assertEqual(row["reconciliation_residual"], 0)
        self.assertEqual(crosscheck_bridge(result), {"rows": 6, "cells": 144})
        result["rows"][0]["adjustments"] += 1
        with self.assertRaisesRegex(ContractError, "SQL differs"):
            crosscheck_bridge(result)

    def test_year_over_year_drivers_and_cash_boundary_examples(self):
        rows = {r["symbol"]: r for r in analyze_bridge(demo_bridge_case())["rows"] if r["period"] == "2024"}
        expected = {
            "AAPL": (-3259, 742, 10228, 7711),
            "MSFT": (15775, 10979, 4212, 30966),
            "GOOGL": (26323, 1791, -4561, 23553),
        }
        for symbol, values in expected.items():
            self.assertEqual(
                tuple(
                    rows[symbol][k]
                    for k in ("delta_net_income", "delta_adjustments", "delta_operating_changes", "delta_cfo")
                ),
                tuple(v * 1_000_000 for v in values),
            )
            self.assertEqual(rows[symbol]["delta_residual"], 0)
        self.assertEqual(rows["MSFT"]["free_cash_flow"], 74071_000_000)
        self.assertEqual(rows["MSFT"]["fcf_less_acquisition_line"], 4939_000_000)
        self.assertEqual(rows["MSFT"]["fcf_less_lease_principal"], 72785_000_000)
        self.assertEqual(rows["GOOGL"]["fcf_less_acquisition_line"], 69833_000_000)
        self.assertEqual(rows["GOOGL"]["fcf_less_lease_principal"], 72359_000_000)
        self.assertIsNone(rows["AAPL"]["finance_lease_additions"])
        self.assertIsNone(rows["AAPL"]["fcf_less_acquisition_line"])
        self.assertEqual(rows["AAPL"]["combined_lease_additions"], 1000_000_000)

    def test_publication_cutoff_redacts_future_detail_values(self):
        for cutoff, visible in (
            ("2024-07-29", set()),
            ("2024-07-30", {"MSFT"}),
            ("2024-11-01", {"AAPL", "MSFT"}),
            ("2025-02-04", {"AAPL", "MSFT"}),
        ):
            with self.subTest(cutoff=cutoff):
                result = analyze_bridge(demo_bridge_case(), cutoff)
                self.assertEqual(crosscheck_bridge(result)["cells"], 144)
                for row in result["rows"]:
                    self.assertEqual(row["status"], "ok" if row["symbol"] in visible else "missing_input")
                    if row["symbol"] not in visible:
                        self.assertIsNone(row["calculated_cfo"])
                for source in result["sources"]:
                    if source["filed"] > cutoff:
                        self.assertIsNone(source["value_usd"])
                        self.assertEqual(source["fact_id"], "")

    def test_missing_operating_line_is_not_summed_as_zero(self):
        case = demo_bridge_case()
        case["detail_case"]["companies"][0]["lines"][0]["values_millions"]["2024"] = None
        result = analyze_bridge(case)
        row = next(r for r in result["rows"] if (r["symbol"], r["period"]) == ("AAPL", "2024"))
        self.assertEqual(row["operating_cash_flow"], 118254_000_000)
        self.assertIsNone(row["adjustments"])
        self.assertIsNone(row["reconciliation_residual"])
        self.assertIsNone(row["delta_residual"])
        self.assertEqual(row["status"], "missing_input")
        self.assertEqual(crosscheck_bridge(result)["cells"], 144)

    def test_nonadjacent_fiscal_windows_do_not_create_a_yoy_bridge(self):
        case = demo_bridge_case()
        apple = case["anchor_case"]["companies"][0]
        apple["periods"][1]["start"] = "2023-10-02"
        for concept in apple["facts"]["facts"]["us-gaap"].values():
            concept["units"]["USD"][1]["start"] = "2023-10-02"
        result = analyze_bridge(case)
        row = next(r for r in result["rows"] if (r["symbol"], r["period"]) == ("AAPL", "2024"))
        self.assertIsNone(row["delta_cfo"])
        self.assertIsNone(row["delta_residual"])
        self.assertEqual(crosscheck_bridge(result)["cells"], 144)

    def test_invalid_values_groups_periods_and_filing_identity_are_rejected(self):
        mutations = [
            lambda c: c["lines"][0]["values_millions"].__setitem__("2024", -11445),
            lambda c: c["lines"][0]["values_millions"].__setitem__("2024", True),
            lambda c: c["lines"][0]["values_millions"].__setitem__("2024", 2**63),
            lambda c: c["lines"][0]["values_millions"].pop("2023"),
            lambda c: c["lines"][0].__setitem__("group", "unknown"),
            lambda c: c["lines"].append(copy.deepcopy(c["lines"][0])),
            lambda c: c["supplemental"].pop(0),
            lambda c: c["supplemental"][0].__setitem__("precision_millions", 100),
            lambda c: c["supplemental"][0]["values_millions"].__setitem__("2024", -1),
            lambda c: c.__setitem__("filed", "2024-11-02"),
            lambda c: c.__setitem__("source_url", "javascript:alert(1)"),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                case = demo_bridge_case()
                mutate(case["detail_case"]["companies"][0])
                with self.assertRaises(ContractError):
                    analyze_bridge(case)
        for duplicate in (True, False):
            case = demo_bridge_case()
            companies = case["detail_case"]["companies"]
            companies.append(copy.deepcopy(companies[0])) if duplicate else companies.pop()
            with self.assertRaisesRegex(ContractError, "coverage"):
                analyze_bridge(case)

    def test_precision_and_fact_identity_survive_cutoff_change(self):
        earlier = analyze_bridge(demo_bridge_case(), "2025-02-04")
        later = analyze_bridge(demo_bridge_case())
        prior = {(s["symbol"], s["period"], s["line_id"]): s for s in earlier["sources"]}
        for source in later["sources"]:
            if source["symbol"] != "GOOGL":
                self.assertEqual(
                    source["fact_id"], prior[(source["symbol"], source["period"], source["line_id"])]["fact_id"]
                )
            if source["symbol"] == "MSFT" and source["line_id"] == "cash_taxes":
                self.assertEqual(source["precision_usd"], 100_000_000)

    def test_bilingual_reports_embed_the_same_five_downloads(self):
        chinese = build_bridge(demo_bridge_case())
        english = build_bridge(demo_bridge_case(), language="en")
        for name in ("case.json", "bridge.csv", "sources.csv", "bridge.sql"):
            self.assertEqual(chinese[name], english[name])
        self.assertEqual(read_json(chinese["analysis.json"])["rows"], read_json(english["analysis.json"])["rows"])
        for packet, lang in ((chinese, "zh-CN"), (english, "en")):
            page = packet["index.html"].decode("utf-8")
            self.assertIn(f'lang="{lang}"', page)
            self.assertIn("≈23.4", page)
            self.assertIn("4.939", page)
            self.assertNotIn("\ufffd", page)
            self.assertNotIn("<script", page)
            self.assertNotIn("@@", page)
            embedded = re.findall(r'<a download="([^"]+)" href="data:[^,]+,([A-Za-z0-9+/=]+)">', page)
            self.assertEqual(len(embedded), 5)
            for filename, encoded in embedded:
                self.assertEqual(base64.b64decode(encoded), packet[filename])

    def test_source_labels_are_html_escaped_and_csv_formula_safe(self):
        case = demo_bridge_case()
        case["detail_case"]["companies"][0]["lines"][0]["zh"] = '<svg onload="x">'
        case["detail_case"]["companies"][0]["lines"][0]["label"] = "=1+1"
        packet = build_bridge(case)
        page = packet["index.html"].decode()
        self.assertIn("&lt;svg onload=&quot;x&quot;&gt;", page)
        self.assertNotIn("<svg", page)
        self.assertIn("text: =1+1", packet["sources.csv"].decode())

    def test_every_saved_file_and_file_set_is_replayed(self):
        for filename in build_bridge(demo_bridge_case()):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as root:
                target = Path(root) / "bridge"
                write_bridge(demo_bridge_case(), target)
                self.assertTrue(verify_bridge(target)["verified"])
                path = target / filename
                path.write_bytes(path.read_bytes() + b" ")
                with self.assertRaises(ContractError):
                    verify_bridge(target)
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "bridge"
            write_bridge(demo_bridge_case(), target)
            (target / "unexpected.txt").write_text("unexpected")
            with self.assertRaisesRegex(ContractError, "file set"):
                verify_bridge(target)

    def test_invalid_build_does_not_create_or_overwrite_output(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "bridge"
            with self.assertRaises(ContractError):
                write_bridge(demo_bridge_case(), target, language="invalid")
            self.assertFalse(target.exists())
            bad = demo_bridge_case()
            bad["detail_case"]["companies"][0]["lines"][0]["values_millions"]["2024"] += 1
            with self.assertRaisesRegex(ContractError, "does not reconcile"):
                write_bridge(bad, target)
            self.assertFalse(target.exists())
            write_bridge(demo_bridge_case(), target)
            before = {p.name: p.read_bytes() for p in target.iterdir()}
            with self.assertRaisesRegex(ContractError, "empty directory"):
                write_bridge(demo_bridge_case(), target)
            self.assertEqual(before, {p.name: p.read_bytes() for p in target.iterdir()})

    def test_cli_builds_and_verifies_an_early_cutoff_and_utf8_path(self):
        with tempfile.TemporaryDirectory() as root, redirect_stdout(io.StringIO()) as output:
            target = Path(root) / "现金桥"
            self.assertEqual(main(["profit-bridge", "--as-of", "2025-02-04", "--out", str(target)]), 0)
            self.assertEqual(main(["verify-profit-bridge", str(target)]), 0)
            self.assertTrue(json.loads(output.getvalue().splitlines()[-1])["verified"])
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["profit-bridge", "--out", str(target)]), 2)


if __name__ == "__main__":
    unittest.main()
