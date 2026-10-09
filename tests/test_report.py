import contextlib
import io
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from statementtrace.cli import demo_inputs, main
from statementtrace.contracts import ContractError, canonical, digest, read_json
from statementtrace.report import FILES, build, verify, write_report


class ReportSelectors(HTMLParser):
    """Read selector values using the HTML option value fallback rule."""

    def __init__(self):
        super().__init__()
        self.select = None
        self.option = None
        self.values = {}
        self.panels = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "select":
            self.select = attrs["id"]
            self.values[self.select] = []
        elif tag == "option":
            self.option = (attrs, [])
        elif tag == "section":
            self.panels.add((attrs["data-cutoff"], attrs["data-period"]))

    def handle_data(self, data):
        if self.option is not None:
            self.option[1].append(data)

    def handle_endtag(self, tag):
        if tag == "option":
            attrs, text = self.option
            fallback = re.sub(r"[ \t\n\r\f]+", " ", "".join(text)).strip(" \t\n\r\f")
            self.values[self.select].append(attrs.get("value", fallback))
            self.option = None
        elif tag == "select":
            self.select = None


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.data, self.request = demo_inputs()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name) / "demo"
        write_report(self.data, self.request, self.target)

    def rehash(self):
        (self.target / "manifest.json").write_bytes(
            canonical(
                {
                    "schema_version": 1,
                    "files": {name: digest((self.target / name).read_bytes()) for name in sorted(FILES)},
                }
            )
        )

    def test_verify_and_byte_reproducibility(self):
        self.assertEqual(verify(self.target), {"verified": True, "files": 9, "panels": 6})
        for name, raw in build(self.data, self.request).items():
            self.assertEqual((self.target / name).read_bytes(), raw)

    def test_tampered_metric_with_updated_hash_is_rejected(self):
        path = self.target / "metrics.csv"
        path.write_text(path.read_text().replace("0.239712", "9.999999"))
        # Do not depend on a specific rounded value occurring.
        path.write_text(path.read_text() + "fabricated,row\n")
        self.rehash()
        with self.assertRaisesRegex(ContractError, "Semantic replay"):
            verify(self.target)

    def test_tampered_source_lineage_with_updated_hash_is_rejected(self):
        path = self.target / "lineage.csv"
        path.write_text(path.read_text().replace("net_income", "fabricated_income"))
        self.rehash()
        with self.assertRaisesRegex(ContractError, "Semantic replay"):
            verify(self.target)

    def test_modified_html_with_updated_hash_is_rejected(self):
        path = self.target / "index.html"
        path.write_text(path.read_text() + "<p>Fake conclusion</p>")
        self.rehash()
        with self.assertRaisesRegex(ContractError, "Semantic replay"):
            verify(self.target)

    def test_unhashed_modification_is_rejected(self):
        (self.target / "analysis.json").write_text("{}")
        with self.assertRaisesRegex(ContractError, "manifest"):
            verify(self.target)

    def test_extra_member_and_symlink_are_rejected(self):
        extra = self.target / "extra.txt"
        extra.write_text("extra")
        with self.assertRaises(ContractError):
            verify(self.target)
        extra.unlink()
        member = self.target / "metrics.csv"
        member.unlink()
        member.symlink_to(self.target / "selected_facts.csv")
        with self.assertRaisesRegex(ContractError, "symlinks"):
            verify(self.target)

    def test_nonempty_output_is_not_overwritten(self):
        with self.assertRaisesRegex(ContractError, "empty"):
            write_report(self.data, self.request, self.target)

    def test_cli_verify_and_fail_closed(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(main(["verify", str(self.target)]), 0)
            self.assertTrue(read_json(stdout.getvalue())["verified"])
            self.assertEqual(main(["verify", str(self.target / "missing")]), 2)
        self.assertIn("regular directory", stderr.getvalue())

    def test_html_escapes_entity_and_period_labels(self):
        self.data["entityName"] = "<script>alert('x')</script>"
        self.request["periods"][0]["label"] = "<img src=x onerror=alert(1)>"
        raw = build(self.data, self.request)["index.html"].decode()
        self.assertNotIn(self.data["entityName"], raw)
        self.assertIn("&lt;script&gt;", raw)
        self.assertNotIn("<img", raw)

    def test_custom_period_labels_match_browser_option_values(self):
        labels = [" FY 2023\t ", 'FY\n2024 " & <annual>']
        for period, label in zip(self.request["periods"], labels, strict=True):
            period["label"] = label
        parsed = ReportSelectors()
        parsed.feed(build(self.data, self.request)["index.html"].decode())
        self.assertEqual(parsed.values["period"], labels)
        self.assertEqual(
            {(cutoff, label) for cutoff in parsed.values["cutoff"] for label in parsed.values["period"]},
            parsed.panels,
        )

    def test_labels_with_the_same_normalized_text_stay_distinct(self):
        labels = ["Annual", " Annual "]
        for period, label in zip(self.request["periods"], labels, strict=True):
            period["label"] = label
        parsed = ReportSelectors()
        parsed.feed(build(self.data, self.request)["index.html"].decode())
        self.assertEqual(parsed.values["period"], labels)
        self.assertEqual(len(set(parsed.values["period"])), 2)


if __name__ == "__main__":
    unittest.main()
