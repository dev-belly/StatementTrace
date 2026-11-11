"""Exact columnar arithmetic, availability boundaries and adversarial packet replay."""

import contextlib
import importlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from statementtrace.cashflow import demo_case
from statementtrace.cli import main
from statementtrace.contracts import ContractError, canonical, digest, read_json
from statementtrace.warehouse import dependencies, verify_warehouse, write_warehouse

HAS_WAREHOUSE = all(importlib.util.find_spec(name) is not None for name in ("polars", "duckdb"))


class OptionalDependencyTests(unittest.TestCase):
    def test_missing_extra_has_an_actionable_cli_error(self):
        stderr = io.StringIO()
        original_import = importlib.import_module

        def without_warehouse(name, *args, **kwargs):
            if name in ("polars", "duckdb"):
                raise ImportError("not installed")
            return original_import(name, *args, **kwargs)

        with patch("statementtrace.warehouse.importlib.import_module", side_effect=without_warehouse):
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(main(["warehouse", "--out", "unused-output"]), 2)
        self.assertIn(".[warehouse]", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


@unittest.skipUnless(HAS_WAREHOUSE, "install the warehouse extra for Polars/DuckDB contracts")
class WarehouseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / "packet"
        self.case = demo_case()
        self.pl, self.duckdb = dependencies()

    def build(self, cutoff=None):
        return write_warehouse(self.case, self.target, cutoff)

    def saved(self, symbol="AAPL", period="2024"):
        rows = read_json((self.target / "analysis.json").read_bytes())["rows"]
        return next(row for row in rows if row["symbol"] == symbol and row["period"] == period)

    def set_amount(self, concept, value, index=1):
        self.case["companies"][0]["facts"]["facts"]["us-gaap"][concept]["units"]["USD"][index]["val"] = value

    def rehash(self, name):
        manifest_path = self.target / "manifest.json"
        manifest = read_json(manifest_path.read_bytes())
        manifest["sha256"][name] = digest((self.target / name).read_bytes())
        manifest_path.write_bytes(canonical(manifest))

    def test_actual_filing_arithmetic_and_column_types(self):
        result = self.build()
        self.assertEqual(result["source_rows"], 24)
        self.assertEqual(result["python_duckdb"], {"rows": 6, "cells": 138})
        self.assertTrue(verify_warehouse(self.target)["verified"])
        self.assertEqual(self.saved()["free_cash_flow"], 108807000000)
        self.assertEqual(self.saved("MSFT")["delta_fcf"], 14596000000)
        self.assertEqual(self.saved("GOOGL")["negative_delta_capex"], -20284000000)
        self.assertEqual(self.saved("GOOGL")["fcf_growth"], "3269/69495")
        self.assertEqual(self.saved("AAPL", "2023")["days"], 371)
        self.assertTrue(
            all(value == 0 for value in read_json((self.target / "quality.json").read_bytes())["violations"].values())
        )
        facts = self.pl.read_parquet(self.target / "source_facts.parquet")
        self.assertEqual(facts.schema["value_usd"], self.pl.Int64)
        self.assertEqual(facts.schema["filed"], self.pl.Date)
        self.assertEqual(facts["fact_id"].n_unique(), 24)
        with self.duckdb.connect(config={"threads": 2}) as db:
            db.read_parquet(str(self.target / "cashflow.parquet")).create_view("mart")
            self.assertEqual(
                db.execute("SELECT typeof(free_cash_flow) FROM mart LIMIT 1").fetchone()[0], "DECIMAL(38,0)"
            )

    def test_cutoff_before_alphabet_filing_keeps_missing_slots(self):
        self.build("2025-02-04")
        row = self.saved("GOOGL")
        self.assertEqual(row["status"], "missing_input")
        self.assertIsNone(row["free_cash_flow"])
        self.assertIsNone(row["fcf_growth"])
        facts = self.pl.read_parquet(self.target / "source_facts.parquet")
        absent = facts.filter(self.pl.col("symbol") == "GOOGL")
        self.assertEqual(absent.height, 8)
        self.assertEqual(absent["value_usd"].null_count(), 8)
        self.assertEqual(absent["filed"].null_count(), 8)
        self.assertTrue(verify_warehouse(self.target)["verified"])

    def test_all_missing_values_keep_their_numeric_and_date_schemas(self):
        self.build("2024-07-29")
        facts = self.pl.read_parquet(self.target / "source_facts.parquet")
        self.assertEqual(facts["value_usd"].null_count(), 24)
        self.assertEqual(facts.schema["value_usd"], self.pl.Int64)
        self.assertEqual(facts.schema["filed"], self.pl.Date)
        self.assertTrue(verify_warehouse(self.target)["verified"])

    def test_one_missing_input_does_not_erase_other_metrics(self):
        del self.case["companies"][0]["facts"]["facts"]["us-gaap"]["PaymentsToAcquirePropertyPlantAndEquipment"]
        self.build()
        row = self.saved()
        self.assertEqual(row["status"], "missing_input")
        self.assertIsNone(row["free_cash_flow"])
        self.assertIsNotNone(row["net_margin"])

    def test_zero_profit_is_zero_and_conversion_is_undefined(self):
        self.set_amount("NetIncomeLoss", 0)
        self.build()
        row = self.saved()
        self.assertEqual(row["net_income"], 0)
        self.assertEqual(row["net_margin"], "0/1")
        self.assertIsNone(row["cash_conversion"])
        self.assertEqual(row["free_cash_flow"], 108807000000)

    def test_nonadjacent_period_has_no_growth_or_bridge(self):
        company = self.case["companies"][0]
        company["periods"][1]["start"] = "2023-10-02"
        for concept in company["facts"]["facts"]["us-gaap"].values():
            concept["units"]["USD"][1]["start"] = "2023-10-02"
        self.build()
        self.assertIsNone(self.saved()["fcf_growth"])
        self.assertIsNone(self.saved()["bridge_residual"])

    def test_integer_beyond_float_precision_and_difference_beyond_int64(self):
        self.set_amount("NetIncomeLoss", -(2**63))
        self.set_amount("NetCashProvidedByUsedInOperatingActivities", 2**63 - 1)
        self.set_amount("PaymentsToAcquirePropertyPlantAndEquipment", 0)
        self.set_amount("RevenueFromContractWithCustomerExcludingAssessedTax", 2**53 + 1)
        self.build()
        row = self.saved()
        self.assertEqual(row["revenue"], 9007199254740993)
        self.assertEqual(row["free_cash_flow"], 9223372036854775807)
        self.assertEqual(row["cfo_minus_profit"], 18446744073709551615)
        self.assertTrue(verify_warehouse(self.target)["verified"])

    def test_period_labels_keep_exact_text(self):
        label = "=FY'2024 / 财年"
        self.case["companies"][0]["periods"][1]["label"] = label
        self.build()
        self.assertEqual(self.saved(period=label)["period"], label)
        self.assertTrue(verify_warehouse(self.target)["verified"])

    def test_changed_mart_is_rejected_even_after_rehashing(self):
        self.build()
        path = self.target / "cashflow.parquet"
        frame = self.pl.read_parquet(path)
        frame.with_columns((self.pl.col("free_cash_flow") + 1).alias("free_cash_flow")).write_parquet(path)
        self.rehash(path.name)
        with self.assertRaisesRegex(ContractError, "free_cash_flow"):
            verify_warehouse(self.target)

    def test_changed_source_identity_is_rejected_even_after_rehashing(self):
        self.build()
        path = self.target / "source_facts.parquet"
        frame = self.pl.read_parquet(path)
        frame.with_columns(self.pl.lit("wrong-accession").alias("accession")).write_parquet(path)
        self.rehash(path.name)
        with self.assertRaisesRegex(ContractError, "selected source facts differ"):
            verify_warehouse(self.target)

    def test_float_mart_cannot_replace_an_exact_decimal_mart(self):
        self.build()
        path = self.target / "cashflow.parquet"
        frame = self.pl.read_parquet(path)
        frame.with_columns(self.pl.col("free_cash_flow").cast(self.pl.Float64)).write_parquet(path)
        self.rehash(path.name)
        with self.assertRaisesRegex(ContractError, "exact DECIMAL"):
            verify_warehouse(self.target)

    def test_corrupt_parquet_has_a_contract_error(self):
        self.build()
        (self.target / "source_facts.parquet").write_bytes(b"not a parquet file")
        self.rehash("source_facts.parquet")
        with self.assertRaisesRegex(ContractError, "engine rejected"):
            verify_warehouse(self.target)

    def test_hash_change_and_unknown_file_are_rejected(self):
        self.build()
        path = self.target / "quality.json"
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        with self.assertRaisesRegex(ContractError, "hash differs"):
            verify_warehouse(self.target)
        path.write_bytes(original)
        (self.target / "extra.txt").write_text("extra", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "file set differs"):
            verify_warehouse(self.target)

    def test_nonempty_destination_and_failed_build_preserve_existing_files(self):
        self.target.mkdir()
        sentinel = self.target / "keep.txt"
        sentinel.write_bytes(b"existing research")
        with self.assertRaisesRegex(ContractError, "new or empty"):
            self.build()
        self.assertEqual(sentinel.read_bytes(), b"existing research")
        self.assertEqual(list(self.target.iterdir()), [sentinel])
        # A valid destination is published only after the SQL check succeeds.
        with patch("statementtrace.warehouse.sql_text", return_value="SELECT missing_column FROM source_facts"):
            with self.assertRaisesRegex(ContractError, "engine rejected"):
                write_warehouse(self.case, self.root / "failed")
        self.assertFalse((self.root / "failed").exists())
        self.assertFalse(list(self.root.glob(".statementtrace-*")))

    def test_symlink_member_is_rejected_without_following_it(self):
        self.build()
        path = self.target / "case.json"
        external = self.root / "external.json"
        external.write_bytes(path.read_bytes())
        path.unlink()
        try:
            path.symlink_to(external)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                self.skipTest("Windows symlink privilege is unavailable")
            raise
        with self.assertRaisesRegex(ContractError, "real file"):
            verify_warehouse(self.target)

    def test_cli_accepts_a_saved_case_and_empty_directory(self):
        self.target.mkdir()
        case_path = self.root / "case.json"
        case_path.write_bytes(canonical(self.case))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                main(["warehouse", "--case", str(case_path), "--as-of", "2025-02-04", "--out", str(self.target)]), 0
            )
            self.assertEqual(main(["verify-warehouse", str(self.target)]), 0)
        self.assertEqual(self.saved("GOOGL")["status"], "missing_input")


if __name__ == "__main__":
    unittest.main()
