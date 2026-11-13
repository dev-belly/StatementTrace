"""Presentation language must not change financial inputs or calculations."""

import base64
import copy
import re
import tempfile
import unittest
from pathlib import Path

from statementtrace.cashflow import build, demo_case, verify_comparison, write_comparison
from statementtrace.cli import main
from statementtrace.contracts import ContractError, read_json


class ChineseResearchTests(unittest.TestCase):
    def test_language_changes_presentation_but_not_financial_evidence(self):
        case = demo_case()
        before = copy.deepcopy(case)
        english, chinese = build(case), build(case, language="zh-CN")
        self.assertEqual(case, before)
        self.assertEqual(set(english), set(chinese))
        for name in ("case.json", "comparison.csv", "source_facts.csv", "comparison.sql"):
            self.assertEqual(english[name], chinese[name], name)
        en, zh = read_json(english["analysis.json"]), read_json(chinese["analysis.json"])
        self.assertEqual(zh.pop("language"), "zh-CN")
        self.assertEqual(en, zh)

    def test_chinese_is_real_utf8_text_with_exact_headline_values_and_downloads(self):
        packet = build(demo_case(), language="zh-CN")
        html = packet["index.html"].decode("utf-8")
        for text in (
            'lang="zh-CN"',
            '<meta charset="utf-8">',
            "利润增长，",
            "现金跟上了吗？",
            "经营现金流增量",
            "勾稽差额：0.000",
            "实际财年区间",
            "35.67%",
            "4.70%",
            "108.807",
            "2025-02-05",
        ):
            self.assertIn(text, html)
        self.assertNotIn("\ufffd", html)
        self.assertNotIn("<script", html)
        self.assertNotIn("https://fonts.", html)
        embedded = re.findall(r'href="data:[^"]+;base64,([A-Za-z0-9+/=]+)" download="([^"]+)"', html)
        self.assertEqual(len(embedded), 5)
        for raw, filename in embedded:
            self.assertEqual(base64.b64decode(raw), packet[filename])

    def test_earlier_cutoff_keeps_missing_values_in_chinese(self):
        packet = build(demo_case(), "2025-02-04", "zh-CN")
        html = packet["index.html"].decode("utf-8")
        self.assertIn("数据不可得", html)
        self.assertNotIn("35.67%", html)
        self.assertEqual(html.count("<article>"), 2)
        rows = read_json(packet["analysis.json"])["rows"]
        self.assertTrue(all(row["free_cash_flow"] is None for row in rows if row["symbol"] == "GOOGL"))

    def test_no_available_periods_has_a_chinese_explanation(self):
        html = build(demo_case(), "2024-07-29", "zh-CN")["index.html"].decode("utf-8")
        self.assertIn("没有相邻且数据可得的财年", html)
        self.assertNotIn("<article>", html)

    def test_custom_chinese_periods_are_html_escaped(self):
        case = demo_case()
        case["companies"][0]["periods"][1]["label"] = '<script>年报 & "2024"</script>'
        html = build(case, language="zh-CN")["index.html"].decode("utf-8")
        self.assertIn("&lt;script&gt;年报 &amp; &quot;2024&quot;&lt;/script&gt;", html)
        self.assertNotIn("<script>", html)

    def test_cli_generates_and_semantically_replays_a_chinese_directory(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "中文报告"
            self.assertEqual(main(["compare", "--language", "zh-CN", "--out", str(target)]), 0)
            self.assertTrue(verify_comparison(target)["verified"])
            before = {p.name: p.read_bytes() for p in target.iterdir()}
            self.assertEqual(main(["compare", "--language", "zh-CN", "--out", str(target)]), 2)
            self.assertEqual(before, {p.name: p.read_bytes() for p in target.iterdir()})
            page = target / "index.html"
            page.write_bytes(page.read_bytes().replace(b"35.67%", b"99.99%"))
            with self.assertRaisesRegex(ContractError, "Comparison replay differs: index.html"):
                verify_comparison(target)

    def test_unsupported_language_creates_no_output(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "report"
            for language in ("zh", "../en", "", None):
                with self.subTest(language=language), self.assertRaisesRegex(ContractError, "Report language"):
                    write_comparison(demo_case(), target, language=language)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
