"""Untrusted period labels stay inert and numeric evidence stays numeric."""

import copy
import csv
import io
import tempfile
import unittest
from pathlib import Path

from statementtrace.cli import demo_inputs
from statementtrace.contracts import ContractError, canonical, digest, read_json
from statementtrace.report import FILES, build, verify, write_report


class SpreadsheetExportTests(unittest.TestCase):
    def setUp(self):
        self.data, self.request = demo_inputs()

    def report(self, label):
        request = copy.deepcopy(self.request)
        request["periods"][0]["label"] = label
        return build(self.data, request)

    def rows(self, raw):
        return list(csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True))

    def test_formula_control_and_locale_prefixes_are_text_in_every_export(self):
        for label in (
            "=1+1",
            "+1+1",
            "-2023",
            "@SUM(1,2)",
            " \t=1+1",
            "\tFY2023",
            "\rFY2023",
            "\nFY2023",
            "\x00=1+1",
            "\ufeff=1+1",
            "＝1+1",
            "＋1+1",
            "－2023",
            "＠SUM(1,2)",
        ):
            files = self.report(label)
            for name in ("selected_facts.csv", "metrics.csv", "lineage.csv", "decisions.csv"):
                rows = self.rows(files[name])
                labels = {row["period"] for row in rows}
                with self.subTest(label=label, name=name):
                    self.assertIn("text: " + label, labels)
                    self.assertNotIn(label, labels)
                    self.assertTrue(all(None not in row and None not in row.values() for row in rows))
            self.assertEqual(read_json(files["request.json"])["periods"][0]["label"], label)
            self.assertEqual(read_json(files["analysis.json"])["panels"][0]["period"]["label"], label)

    def test_marker_cannot_make_distinct_labels_collide(self):
        request = copy.deepcopy(self.request)
        labels = ["=1+1", "text: =1+1"]
        for period, label in zip(request["periods"], labels, strict=True):
            period["label"] = label
        rows = self.rows(build(self.data, request)["metrics.csv"])
        self.assertEqual({row["period"] for row in rows}, {"text: " + label for label in labels})

    def test_commas_quotes_and_embedded_carriage_returns_round_trip(self):
        baseline = build(self.data, self.request)
        for label in ('FY, "2023"', "FY\r2023", "FY\r\n2023", "FY\n2023", " Annual "):
            files = self.report(label)
            for name in ("selected_facts.csv", "metrics.csv", "lineage.csv", "decisions.csv"):
                rows = self.rows(files[name])
                with self.subTest(label=label, name=name):
                    self.assertEqual(len(rows), len(self.rows(baseline[name])))
                    self.assertEqual(rows[0]["period"], label)
                    self.assertTrue(all(None not in row and None not in row.values() for row in rows))

    def test_negative_income_ratios_and_exact_amounts_are_not_text_prefixed(self):
        rows = self.data["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"]
        rows[0]["val"] = -93736000000
        files = self.report("=1+1")
        selected = self.rows(files["selected_facts.csv"])
        self.assertIn("-93736000000", [row["value_usd"] for row in selected])
        metrics = self.rows(files["metrics.csv"])
        negative = [row for row in metrics if row["metric"] == "net_margin" and row["display"].startswith("-")]
        self.assertTrue(negative)
        self.assertTrue(all(not row["exact"].startswith("text:") for row in negative))
        self.assertTrue(all(not row["display"].startswith("text:") for row in negative))

    def test_marked_report_verifies_and_rehashed_removed_marker_fails(self):
        request = copy.deepcopy(self.request)
        request["periods"][0]["label"] = "=1+1"
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "report"
            write_report(self.data, request, target)
            self.assertTrue(verify(target)["verified"])
            path = target / "metrics.csv"
            path.write_bytes(path.read_bytes().replace(b"text: =1+1", b"=1+1"))
            (target / "manifest.json").write_bytes(
                canonical(
                    {
                        "schema_version": 1,
                        "files": {name: digest((target / name).read_bytes()) for name in sorted(FILES)},
                    }
                )
            )
            with self.assertRaisesRegex(ContractError, "Semantic replay"):
                verify(target)


if __name__ == "__main__":
    unittest.main()
