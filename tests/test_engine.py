import copy
import random
import sqlite3
import unittest
from decimal import getcontext
from fractions import Fraction

from statementtrace.cli import demo_inputs
from statementtrace.contracts import ContractError, display, read_json
from statementtrace.engine import METRICS, analyze, choose, normalize, validate_request


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.data, self.request = demo_inputs()
        self.p23, self.p24 = self.request["periods"]

    def rows(self, tag="RevenueFromContractWithCustomerExcludingAssessedTax"):
        return self.data["facts"]["us-gaap"][tag]["units"]["USD"]

    def select(self, cutoff="2024-11-01", metric="revenue", period=None):
        return choose(normalize(self.data), metric, period or self.p23, cutoff)[0]

    def test_real_fixture_counts_and_scaling(self):
        self.assertEqual(len(normalize(self.data)), 33)
        self.assertEqual(self.select(period=self.p24).value, 391035000000)

    def test_no_future_filing(self):
        self.assertIsNone(self.select("2024-10-31", period=self.p24))
        self.assertEqual(self.select("2024-11-01", period=self.p24).record["filed"], "2024-11-01")

    def test_comparative_period_is_not_filing_fy(self):
        fact = self.select()
        self.assertEqual(fact.record["fy"], 2024)
        self.assertEqual(fact.record["end"], "2023-09-30")
        self.assertEqual(fact.value, 383285000000)

    def test_53_week_period_and_wrong_quarter(self):
        quarter = copy.deepcopy(self.rows()[0])
        quarter.update(start="2023-07-02", val=999, filed="2024-11-01")
        self.rows().append(quarter)
        result = analyze(self.data, self.request)
        self.assertEqual(result["panels"][0]["duration_days"], 371)
        self.assertEqual(result["panels"][1]["duration_days"], 364)
        self.assertEqual(self.select().value, 383285000000)

    def test_wrong_currency_is_not_converted(self):
        concept = self.data["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]
        concept["units"]["EUR"] = [{**self.rows()[1], "val": 17}]
        self.assertEqual(self.select().value, 383285000000)
        reasons = choose(normalize(self.data), "revenue", self.p23, "2024-11-01")[1]
        self.assertIn("wrong_unit", reasons.values())

    def test_quarterly_form_is_excluded(self):
        row = {**self.rows()[1], "form": "10-Q", "val": 17}
        self.rows().append(row)
        self.assertEqual(self.select().value, 383285000000)

    def test_synthetic_amendment_is_selected_only_when_available(self):
        row = {**self.rows()[1], "val": 123, "filed": "2024-11-02", "accn": "0000320193-24-999999", "form": "10-K/A"}
        self.rows().append(row)
        self.assertEqual(self.select().value, 383285000000)
        self.assertEqual(self.select("2024-11-02").value, 123)

    def test_conflicting_same_day_filing_fails(self):
        self.rows().append({**self.rows()[1], "val": 123, "accn": "0000320193-24-999999"})
        with self.assertRaisesRegex(ContractError, "Conflicting"):
            self.select()

    def test_alias_conflict_fails(self):
        self.data["facts"]["us-gaap"]["Revenues"] = {"units": {"USD": [{**self.rows()[1], "val": 123}]}}
        with self.assertRaisesRegex(ContractError, "Conflicting"):
            self.select()

    def test_duplicates_and_input_order_are_idempotent(self):
        expected = analyze(self.data, self.request)
        self.rows().append(copy.deepcopy(self.rows()[0]))
        random.Random(42).shuffle(self.rows())
        self.assertEqual(analyze(self.data, self.request), expected)

    def test_sql_window_oracle_matches_selection(self):
        # Independent SQL query uses exact dates and latest availability; no engine ranking call.
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE facts(metric, tag, unit, value, start, end, filed, form, accn)")
        for fact in normalize(self.data):
            row = fact.record
            db.execute(
                "INSERT INTO facts VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    fact.metric,
                    fact.tag,
                    fact.unit,
                    row["val"],
                    row.get("start"),
                    row["end"],
                    row["filed"],
                    row["form"],
                    row["accn"],
                ),
            )
        for cutoff in self.request["as_of_dates"]:
            for period in self.request["periods"]:
                for metric, (kind, _) in METRICS.items():
                    sql = """SELECT value, accn FROM facts WHERE metric=? AND unit='USD'
                    AND form IN ('10-K','10-K/A') AND end=? AND filed<=?
                    AND ((?='instant' AND start IS NULL) OR (?='duration' AND start=?))
                    ORDER BY filed DESC, accn ASC LIMIT 1"""
                    result = db.execute(sql, (metric, period["end"], cutoff, kind, kind, period["start"])).fetchone()
                    fact = self.select(cutoff, metric, period)
                    self.assertEqual(result, (fact.value, fact.record["accn"]) if fact else None)
        db.close()

    def test_invalid_integer_values(self):
        for value in [True, 1.5, "391035", None]:
            with self.subTest(value=value):
                self.rows()[0]["val"] = value
                with self.assertRaises(ContractError):
                    normalize(self.data)

    def test_invalid_dates_and_accession(self):
        for key, value in [
            ("filed", "2023-02-30"),
            ("end", "2029-01-01"),
            ("start", "2024-01-01"),
            ("accn", "../escape"),
        ]:
            with self.subTest(key=key):
                data, _ = demo_inputs()
                row = data["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"][0]
                row[key] = value
                with self.assertRaises(ContractError):
                    normalize(data)

    def test_request_validation(self):
        for request in [
            {},
            {"periods": [], "as_of_dates": ["2024-11-01"]},
            {**self.request, "as_of_dates": ["2024-11-01", "2023-11-03"]},
            {**self.request, "periods": [self.p23, self.p23]},
            {**self.request, "as_of_dates": [True]},
        ]:
            with self.subTest(request=request), self.assertRaises(ContractError):
                validate_request(request)


