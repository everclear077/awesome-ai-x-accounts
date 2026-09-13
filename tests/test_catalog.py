"""Regression checks for profile integrity, seven-language output, and safe imports."""
import copy
import csv
import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.catalog import (
    CatalogError, LOCALES, PUBLIC_DOCS, ROOT, bio_markdown, check_local_links, generate,
    load_backlog, load_catalog, load_locales, localized_path, validate, validate_locales,
)
from scripts.fetch_profiles import main as fetch_main, parse_profile


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.data, self.schema = load_catalog()
        self.locales = load_locales()
        self.backlog = load_backlog()
        self.template = (ROOT / "templates/README.md").read_text(encoding="utf-8")

    def render(self):
        return generate(self.data, self.template, self.locales, self.backlog)

    def test_real_catalog_and_seven_locales_validate(self):
        validate(self.data, self.schema)
        validate_locales(self.data, self.locales, self.backlog)
        self.assertEqual(set(LOCALES), {"en", "zh-CN", "ko", "ja", "ru", "fr", "es"})

    def test_duplicate_handle_is_case_insensitive(self):
        duplicate = copy.deepcopy(self.data["accounts"][0])
        duplicate["handle"] = duplicate["handle"].upper()
        duplicate["id"] = "99999999999999999999"
        duplicate["url"] = "https://x.com/" + duplicate["handle"]
        self.data["accounts"].append(duplicate)
        with self.assertRaisesRegex(CatalogError, "duplicate handle"):
            validate(self.data, self.schema)

    def test_numeric_id_detects_renamed_duplicate(self):
        duplicate = copy.deepcopy(self.data["accounts"][0])
        duplicate["handle"] = "old_handle"
        duplicate["url"] = "https://x.com/old_handle"
        duplicate["source_url"] = "https://x.com/old_handle"
        self.data["accounts"].append(duplicate)
        with self.assertRaisesRegex(CatalogError, "duplicate numeric account id"):
            validate(self.data, self.schema)

    def test_original_bio_preserves_whitespace_and_unicode(self):
        bio = "  Original | <script>bad</script>\n@someone & AI\n日本語\t中文  "
        self.data["accounts"][0]["bio"] = bio
        self.data["accounts"][0]["name"] = "Name\n| **not another row** | <img src=bad>"
        validate(self.data, self.schema)
        self.assertEqual(self.data["accounts"][0]["bio"], bio)
        rendered = self.render()
        escaped = bio_markdown(bio)
        for locale in LOCALES:
            self.assertIn(escaped, rendered[localized_path("README.md", locale)])
            self.assertNotIn("<script>bad</script>", rendered[localized_path("README.md", locale)])
            self.assertNotIn("<img src=bad>", rendered[localized_path("README.md", locale)])
            self.assertEqual(sum(line.startswith("| **") for line in rendered[localized_path("README.md", locale)].splitlines()), len(self.data["accounts"]))

    def test_zero_and_unknown_followers_are_distinct(self):
        self.data["accounts"][0]["followers_count"] = 0
        self.data["accounts"][1]["followers_count"] = None
        self.data["accounts"][0]["bio"] = ""
        self.data["accounts"][1]["bio"] = None
        validate(self.data, self.schema)
        output = self.render()
        rows = list(csv.DictReader(io.StringIO(output["data/accounts.csv"].lstrip("\ufeff"))))
        by_handle = {r["handle"]: r for r in rows}
        self.assertEqual(by_handle[self.data["accounts"][0]["handle"]]["followers_count"], "0")
        self.assertEqual(by_handle[self.data["accounts"][1]["handle"]]["followers_count"], "")
        self.assertIn("| — | 0 |", output["README.md"])
        self.assertIn("| — | — |", output["README.md"])

    def test_invalid_follower_values_rejected(self):
        for value in (-1, 1.5, True, "1.2M", "1000"):
            with self.subTest(value=value):
                self.data["accounts"][0]["followers_count"] = value
                with self.assertRaises(CatalogError):
                    validate(self.data, self.schema)

    def test_editorial_fields_are_rejected(self):
        for key in ("why", "notes", "kind", "languages", "sources"):
            with self.subTest(key=key):
                data = copy.deepcopy(self.data)
                data["accounts"][0][key] = "not part of the profile directory"
                with self.assertRaisesRegex(CatalogError, "unknown field"):
                    validate(data, self.schema)

    def test_category_profile_and_source_mismatch_rejected(self):
        for key, value in (
            ("category", "typo"), ("url", "https://x.com/someone_else"),
            ("source_url", "https://api.fxtwitter.com/2/profile/someone_else"),
            ("source_url", "https://example.com/profile"),
            ("source_url", "https://user:secret@x.com/handle"),
            ("source_url", "https://x.com/handle?other=1"),
        ):
            with self.subTest(key=key, value=value):
                data = copy.deepcopy(self.data)
                data["accounts"][0][key] = value
                with self.assertRaises(CatalogError):
                    validate(data, self.schema)

    def test_source_handle_case_can_differ(self):
        account = self.data["accounts"][0]
        account["source_url"] = "https://api.fxtwitter.com/2/profile/" + account["handle"].upper()
        validate(self.data, self.schema)

    def test_invalid_naive_and_future_timestamps_rejected(self):
        for value in ("2026-02-30T12:00:00+00:00", "2020-01-01T12:00:00",
                      (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()):
            with self.subTest(value=value):
                self.data["accounts"][0]["observed_at"] = value
                with self.assertRaises(CatalogError):
                    validate(self.data, self.schema)

    def test_missing_locale_guide_and_stale_translation_rejected(self):
        for mutate, message in (
            (lambda v: v.pop("fr"), "missing or extra locale"),
            (lambda v: v["es"]["docs"].pop("CONTRIBUTING.md"), "translation keys"),
            (lambda v: v["en"]["ui"].update(intro="Updated English text."), "stale interface"),
        ):
            with self.subTest(message=message):
                locales = copy.deepcopy(self.locales)
                mutate(locales)
                with self.assertRaisesRegex(CatalogError, message):
                    validate_locales(self.data, locales, self.backlog)

    def test_placeholder_and_old_account_translations_rejected(self):
        locales = copy.deepcopy(self.locales)
        locales["ja"]["docs"]["CONTRIBUTING.md"] = locales["ja"]["docs"]["CONTRIBUTING.md"].replace("{{FETCH_COMMAND}}", "")
        with self.assertRaisesRegex(CatalogError, "placeholder mismatch"):
            validate_locales(self.data, locales, self.backlog)
        locales = copy.deepcopy(self.locales)
        locales["ru"]["accounts"] = {}
        with self.assertRaisesRegex(CatalogError, "unknown locale fields"):
            validate_locales(self.data, locales, self.backlog)

    def test_profile_updates_do_not_require_bio_translations(self):
        self.data["accounts"][0]["bio"] = "A new original bio."
        validate_locales(self.data, self.locales, self.backlog)

    def test_generation_deterministic_and_seven_tables_have_three_columns(self):
        expected = self.render()
        self.data["accounts"].reverse()
        self.assertEqual(expected, self.render())
        for locale in LOCALES:
            body = expected[localized_path("README.md", locale)]
            self.assertEqual(body.count("| --- | --- | ---: |"), len(self.data["categories"]))
            self.assertEqual(sum(line.startswith("| **") for line in body.splitlines()), len(self.data["accounts"]))
            self.assertNotIn("<sub>", body)
            self.assertNotIn("docs/sources.md", body)
            self.assertNotIn("#start", body)
            for account in self.data["accounts"]:
                self.assertIn(bio_markdown(account["bio"]), body)
            for document in ("README.md", *PUBLIC_DOCS):
                text = expected[localized_path(document, locale)]
                for language in LOCALES.values():
                    self.assertIn(language, text)
                self.assertNotIn("{{", text)
        self.assertEqual([p for p in expected if p.endswith(".csv")], ["data/accounts.csv"])

    def test_csv_formula_safety_and_shared_profile_values(self):
        self.data["accounts"][0]["bio"] = " \n=HYPERLINK(\"bad\")"
        self.data["accounts"][1]["bio"] = "literal\nsecond line"
        output = self.render()
        rows = list(csv.DictReader(io.StringIO(output["data/accounts.csv"].lstrip("\ufeff"))))
        self.assertEqual(len(rows), len(self.data["accounts"]))
        by_handle = {r["handle"]: r for r in rows}
        first, second = self.data["accounts"][:2]
        self.assertEqual(by_handle[first["handle"]]["bio"], "'" + first["bio"])
        self.assertEqual(by_handle[second["handle"]]["bio"], second["bio"])
        self.assertEqual(by_handle[second["handle"]]["followers_count"], str(second["followers_count"]))

    def test_current_navigation_and_invalid_links(self):
        check_local_links(ROOT, self.render())
        with tempfile.TemporaryDirectory() as directory:
            for text in ("[bad](missing.md)", "[bad](#missing)", "[bad](../outside.md)"):
                with self.subTest(text=text), self.assertRaises(CatalogError):
                    check_local_links(Path(directory), {"README.md": text})

    def test_backlog_cannot_repeat_published_account(self):
        self.backlog["candidates"].append({key: self.data["accounts"][0][key] for key in ("name", "handle")})
        with self.assertRaisesRegex(CatalogError, "already published"):
            validate_locales(self.data, self.locales, self.backlog)


class ProfileFetchTests(unittest.TestCase):
    def setUp(self):
        self.payload = {"code": 200, "user": {
            "id": "123456", "screen_name": "Example", "name": "Example", "protected": False,
            "description": "A rewritten description that must not be used",
            "raw_description": {"text": "  Literal\n@someone | 中文  "}, "followers": 0,
        }}

    def test_fetch_uses_raw_bio_and_zero_count(self):
        record = parse_profile(self.payload, "example", "research", "2020-01-01T00:00:00+00:00")
        self.assertEqual(record["bio"], self.payload["user"]["raw_description"]["text"])
        self.assertEqual(record["followers_count"], 0)
        self.assertEqual(record["id"], "123456")

    def test_fetch_rejects_other_handles_missing_data_and_private_profiles(self):
        for mutate in (
            lambda p: p["user"].update(screen_name="SomeoneElse"),
            lambda p: p["user"].update(protected=True),
            lambda p: p["user"].pop("raw_description"),
            lambda p: p["user"].update(followers=True),
            lambda p: p["user"].update(followers=-1),
            lambda p: p.update(code=404),
        ):
            with self.subTest(mutate=mutate):
                payload = copy.deepcopy(self.payload)
                mutate(payload)
                with self.assertRaises(CatalogError):
                    parse_profile(payload, "example", "research", "2020-01-01T00:00:00+00:00")
        with self.assertRaises(CatalogError):
            parse_profile([], "example", "research", "2020-01-01T00:00:00+00:00")

    def test_fetch_refuses_existing_output_before_network_access(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "accounts.json"
            target.write_text("keep this data", encoding="utf-8")
            with patch("sys.argv", ["fetch_profiles.py", "example", "--category", "research", "--output", str(target)]):
                with patch("scripts.fetch_profiles.urllib.request.urlopen") as network:
                    with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                        fetch_main()
                    network.assert_not_called()
            self.assertEqual(target.read_text(encoding="utf-8"), "keep this data")


if __name__ == "__main__":
    unittest.main()
