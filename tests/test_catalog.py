"""Regression coverage for bad data, unsafe exports, and broken navigation."""
import copy
import csv
import io
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.catalog import (
    CatalogError, ROOT, check_local_links, generate, load_catalog, validate,
)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        data, self.schema = load_catalog()
        self.data = copy.deepcopy(data)
        self.template = (ROOT / "templates/README.md").read_text(encoding="utf-8")

    def test_real_catalog_validates(self):
        validate(self.data, self.schema)

    def test_case_insensitive_duplicate_is_rejected(self):
        duplicate = copy.deepcopy(self.data["accounts"][0])
        duplicate["handle"] = duplicate["handle"].upper()
        duplicate["url"] = "https://x.com/" + duplicate["handle"]
        self.data["accounts"].append(duplicate)
        with self.assertRaisesRegex(CatalogError, "duplicate handle"):
            validate(self.data, self.schema)

    def test_wrong_identity_source_is_rejected(self):
        self.data["accounts"][0]["sources"][0]["url"] = "https://x.com/someone_else/status/123"
        with self.assertRaisesRegex(CatalogError, "different handle"):
            validate(self.data, self.schema)

    def test_missing_evidence_is_rejected(self):
        self.data["accounts"][0]["sources"] = []
        with self.assertRaisesRegex(CatalogError, "too few items"):
            validate(self.data, self.schema)

    def test_unknown_field_is_rejected(self):
        self.data["accounts"][0]["followers"] = 100000
        with self.assertRaisesRegex(CatalogError, "unknown field"):
            validate(self.data, self.schema)

    def test_category_and_url_mismatch_are_rejected(self):
        for field, value, message in (
            ("category", "typo", "unknown category"),
            ("url", "https://x.com/typo", "URL mismatch"),
        ):
            with self.subTest(field=field):
                data = copy.deepcopy(self.data)
                data["accounts"][0][field] = value
                with self.assertRaisesRegex(CatalogError, message):
                    validate(data, self.schema)

    def test_invalid_or_future_dates_are_rejected(self):
        for value in ("2026-02-30", (date.today() + timedelta(days=1)).isoformat()):
            with self.subTest(value=value):
                self.data["accounts"][0]["sources"][0]["checked_at"] = value
                with self.assertRaises(CatalogError):
                    validate(self.data, self.schema)

    def test_unsafe_source_is_rejected(self):
        for url in ("javascript:alert(1)", "https://user:secret@example.com/x", "https://x.com/<script>"):
            with self.subTest(url=url):
                self.data["accounts"][0]["sources"][0]["url"] = url
                with self.assertRaises(CatalogError):
                    validate(self.data, self.schema)

    def test_generation_is_independent_of_input_order(self):
        expected = generate(self.data, self.template)
        self.data["accounts"].reverse()
        self.assertEqual(expected, generate(self.data, self.template))
        rows = list(csv.DictReader(io.StringIO(expected["data/accounts.csv"].lstrip("\ufeff"))))
        self.assertEqual(len(rows), len(self.data["accounts"]))
        self.assertEqual(len(expected["data/handles.txt"].splitlines()), len(rows))
        self.assertNotIn("{{", expected["README.md"])

    def test_untrusted_text_cannot_inject_markup_or_csv_formula(self):
        self.data["accounts"][0]["name"] = '=1+1 | <img src="evil">'
        self.data["accounts"][0]["why"] = "安全测试 [link](https://example.com) | <script>bad</script>"
        outputs = generate(self.data, self.template)
        self.assertNotIn('<img src="evil">', outputs["README.md"])
        self.assertIn("&lt;script&gt;", outputs["README.md"])
        rows = list(csv.DictReader(io.StringIO(outputs["data/accounts.csv"].lstrip("\ufeff"))))
        row = next(r for r in rows if r["handle"] == self.data["accounts"][0]["handle"])
        self.assertTrue(row["name"].startswith("'="))

    def test_missing_file_and_anchor_fail_link_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for rendered in (
                {"README.md": "[missing](missing.md)"},
                {"README.md": "[missing](#missing)"},
                {"README.md": "[escape](../outside.md)"},
            ):
                with self.subTest(rendered=rendered):
                    with self.assertRaises(CatalogError):
                        check_local_links(root, rendered)

    def test_current_navigation_targets_exist(self):
        check_local_links(ROOT, generate(self.data, self.template))


if __name__ == "__main__":
    unittest.main()
