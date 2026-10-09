import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from statementtrace.cli import demo_inputs, main
from statementtrace.contracts import ContractError, canonical, digest, read_json
from statementtrace.report import FILES, build, verify, write_report


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


if __name__ == "__main__":
    unittest.main()