class RatioTests(unittest.TestCase):
    def setUp(self):
        self.data, self.request = demo_inputs()

    def final_metrics(self):
        return {m["metric"]: m for m in analyze(self.data, self.request)["panels"][-1]["metrics"]}

    def test_exact_ratio_fcf_growth_and_accounting_identity(self):
        metrics = self.final_metrics()
        self.assertEqual(Fraction(metrics["net_margin"]["exact"]), Fraction(93736, 391035))
        self.assertEqual(Fraction(metrics["free_cash_flow"]["exact"]), 108807000000)
        self.assertEqual(Fraction(metrics["revenue_growth"]["exact"]), Fraction(7750, 383285))
        self.assertEqual(metrics["balance_residual"]["exact"], "0/1")

    def test_missing_does_not_turn_into_zero(self):
        del self.data["facts"]["us-gaap"]["LiabilitiesCurrent"]
        metric = self.final_metrics()["current_ratio"]
        self.assertEqual(metric["status"], "missing_input")
        self.assertEqual(metric["exact"], "")
        self.assertEqual(metric["missing"], ["current_liabilities"])

    def test_zero_denominator_is_explicit(self):
        rows = self.data["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"]
        rows[-1]["val"] = 0
        self.assertEqual(self.final_metrics()["cash_conversion"]["status"], "zero_denominator")

    def test_negative_income_is_valid(self):
        self.data["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"][-1]["val"] = -10
        self.assertLess(Fraction(self.final_metrics()["net_margin"]["exact"]), 0)

    def test_lineage_references_selected_inputs(self):
        panel = analyze(self.data, self.request)["panels"][-1]
        metric = next(m for m in panel["metrics"] if m["metric"] == "net_margin")
        self.assertEqual(
            metric["inputs"],
            [
                {"role": "net_income", "fact_id": panel["facts"]["net_income"]["fact_id"]},
                {"role": "revenue", "fact_id": panel["facts"]["revenue"]["fact_id"]},
            ],
        )

    def test_decimal_context_does_not_change_output(self):
        original = getcontext().copy()
        try:
            getcontext().prec = 3
            getcontext().rounding = "ROUND_DOWN"
            self.assertEqual(display(Fraction(2, 3)), "0.666667")
            self.assertEqual(getcontext().prec, 3)
        finally:
            getcontext().prec = original.prec
            getcontext().rounding = original.rounding

    def test_strict_json_rejects_duplicate_and_nonfinite(self):
        for raw in ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}']:
            with self.subTest(raw=raw), self.assertRaises(ContractError):
                read_json(raw)


if __name__ == "__main__":
    unittest.main()
