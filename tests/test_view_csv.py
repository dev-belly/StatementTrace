"""A panel download must carry exactly its saved rows, including missing values."""

import base64
import copy
import csv
import io
import json
import re
import unittest
from fractions import Fraction
from html.parser import HTMLParser

from statementtrace.cli import demo_inputs
from statementtrace.report import build

FIELDS = ["as_of", "period", "metric", "formula", "unit", "status", "exact", "display", "missing"]
FACT_FIELDS = [
    "as_of",
    "period",
    "metric",
    "status",
    "value_usd",
    "start",
    "end",
    "filed",
    "tag",
    "accession",
    "fact_id",
    "source_url",
]
PREFIX = "data:text/csv;charset=utf-8;base64,"


class PanelDownloads(HTMLParser):
    def __init__(self, raw):
        super().__init__()
        self.view = None
        self.downloads = []
        self.feed(raw.decode("utf-8"))

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "section":
            self.view = (attrs["data-cutoff"], json.loads(attrs["data-period"]))
        elif tag == "a" and {"view-csv", "view-facts-csv"} & set(attrs.get("class", "").split()):
            self.downloads.append((self.view, attrs))

    def handle_endtag(self, tag):
        if tag == "section":
            self.view = None


def csv_rows(raw):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True)
    return reader.fieldnames, list(reader)


