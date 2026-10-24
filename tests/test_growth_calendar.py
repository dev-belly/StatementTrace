"""A gap in configured fiscal periods must not become reported annual growth."""

import tempfile
import unittest
from pathlib import Path

from statementtrace.cli import demo_inputs
from statementtrace.engine import analyze
from statementtrace.report import verify, write_report


def growth(panel):
    return next(metric for metric in panel["metrics"] if metric["metric"] == "revenue_growth")


class GrowthCalendarTests(unittest.TestCase):
    def test_one_day_gap_keeps_current_metrics_but_omits_the_growth_base(self):
        data, request = demo_inputs()
        old_start = request["periods"][1]["start"]
        request["periods"][1]["start"] = "2023-10-02"
        for concept in data["facts"]["us-gaap"].values():
            for rows in concept["units"].values():
                for row in rows:
                    if row.get("start") == old_start:
                        row["start"] = "2023-10-02"
        result = analyze(data, request)
        metric = growth(result["panels"][-1])
        self.assertEqual(metric["status"], "missing_input")
        self.assertEqual(metric["missing"], ["previous_period_revenue"])
        self.assertEqual(metric["exact"], "")
        self.assertEqual([item["role"] for item in metric["inputs"]], ["revenue"])
        self.assertEqual(result["panels"][-1]["facts"]["revenue"]["record"]["val"], 391035000000)
        other = next(item for item in result["panels"][-1]["metrics"] if item["metric"] == "net_margin")
        self.assertEqual(other["status"], "ok")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "gapped-report"
            write_report(data, request, path)
            self.assertTrue(verify(path)["verified"])

    def test_skipped_year_is_not_treated_as_the_immediately_previous_fiscal_year(self):
        data, request = demo_inputs()
        old_start, old_end = request["periods"][0]["start"], request["periods"][0]["end"]
        request["periods"][0].update(start="2021-09-25", end="2022-09-30", label="Earlier synthetic period")
        for concept in data["facts"]["us-gaap"].values():
            for rows in concept["units"].values():
                for row in rows:
                    if row["end"] == old_end:
                        row["end"] = "2022-09-30"
                        if row.get("start") == old_start:
                            row["start"] = "2021-09-25"
        panel = analyze(data, request)["panels"][-1]
        self.assertEqual(growth(panel)["missing"], ["previous_period_revenue"])
        self.assertEqual(growth(panel)["status"], "missing_input")

    def test_calendar_adjacency_uses_dates_including_53_week_years_not_labels(self):
        data, request = demo_inputs()
        request["periods"][0]["label"] = "Earlier"
        request["periods"][1]["label"] = "Later"
        panels = analyze(data, request)["panels"]
        self.assertEqual([panel["duration_days"] for panel in panels[-2:]], [371, 364])
        self.assertEqual(growth(panels[-1])["status"], "ok")
        self.assertEqual(growth(panels[-1])["exact"], "1550/76657")
