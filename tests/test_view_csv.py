"""A panel download must carry exactly its saved rows, including missing values."""

import base64
import copy
import csv
import io
import json
import unittest
from fractions import Fraction
from html.parser import HTMLParser

from statementtrace.cli import demo_inputs
from statementtrace.report import build

FIELDS = ["as_of", "period", "metric", "formula", "unit", "status", "exact", "display", "missing"]
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
        elif tag == "a" and "view-csv" in attrs.get("class", "").split():
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

    def downloads(self, files):
        result = []
        for view, attrs in PanelDownloads(files["index.html"]).downloads:
            self.assertTrue(attrs["href"].startswith(PREFIX))
            raw = base64.b64decode(attrs["href"][len(PREFIX) :], validate=True)
            fields, rows = csv_rows(raw)
            self.assertEqual(fields, FIELDS)
            self.assertEqual(len(rows), 9)
            self.assertEqual(attrs["download"], f"statementtrace-metrics-{view[0]}.csv")
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
                downloads = self.downloads(files)
                _, all_rows = csv_rows(files["metrics.csv"])
                self.assertEqual([row for _, rows in downloads for row in rows], all_rows)
                for (_, identity), rows in downloads:
                    self.assertEqual({row["period"] for row in rows}, {exported[labels.index(identity)]})
                negative = [row for row in all_rows if row["display"].startswith("-")]
                self.assertTrue(negative)
                self.assertTrue(all(not row["exact"].startswith("text:") for row in negative))


if __name__ == "__main__":
    unittest.main()