class ViewCSVTests(unittest.TestCase):
    def setUp(self):
        self.data, self.request = demo_inputs()

    def downloads(self, files, kind="metrics"):
        result = []
        for view, attrs in PanelDownloads(files["index.html"]).downloads:
            if ("view-csv" if kind == "metrics" else "view-facts-csv") not in attrs["class"].split():
                continue
            self.assertTrue(attrs["href"].startswith(PREFIX))
            raw = base64.b64decode(attrs["href"][len(PREFIX) :], validate=True)
            fields, rows = csv_rows(raw)
            self.assertEqual(fields, FIELDS if kind == "metrics" else FACT_FIELDS)
            self.assertEqual(len(rows), 9 if kind == "metrics" else 11)
            self.assertRegex(
                attrs["download"],
                rf"^statementtrace-{kind}-{view[0]}-[A-Za-z0-9-]+-[0-9a-f]{{16}}\.csv$",
            )
            self.assertLess(len(attrs["download"]), 120)
            self.assertTrue(all(row["as_of"] == view[0] for row in rows))
            self.assertTrue(all(None not in row and None not in row.values() for row in rows))
            result.append((view, rows))
        return result

    def test_every_panel_download_matches_its_slice_of_the_full_metrics_export(self):
        files = build(self.data, self.request)
        downloads = self.downloads(files)
        self.assertEqual(len(downloads), 6)
        self.assertEqual(len({view for view, _ in downloads}), 6)
        _, all_rows = csv_rows(files["metrics.csv"])
        for (cutoff, period), rows in downloads:
            expected = [row for row in all_rows if row["as_of"] == cutoff and row["period"] == period]
            self.assertEqual(rows, expected)
        self.assertEqual([row for _, rows in downloads for row in rows], all_rows)

    def test_before_filing_is_missing_and_after_filing_keeps_hand_checked_exact_values(self):
        views = dict(self.downloads(build(self.data, self.request)))
        before = views["2024-10-31", "2024"]
        self.assertTrue(all(row["status"] == "missing_input" for row in before))
        self.assertTrue(all(row["exact"] == row["display"] == "" and row["missing"] for row in before))
        after = {row["metric"]: row for row in views["2024-11-01", "2024"]}
        fcf = after["free_cash_flow"]
        self.assertEqual((fcf["exact"], fcf["unit"], fcf["status"]), ("108807000000/1", "USD", "ok"))
        self.assertEqual(fcf["formula"], "operating_cash_flow - capex")
        self.assertEqual(Fraction(after["net_margin"]["exact"]), Fraction(93736, 391035))

    def test_selected_facts_match_the_full_export_with_original_columns_and_missing_rows(self):
        files = build(self.data, self.request)
        downloads = self.downloads(files, "facts")
        self.assertEqual(len(downloads), 6)
        fields, all_rows = csv_rows(files["selected_facts.csv"])
        self.assertEqual(fields, FACT_FIELDS)
        for (cutoff, period), rows in downloads:
            self.assertEqual(rows, [row for row in all_rows if row["as_of"] == cutoff and row["period"] == period])
        self.assertEqual([row for _, rows in downloads for row in rows], all_rows)
        views = dict(downloads)
        before = views["2024-10-31", "2024"]
        self.assertTrue(all(row["status"] == "missing" for row in before))
        self.assertTrue(all(row[field] == "" for row in before for field in FACT_FIELDS[4:]))
        after = {row["metric"]: row for row in views["2024-11-01", "2024"]}
        revenue = after["revenue"]
        self.assertEqual(
            [revenue[field] for field in ("value_usd", "start", "end", "filed", "tag", "accession")],
            [
                "391035000000",
                "2023-10-01",
                "2024-09-28",
                "2024-11-01",
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "0000320193-24-000123",
            ],
        )
        self.assertEqual(revenue["fact_id"], "7c06142e9003b63b065bde9104c5e5547b4075f5aeece8a3ae03dcd2e0d1bbd5")
        self.assertEqual(
            revenue["source_url"],
            "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/0000320193-24-000123-index.htm",
        )

    def test_selected_facts_do_not_claim_the_growth_metrics_prior_period_input(self):
        files = build(self.data, self.request)
        facts = dict(self.downloads(files, "facts"))["2024-11-01", "2024"]
        _, lineage = csv_rows(files["lineage.csv"])
        prior = next(
            row
            for row in lineage
            if row["as_of"] == "2024-11-01" and row["period"] == "2024" and row["role"] == "previous_period_revenue"
        )
        self.assertNotIn(prior["fact_id"], {row["fact_id"] for row in facts})
        self.assertIn("For the growth metric's prior-period input", files["index.html"].decode())
        self.assertIn("href='lineage.csv'>Full lineage</a>", files["index.html"].decode())

    def test_download_names_are_stable_safe_and_distinct_for_exact_period_identities(self):
        cases = [
            ["2023", "2024"],
            ["Annual", " Annual "],
            ["same\rlabel", "same\nlabel"],
            ["same\x00label", "same�label"],
            ["年报 🧾", "中文"],
            ["../CON:<bad>|?*\\name", "text: ../CON:<bad>|?*\\name"],
            ["x" * 1000, "x" * 999 + "y"],
        ]
        for labels in cases:
            with self.subTest(labels=labels):
                request = copy.deepcopy(self.request)
                for period, label in zip(request["periods"], labels, strict=True):
                    period["label"] = label
                files = build(self.data, request)
                self.downloads(files)
                self.downloads(files, "facts")
                names = [attrs["download"] for _, attrs in PanelDownloads(files["index.html"]).downloads]
                self.assertEqual(len(names), 12)
                self.assertEqual(len(set(names)), len(names))
                self.assertEqual(
                    names,
                    [
                        attrs["download"]
                        for _, attrs in PanelDownloads(build(self.data, request)["index.html"]).downloads
                    ],
                )
                self.assertTrue(all(re.fullmatch(r"[A-Za-z0-9.-]+", name) for name in names))

    def test_labels_round_trip_with_text_markers_and_negative_numbers_keep_their_values(self):
        cases = [
            (["=1+1", "text: =1+1"], ["text: =1+1", "text: text: =1+1"]),
            (['FY,\r\n"2023"', " Annual "], ['FY,\r\n"2023"', " Annual "]),
            (["\x00FY2023", "\tFY2024"], ["text: \x00FY2023", "text: \tFY2024"]),
            (["年报 🧾 +&%#?", 'FY "2024"'], ["年报 🧾 +&%#?", 'FY "2024"']),
            (["＝1+1", "＠SUM(1,2)"], ["text: ＝1+1", "text: ＠SUM(1,2)"]),
        ]
        for labels, exported in cases:
            with self.subTest(labels=labels):
                data, request = copy.deepcopy(self.data), copy.deepcopy(self.request)
                data["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"][0]["val"] = -93736000000
                for period, label in zip(request["periods"], labels, strict=True):
                    period["label"] = label
                files = build(data, request)
                for kind, full_export in (("metrics", "metrics.csv"), ("facts", "selected_facts.csv")):
                    downloads = self.downloads(files, kind)
                    _, all_rows = csv_rows(files[full_export])
                    self.assertEqual([row for _, rows in downloads for row in rows], all_rows)
                    for (_, identity), rows in downloads:
                        self.assertEqual({row["period"] for row in rows}, {exported[labels.index(identity)]})
                _, all_rows = csv_rows(files["metrics.csv"])
                negative = [row for row in all_rows if row["display"].startswith("-")]
                self.assertTrue(negative)
                self.assertTrue(all(not row["exact"].startswith("text:") for row in negative))
                _, all_facts = csv_rows(files["selected_facts.csv"])
                negative_facts = [row for row in all_facts if row["value_usd"].startswith("-")]
                self.assertTrue(negative_facts)
                self.assertTrue(all(not row["value_usd"].startswith("text:") for row in negative_facts))


if __name__ == "__main__":
    unittest.main()
