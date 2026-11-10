"""Financial expectations, source boundaries and the installed command surface."""

import copy
import csv
import io
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from statementtrace.cashflow import build, compare, demo_case, sql_crosscheck, verify_comparison, write_comparison
from statementtrace.cli import main
from statementtrace.contracts import ContractError, read_json


class CashflowStudyTests(unittest.TestCase):
    def setUp(self):
        self.case = demo_case()

    def row(self, result, symbol, period="2024"):
        return next(row for row in result["rows"] if row["symbol"] == symbol and row["period"] == period)

    def test_filed_table_amounts_and_cash_bridge(self):
        result = compare(self.case)
        # Hand arithmetic from the three filed cash-flow statements, in USD millions.
        expectations = {
            "AAPL": (108807, 7711, 1512, 9223),
            "MSFT": (74071, 30966, -16370, 14596),
            "GOOGL": (72764, 23553, -20284, 3269),
        }
        for symbol, (fcf, cfo_change, capex_effect, change) in expectations.items():
            with self.subTest(symbol=symbol):
                row = self.row(result, symbol)
                self.assertEqual(row["free_cash_flow"], fcf * 1000000)
                self.assertEqual(row["delta_cfo"], cfo_change * 1000000)
                self.assertEqual(row["negative_delta_capex"], capex_effect * 1000000)
                self.assertEqual(row["delta_fcf"], change * 1000000)
                self.assertEqual(row["bridge_residual"], 0)
        alphabet = self.row(result, "GOOGL")
        self.assertEqual(alphabet["net_income_growth"], Fraction(26323, 73795))
        self.assertEqual(alphabet["fcf_growth"], Fraction(3269, 69495))
        self.assertLess(alphabet["fcf_margin"], self.row(result, "GOOGL", "2023")["fcf_margin"])

    def test_sql_recomputes_all_six_rows_from_source_values(self):
        result = compare(self.case)
        checks = sql_crosscheck(result)
        self.assertEqual(checks, {"rows": 6, "cells": 108})
        # The independent calculation must notice a wrong Python result.
        self.row(result, "GOOGL")["free_cash_flow"] += 1000000
        with self.assertRaisesRegex(ContractError, "SQL differs"):
            sql_crosscheck(result)

    def test_alphabet_filing_cutoff_is_not_the_acceptance_date(self):
        early = compare(self.case, "2025-02-04")
        for year in ("2023", "2024"):
            row = self.row(early, "GOOGL", year)
            self.assertEqual(row["status"], "missing_input")
            self.assertIsNone(row["free_cash_flow"])
        self.assertEqual(self.row(early, "MSFT")["free_cash_flow"], 74071000000)
        self.assertEqual(sql_crosscheck(early)["rows"], 6)
        self.assertEqual(self.row(compare(self.case, "2025-02-05"), "GOOGL")["status"], "ok")

    def test_before_all_filings_is_missing_not_zero(self):
        result = compare(self.case, "2024-07-29")
        self.assertTrue(all(row["status"] == "missing_input" for row in result["rows"]))
        self.assertTrue(all(row["free_cash_flow"] is None for row in result["rows"]))
        sql_crosscheck(result)

    def test_actual_fiscal_windows_survive_comparison(self):
        result = compare(self.case)
        self.assertEqual(self.row(result, "AAPL", "2023")["days"], 371)
        self.assertEqual(self.row(result, "AAPL")["days"], 364)
        self.assertEqual(self.row(result, "MSFT")["end"], "2024-06-30")
        self.assertEqual(self.row(result, "GOOGL")["end"], "2024-12-31")

    def test_missing_capex_does_not_invent_fcf(self):
        del self.case["companies"][0]["facts"]["facts"]["us-gaap"]["PaymentsToAcquirePropertyPlantAndEquipment"]
        result = compare(self.case)
        row = self.row(result, "AAPL")
        self.assertIsNone(row["free_cash_flow"])
        self.assertIsNotNone(row["net_margin"])
        self.assertIsNone(row["delta_fcf"])
        sql_crosscheck(result)

    def test_zero_profit_preserves_cash_flow_and_has_no_conversion_ratio(self):
        self.case["companies"][0]["facts"]["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"][1]["val"] = 0
        result = compare(self.case)
        row = self.row(result, "AAPL")
        self.assertIsNone(row["cash_conversion"])
        self.assertEqual(row["free_cash_flow"], 108807000000)
        sql_crosscheck(result)

    def test_nonadjacent_periods_do_not_create_a_year_on_year_bridge(self):
        company = self.case["companies"][0]
        company["periods"][1]["start"] = "2023-10-02"
        for concept in company["facts"]["facts"]["us-gaap"].values():
            concept["units"]["USD"][1]["start"] = "2023-10-02"
        result = compare(self.case)
        row = self.row(result, "AAPL")
        self.assertIsNotNone(row["free_cash_flow"])
        self.assertIsNone(row["fcf_growth"])
        self.assertIsNone(row["bridge_residual"])
        sql_crosscheck(result)

    def test_capex_sign_is_explicit(self):
        self.case["companies"][0]["facts"]["facts"]["us-gaap"]["PaymentsToAcquirePropertyPlantAndEquipment"]["units"][
            "USD"
        ][1]["val"] *= -1
        with self.assertRaisesRegex(ContractError, "positive cash-outflow"):
            compare(self.case)

    def test_duplicate_symbols_do_not_blend_issuers(self):
        self.case["companies"].append(copy.deepcopy(self.case["companies"][0]))
        with self.assertRaisesRegex(ContractError, "unique"):
            compare(self.case)

    def test_exports_keep_24_selected_source_identities_and_exact_ratios(self):
        packet = build(self.case)
        facts = list(csv.DictReader(io.StringIO(packet["source_facts.csv"].decode())))
        self.assertEqual(len(facts), 24)
        self.assertEqual(len({row["fact_id"] for row in facts}), 24)
        self.assertTrue(all(row["filed"] <= row["as_of"] and row["value_usd"] for row in facts))
        analysis = read_json(packet["analysis.json"])
        row = self.row(analysis, "GOOGL")
        self.assertEqual(row["fcf_growth"], "3269/69495")
        html = packet["index.html"].decode()
        for name in packet:
            if name != "index.html":
                self.assertIn(name, html)
        self.assertNotIn("<script", html)

    def test_command_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "study"
            self.assertEqual(main(["compare", "--out", str(target)]), 0)
            self.assertTrue(verify_comparison(target)["verified"])
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            with self.assertRaisesRegex(ContractError, "new or empty"):
                write_comparison(self.case, target)
            self.assertEqual(before, {path.name: path.read_bytes() for path in target.iterdir()})

    def test_saved_amount_changes_fail_replay(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "study"
            write_comparison(self.case, target)
            csv_path = target / "comparison.csv"
            csv_path.write_bytes(csv_path.read_bytes().replace(b"108807000000", b"108808000000"))
            with self.assertRaisesRegex(ContractError, "Comparison replay differs"):
                verify_comparison(target)

    def test_alternate_cutoff_replays_its_own_missing_results(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "early"
            write_comparison(self.case, target, "2025-02-04")
            self.assertEqual(verify_comparison(target)["as_of"], "2025-02-04")


if __name__ == "__main__":
    unittest.main()
