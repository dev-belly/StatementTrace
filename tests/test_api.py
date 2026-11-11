"""HTTP contracts: provenance, exact numbers, immutable snapshots and strict filters."""

import contextlib
import importlib
import importlib.util
import io
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from statementtrace.cashflow import demo_case
from statementtrace.cli import main
from statementtrace.contracts import ContractError, canonical, digest, read_json
from statementtrace.warehouse import write_warehouse

HAS_API = all(importlib.util.find_spec(name) is not None for name in ("fastapi", "httpx", "polars", "duckdb"))


class ApiCommandTests(unittest.TestCase):
    def test_missing_api_extra_has_an_actionable_error(self):
        original_import = importlib.import_module

        def without_api(name, *args, **kwargs):
            if name == "statementtrace.api":
                raise ImportError("API extra is absent")
            return original_import(name, *args, **kwargs)

        stderr = io.StringIO()
        with patch("statementtrace.cli.importlib.import_module", side_effect=without_api):
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(main(["serve-warehouse", "unused-packet"]), 2)
        self.assertIn(".[warehouse,api]", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_bad_ports_are_rejected_before_starting_a_server(self):
        for value in ("0", "65536", "not-a-number"):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main(["serve-warehouse", "unused-packet", "--port", value])
                self.assertEqual(error.exception.code, 2)


@unittest.skipUnless(HAS_API, "install warehouse, api and dev extras for HTTP contract tests")
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        from statementtrace.api import create_app

        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.packet = Path(cls.temp.name) / "packet"
        write_warehouse(demo_case(), cls.packet)
        cls.client = TestClient(create_app(cls.packet))
        cls.addClassCleanup(cls.client.close)

    def client_for(self, root, case=None, cutoff=None):
        from fastapi.testclient import TestClient

        from statementtrace.api import create_app

        packet = Path(root) / "packet"
        write_warehouse(case or demo_case(), packet, cutoff)
        return TestClient(create_app(packet))

    def test_snapshot_quality_and_health_have_the_same_identity(self):
        health = self.client.get("/healthz")
        snapshot = self.client.get("/v1/snapshot").json()
        quality = self.client.get("/v1/quality").json()
        self.assertEqual(health.status_code, 200)
        identity = health.json()
        self.assertEqual(identity["as_of"], "2025-02-05")
        self.assertEqual(len(identity["snapshot_id"]), 64)
        self.assertEqual(health.headers["X-StatementTrace-Snapshot"], identity["snapshot_id"])
        self.assertEqual(snapshot["snapshot_id"], identity["snapshot_id"])
        self.assertEqual(snapshot["currency"], "USD")
        self.assertEqual((snapshot["source_rows"], snapshot["issuer_years"]), (24, 6))
        self.assertEqual(quality["snapshot"], identity)
        self.assertEqual(quality["python_duckdb"], {"rows": 6, "cells": 138})
        self.assertTrue(all(count == 0 for count in quality["violations"].values()))

    def test_cashflow_filter_returns_hand_calculated_amounts_and_exact_ratios(self):
        response = self.client.get("/v1/cashflow", params={"symbol": "GOOGL", "period": "2024"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        row = data["items"][0]
        self.assertEqual(row["amounts"]["free_cash_flow"], "72764000000")
        self.assertEqual(row["bridge"]["negative_delta_capex"], "-20284000000")
        self.assertEqual(row["bridge"]["bridge_residual"], "0")
        self.assertEqual(row["ratios"]["fcf_growth"], {"numerator": "3269", "denominator": "69495"})
        self.assertEqual((row["start"], row["end"], row["days"]), ("2024-01-01", "2024-12-31", 366))

    def test_source_filter_keeps_filing_identity_and_dates(self):
        data = self.client.get("/v1/facts", params={"symbol": "AAPL", "period": "2024", "metric": "capex"}).json()
        self.assertEqual(data["total"], 1)
        fact = data["items"][0]
        self.assertEqual(fact["value_usd"], "9447000000")
        self.assertEqual(fact["filed"], "2024-11-01")
        self.assertEqual(fact["accession"], "0000320193-24-000123")
        self.assertEqual(len(fact["fact_id"]), 64)
        self.assertTrue(fact["source_url"].startswith("https://www.sec.gov/Archives/edgar/"))

    def test_issuers_list_uses_the_saved_fiscal_labels(self):
        data = self.client.get("/v1/issuers").json()
        self.assertEqual([row["symbol"] for row in data], ["AAPL", "GOOGL", "MSFT"])
        self.assertTrue(all(row["periods"] == ["2023", "2024"] for row in data))

    def test_pagination_visits_each_fact_once_under_one_snapshot(self):
        offset, rows, identities, sizes = 0, [], set(), []
        while offset is not None:
            response = self.client.get("/v1/facts", params={"limit": 7, "offset": offset})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["total"], 24)
            identities.add(data["snapshot"]["snapshot_id"])
            self.assertEqual(response.headers["X-StatementTrace-Snapshot"], data["snapshot"]["snapshot_id"])
            rows.extend(data["items"])
            sizes.append(len(data["items"]))
            offset = data["next_offset"]
        self.assertEqual(sizes, [7, 7, 7, 3])
        self.assertEqual(len({row["fact_id"] for row in rows}), 24)
        self.assertEqual(len(identities), 1)
        self.assertEqual(rows, self.client.get("/v1/facts").json()["items"])

    def test_empty_results_preserve_total_and_do_not_invent_rows(self):
        for params, total in (({"offset": 1000}, 24), ({"symbol": "UNKNOWN"}, 0)):
            data = self.client.get("/v1/facts", params=params).json()
            self.assertEqual(data["total"], total)
            self.assertEqual(data["items"], [])
            self.assertIsNone(data["next_offset"])

    def test_invalid_and_unrecognized_filters_are_not_silently_ignored(self):
        for params in (
            {"limit": 0},
            {"limit": 501},
            {"offset": -1},
            {"limit": "1.5"},
            {"symbol": "aapl"},
            {"as_of": "2024-01-01"},
            {"sql": "select 1"},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.client.get("/v1/cashflow", params=params).status_code, 422)
        self.assertEqual(self.client.get("/v1/facts", params={"metric": "unknown"}).status_code, 422)
        self.assertEqual(self.client.get("/v1/cashflow", params={"metric": "capex"}).status_code, 422)

    def test_duplicate_scalar_filters_are_rejected(self):
        response = self.client.get("/v1/cashflow?symbol=AAPL&symbol=GOOGL")
        self.assertEqual(response.status_code, 422)
        self.assertIn("Duplicate", response.json()["detail"][0]["msg"])
        self.assertIn("X-StatementTrace-Snapshot", response.headers)

    def test_metadata_routes_also_reject_unsupported_cutoff_parameters(self):
        for endpoint in ("/healthz", "/v1/snapshot", "/v1/quality", "/v1/issuers"):
            with self.subTest(endpoint=endpoint):
                response = self.client.get(endpoint, params={"as_of": "1900-01-01"})
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"][0]["type"], "extra_forbidden")

    def test_write_methods_are_unavailable_and_packet_bytes_are_preserved(self):
        before = {path.name: digest(path.read_bytes()) for path in self.packet.iterdir()}
        for method, endpoint in (("POST", "/v1/cashflow"), ("DELETE", "/v1/facts"), ("PUT", "/v1/snapshot")):
            self.assertEqual(self.client.request(method, endpoint, json={"value": 1}).status_code, 405)
        self.assertEqual(before, {path.name: digest(path.read_bytes()) for path in self.packet.iterdir()})

    def test_earlier_cutoff_retains_missing_slots_and_apps_are_independent(self):
        with tempfile.TemporaryDirectory() as root, self.client_for(root, cutoff="2025-02-04") as early:
            old = early.get("/v1/cashflow", params={"symbol": "GOOGL", "period": "2024"}).json()
            row = old["items"][0]
            self.assertEqual(row["status"], "missing_input")
            self.assertTrue(all(value is None for value in row["amounts"].values()))
            self.assertTrue(all(value is None for value in row["ratios"].values()))
            absent = early.get("/v1/facts", params={"symbol": "GOOGL"}).json()["items"]
            self.assertEqual(len(absent), 8)
            self.assertTrue(
                all(row["value_usd"] is None and row["filed"] is None and row["fact_id"] is None for row in absent)
            )
            current = self.client.get("/v1/cashflow", params={"symbol": "GOOGL", "period": "2024"}).json()
            self.assertEqual(current["items"][0]["amounts"]["free_cash_flow"], "72764000000")
            self.assertNotEqual(old["snapshot"]["snapshot_id"], current["snapshot"]["snapshot_id"])

    def test_zero_and_undefined_ratio_have_different_http_representations(self):
        case = demo_case()
        case["companies"][0]["facts"]["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"][1]["val"] = 0
        with tempfile.TemporaryDirectory() as root, self.client_for(root, case=case) as client:
            row = client.get("/v1/cashflow", params={"symbol": "AAPL", "period": "2024"}).json()["items"][0]
            self.assertEqual(row["amounts"]["net_income"], "0")
            self.assertEqual(row["ratios"]["net_margin"], {"numerator": "0", "denominator": "1"})
            self.assertIsNone(row["ratios"]["cash_conversion"])

    def test_large_integers_do_not_cross_the_json_number_boundary(self):
        case = demo_case()
        concepts = case["companies"][0]["facts"]["facts"]["us-gaap"]
        for name, value in {
            "RevenueFromContractWithCustomerExcludingAssessedTax": 2**53 + 1,
            "NetIncomeLoss": -(2**63),
            "NetCashProvidedByUsedInOperatingActivities": 2**63 - 1,
        }.items():
            concepts[name]["units"]["USD"][1]["val"] = value
        with tempfile.TemporaryDirectory() as root, self.client_for(root, case=case) as client:
            row = client.get("/v1/cashflow", params={"symbol": "AAPL", "period": "2024"}).json()["items"][0]
            self.assertEqual(row["amounts"]["revenue"], "9007199254740993")
            self.assertEqual(row["amounts"]["cfo_minus_profit"], "18446744073709551615")
            facts = client.get("/v1/facts", params={"symbol": "AAPL", "period": "2024", "metric": "net_income"}).json()
            self.assertEqual(facts["items"][0]["value_usd"], "-9223372036854775808")

    def test_exact_period_labels_round_trip_through_query_parameters(self):
        case = demo_case()
        label = "=FY'2024 / 财年\n"
        case["companies"][0]["periods"][1]["label"] = label
        with tempfile.TemporaryDirectory() as root, self.client_for(root, case=case) as client:
            data = client.get("/v1/cashflow", params={"symbol": "AAPL", "period": label}).json()
            self.assertEqual(data["total"], 1)
            self.assertEqual(data["items"][0]["period"], label)

    def test_captured_app_does_not_read_changing_packet_files_on_requests(self):
        from fastapi.testclient import TestClient

        from statementtrace.api import create_app

        with tempfile.TemporaryDirectory() as root:
            packet = Path(root) / "captured"
            shutil.copytree(self.packet, packet)
            with TestClient(create_app(packet)) as client:
                before = client.get("/v1/cashflow").json()
                shutil.rmtree(packet)
                self.assertEqual(client.get("/v1/cashflow").json(), before)
                self.assertEqual(client.get("/v1/facts").json()["total"], 24)

    def test_rehashed_tampering_is_refused_before_application_creation(self):
        from statementtrace.api import create_app

        with tempfile.TemporaryDirectory() as root:
            packet = Path(root) / "changed"
            shutil.copytree(self.packet, packet)
            path = packet / "analysis.json"
            analysis = read_json(path.read_bytes())
            analysis["rows"][0]["free_cash_flow"] += 1
            path.write_bytes(canonical(analysis))
            manifest_path = packet / "manifest.json"
            manifest = read_json(manifest_path.read_bytes())
            manifest["sha256"]["analysis.json"] = digest(path.read_bytes())
            manifest_path.write_bytes(canonical(manifest))
            with self.assertRaisesRegex(ContractError, "replay differs"):
                create_app(packet)

    def test_openapi_describes_exact_money_and_read_only_routes(self):
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        field = schema["components"]["schemas"]["Amounts"]["properties"]["free_cash_flow"]
        self.assertEqual({item["type"] for item in field["anyOf"]}, {"string", "null"})
        for path, methods in schema["paths"].items():
            self.assertEqual(set(methods), {"get"}, path)
        self.assertEqual(self.client.get("/docs").status_code, 200)

    def test_concurrent_requests_share_the_same_snapshot_without_state_changes(self):
        def query(offset):
            data = self.client.get("/v1/facts", params={"offset": offset, "limit": 1}).json()
            return data["snapshot"]["snapshot_id"], data["items"][0]["fact_id"]

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(query, range(24)))
        self.assertEqual(len({snapshot for snapshot, _ in results}), 1)
        self.assertEqual(len({fact for _, fact in results}), 24)


if __name__ == "__main__":
    unittest.main()
