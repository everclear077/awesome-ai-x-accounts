"""Regression coverage for bad data, unsafe exports, and broken navigation."""
import copy
import csv
import io
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.catalog import (
    CatalogError, ROOT, LOCALES, PUBLIC_DOCS, check_local_links, generate, load_catalog,
    load_locales, load_backlog, localized_path, validate, validate_locales,
)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        data, self.schema = load_catalog()
        self.data = copy.deepcopy(data)
        self.template = (ROOT / "templates/README.md").read_text(encoding="utf-8")
        self.locales = load_locales()
        self.backlog = load_backlog()

    def render(self):
        return generate(self.data, self.template, self.locales, self.backlog)

    def test_real_catalog_validates(self):
        validate(self.data, self.schema)
        validate_locales(self.data, self.locales, self.backlog)

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
        expected = self.render()
        self.data["accounts"].reverse()
        self.assertEqual(expected, self.render())
        rows = list(csv.DictReader(io.StringIO(expected["data/accounts.csv"].lstrip("\ufeff"))))
        self.assertEqual(len(rows), len(self.data["accounts"]))
        self.assertEqual(len(expected["data/handles.txt"].splitlines()), len(rows))
        self.assertNotIn("{{", expected["README.md"])

    def test_untrusted_text_cannot_inject_markup_or_csv_formula(self):
        self.data["accounts"][0]["name"] = '=1+1 | <img src="evil">'
        self.data["accounts"][0]["why"] = "安全测试 [link](https://example.com) | <script>bad</script>"
        outputs = self.render()
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
        check_local_links(ROOT, self.render())

    def test_missing_locale_or_account_translation_fails(self):
        original = copy.deepcopy(self.locales)
        del self.locales["ja"]
        with self.assertRaisesRegex(CatalogError, "missing or extra locale"):
            validate_locales(self.data, self.locales, self.backlog)
        self.locales = original
        del self.locales["ru"]["accounts"][self.data["accounts"][0]["handle"]]
        with self.assertRaisesRegex(CatalogError, "missing or extra account translations"):
            validate_locales(self.data, self.locales, self.backlog)

    def test_extra_translation_and_missing_note_fail(self):
        original = copy.deepcopy(self.locales)
        self.locales["ko"]["accounts"]["unknown_handle"] = {}
        with self.assertRaisesRegex(CatalogError, "missing or extra account translations"):
            validate_locales(self.data, self.locales, self.backlog)
        self.locales = original
        account = next(a for a in self.data["accounts"] if a["notes"])
        self.locales["ko"]["accounts"][account["handle"]]["notes"] = ""
        with self.assertRaisesRegex(CatalogError, "too short"):
            validate_locales(self.data, self.locales, self.backlog)

    def test_english_description_and_note_changes_require_translation_review(self):
        for key in ("why", "notes"):
            with self.subTest(key=key):
                data = copy.deepcopy(self.data)
                account = next(a for a in data["accounts"] if a["notes"])
                account[key] += " Updated."
                with self.assertRaisesRegex(CatalogError, "stale account translation"):
                    validate_locales(data, self.locales, self.backlog)

    def test_english_guide_change_requires_translation_review(self):
        self.locales["en"]["docs"]["CONTRIBUTING.md"] += "\n\nNew guidance."
        with self.assertRaisesRegex(CatalogError, "stale interface/document translation"):
            validate_locales(self.data, self.locales, self.backlog)

    def test_missing_guide_or_translation_placeholder_fails(self):
        original = copy.deepcopy(self.locales)
        del self.locales["ja"]["docs"]["SUPPORT.md"]
        with self.assertRaisesRegex(CatalogError, "missing or extra translation keys"):
            validate_locales(self.data, self.locales, self.backlog)
        self.locales = original
        self.locales["ru"]["docs"]["CONTRIBUTING.md"] = self.locales["ru"]["docs"]["CONTRIBUTING.md"].replace("{{COMMANDS}}", "")
        with self.assertRaisesRegex(CatalogError, "placeholder mismatch"):
            validate_locales(self.data, self.locales, self.backlog)

    def test_localized_exports_preserve_all_shared_facts(self):
        outputs = self.render()
        canonical = {a["handle"]: a for a in self.data["accounts"]}
        self.assertEqual(self.data["default_locale"], "en")
        self.assertIn("Find the people behind the progress.", outputs["README.md"])
        for locale in LOCALES:
            with self.subTest(locale=locale):
                rows = list(csv.DictReader(io.StringIO(outputs[localized_path("data/accounts.csv", locale)].lstrip("\ufeff"))))
                self.assertEqual({r["handle"] for r in rows}, canonical.keys())
                for row in rows:
                    account = canonical[row["handle"]]
                    for key in ("name", "url", "category", "kind"):
                        self.assertEqual(row[key], account[key])
                    self.assertEqual(row["languages"], ";".join(account["languages"]))
                    self.assertEqual(row["source_urls"], ";".join(s["url"] for s in account["sources"]))
                    self.assertEqual(row["source_checked_at"], ";".join(s["checked_at"] for s in account["sources"]))
                    expected = account if locale == "en" else self.locales[locale]["accounts"][row["handle"]]
                    self.assertEqual(row["why"], expected["why"])
                    self.assertEqual(row["notes"], expected["notes"])
                for document in ("README.md", "docs/sources.md", *PUBLIC_DOCS):
                    body = outputs[localized_path(document, locale)]
                    for language_name in LOCALES.values():
                        self.assertIn(language_name, body)
                    self.assertNotIn("{{", body)
        self.assertIn("../../AGENTS.md", outputs["docs/ja/ai-workflow.md"])
        self.assertIn("../ru/sources.md", outputs["docs/ja/sources.md"])

    def test_backlog_cannot_duplicate_published_accounts(self):
        self.backlog["candidates"].append({key: self.data["accounts"][0][key] for key in ("name", "handle")})
        with self.assertRaisesRegex(CatalogError, "already published"):
            validate_locales(self.data, self.locales, self.backlog)


if __name__ == "__main__":
    unittest.main()
