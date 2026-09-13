"""Validate the catalog and generate its public views. Python 3.11+, stdlib only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import posixpath
import re
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class CatalogError(ValueError):
    """A human-readable catalog validation error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CatalogError(message)


def validate_shape(value: object, schema: dict, path: str = "$") -> None:
    """Validate the small, explicit JSON Schema subset used by this repository."""
    types = {"object": dict, "array": list, "string": str, "integer": int}
    expected = schema.get("type")
    if expected:
        require(type(value) is types[expected], f"{path}: expected {expected}")
    if "enum" in schema:
        require(value in schema["enum"], f"{path}: invalid value {value!r}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            require(key in value, f"{path}: missing {key}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            require(not value.keys() - properties.keys(), f"{path}: unknown field")
        for key, item in value.items():
            if key in properties:
                validate_shape(item, properties[key], f"{path}.{key}")
    elif isinstance(value, list):
        require(len(value) >= schema.get("minItems", 0), f"{path}: too few items")
        if schema.get("uniqueItems"):
            keys = [json.dumps(v, sort_keys=True) for v in value]
            require(len(set(keys)) == len(keys), f"{path}: duplicate items")
        for index, item in enumerate(value):
            validate_shape(item, schema.get("items", {}), f"{path}[{index}]")
    elif isinstance(value, str):
        require(len(value) >= schema.get("minLength", 0), f"{path}: too short")
        require(len(value) <= schema.get("maxLength", len(value)), f"{path}: too long")
        require(not any(ord(c) < 32 for c in value), f"{path}: control character")
        require(value == value.strip(), f"{path}: surrounding whitespace")
        if "pattern" in schema:
            require(re.search(schema["pattern"], value) is not None, f"{path}: invalid format")
        if schema.get("format") == "date":
            try:
                parsed = date.fromisoformat(value)
            except ValueError as exc:
                raise CatalogError(f"{path}: invalid date") from exc
            require(parsed.isoformat() == value, f"{path}: noncanonical date")
            require(parsed <= date.today(), f"{path}: future check date")


def validate(data: dict, schema: dict) -> None:
    validate_shape(data, schema)
    categories = [c["id"] for c in data["categories"]]
    require(len(categories) == len(set(categories)), "duplicate category id")
    handles: set[str] = set()
    for account in data["accounts"]:
        handle = account["handle"]
        require(handle.lower() not in handles, f"duplicate handle: {handle}")
        handles.add(handle.lower())
        require(account["category"] in categories, f"{handle}: unknown category")
        require(account["url"] == f"https://x.com/{handle}", f"{handle}: URL mismatch")
        seen_sources: set[str] = set()
        for source in account["sources"]:
            url = source["url"]
            parsed = urlsplit(url)
            require(
                parsed.scheme == "https" and bool(parsed.hostname)
                and "." in parsed.hostname and not parsed.username
                and not parsed.password and not re.search(r'[\s<>"\\]', url),
                f"{handle}: unsafe source URL",
            )
            require(url not in seen_sources, f"{handle}: duplicate source")
            seen_sources.add(url)
            if source["method"] == "x-index":
                require(parsed.hostname in {"x.com", "twitter.com", "mobile.x.com", "www.x.com"},
                        f"{handle}: x-index source must be on X")
                parts = parsed.path.strip("/").split("/")
                require(parts[0].lower() == handle.lower(),
                        f"{handle}: source belongs to a different handle")


def md(value: str) -> str:
    escaped = html.escape(value, quote=False)
    special = set("\\|[]*_") | {chr(96)}
    return "".join("\\" + char if char in special else char for char in escaped)


def md_url(value: str) -> str:
    return value.replace("(", "%28").replace(")", "%29")


def csv_safe(value: str) -> str:
    # Spreadsheet programs may evaluate cells beginning with a formula prefix.
    return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value


LOCALES = {"en": "English", "zh-CN": "简体中文", "ko": "한국어", "ja": "日本語", "ru": "Русский"}
PUBLIC_DOCS = (
    "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md", "SUPPORT.md", "CHANGELOG.md",
    "docs/curation-policy.md", "docs/ai-workflow.md", "docs/maintenance.md",
    "docs/research-backlog.md",
)
COMMANDS = (
    chr(96) * 3 + "sh\npython scripts/catalog.py build\npython scripts/catalog.py check\n"
    "python -m unittest discover -s tests -v\ngit diff --check\n" + chr(96) * 3
)
GENERATED = "<!-- Generated by scripts/catalog.py. Edit data, locales, or templates. -->\n"
TOKEN = re.compile(r"\{\{([A-Z_]+)\}\}")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def account_digest(account: dict) -> str:
    return digest({key: account[key] for key in ("why", "notes")})


def load_locales(root: Path = ROOT) -> dict:
    return {path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((root / "locales").glob("*.json"))}


def load_backlog(root: Path = ROOT) -> dict:
    return json.loads((root / "data/research-backlog.json").read_text(encoding="utf-8"))


def validate_translation_shape(value: object, reference: object, path: str) -> None:
    require(type(value) is type(reference), f"{path}: translation type mismatch")
    if isinstance(reference, dict):
        require(value.keys() == reference.keys(), f"{path}: missing or extra translation keys")
        for key in reference:
            validate_translation_shape(value[key], reference[key], f"{path}.{key}")
    elif isinstance(reference, list):
        require(len(value) == len(reference), f"{path}: translation list length mismatch")
        for index, (item, original) in enumerate(zip(value, reference)):
            validate_translation_shape(item, original, f"{path}[{index}]")
    else:
        require(isinstance(value, str) and bool(value.strip()), f"{path}: empty translation")
        require(value == value.strip() and "\r" not in value, f"{path}: noncanonical whitespace")
        require(Counter(TOKEN.findall(value)) == Counter(TOKEN.findall(reference)),
                f"{path}: translation placeholder mismatch")


def validate_locales(data: dict, locales: dict, backlog: dict) -> None:
    require(locales.keys() == LOCALES.keys(), "missing or extra locale")
    english = locales["en"]
    require(english.keys() == {"ui", "docs"}, "en: unknown fields")
    require(english["docs"].keys() == set(PUBLIC_DOCS), "en: missing or extra public documents")
    validate_translation_shape(english, english, "en")
    ui = english["ui"]
    require(ui["categories"] == {c["id"]: c["title"] for c in data["categories"]},
            "English category labels differ from canonical data")
    require(ui["types"].keys() == {"person", "organization", "media"}, "invalid account types")
    require(ui["methods"].keys() == {"x-index", "owner-link"}, "invalid source methods")
    require(ui["language_names"].keys() == {"zh", "en", "fr", "ja", "ko", "es", "de", "pt", "ar", "hi", "ru"},
            "invalid content language labels")
    for key, length in {"start_rows": 7, "exports": 5, "stats": 5, "backlog_headers": 3,
                        "issue": 11, "correction": 7}.items():
        require(len(ui[key]) == length, f"en.ui.{key}: invalid list length")
    for locale in LOCALES:
        if locale == "en":
            continue
        resource = locales[locale]
        require(resource.keys() == {"ui", "docs", "accounts", "source_digest"},
                f"{locale}: missing or extra locale fields")
        require(resource["source_digest"] == digest(english), f"{locale}: stale interface/document translation")
        for key in ("ui", "docs"):
            validate_translation_shape(resource[key], english[key], f"{locale}.{key}")
        require(resource["accounts"].keys() == {a["handle"] for a in data["accounts"]},
                f"{locale}: missing or extra account translations")
        for account in data["accounts"]:
            handle = account["handle"]
            item = resource["accounts"][handle]
            require(item.keys() == {"why", "notes", "source_digest"},
                    f"{locale}.{handle}: missing or extra account fields")
            for key in ("why", "notes"):
                validate_shape(item[key], {"type": "string", "minLength": 1 if account[key] else 0,
                                          "maxLength": 1000}, f"{locale}.{handle}.{key}")
                require(bool(item[key]) == bool(account[key]), f"{locale}.{handle}: note coverage mismatch")
            require(item["source_digest"] == account_digest(account),
                    f"{locale}.{handle}: stale account translation")
    validate_shape(backlog, {
        "type": "object", "required": ["research_date", "candidates"], "additionalProperties": False,
        "properties": {
            "research_date": {"type": "string", "format": "date"},
            "candidates": {"type": "array", "items": {
                "type": "object", "required": ["name", "handle"], "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 100},
                    "handle": {"type": "string", "pattern": "^[A-Za-z0-9_]{1,15}$"},
                },
            }},
        },
    }, "backlog")
    handles = [a["handle"].lower() for a in backlog["candidates"]]
    require(len(handles) == len(set(handles)), "duplicate backlog candidate")
    require(not set(handles) & {a["handle"].lower() for a in data["accounts"]},
            "backlog candidate already published")


def localized_path(path: str, locale: str) -> str:
    if locale == "en":
        return path
    parent, name = posixpath.split(path)
    if parent == "docs":
        return f"docs/{locale}/{name}"
    stem, extension = posixpath.splitext(name)
    return posixpath.join(parent, f"{stem}.{locale}{extension}")


def relative_link(page: str, target: str) -> str:
    return posixpath.relpath(target, posixpath.dirname(page) or ".")


def language_nav(document: str, locale: str) -> str:
    page = localized_path(document, locale)
    links = [f"**{label}**" if language == locale else
             f"[{label}]({relative_link(page, localized_path(document, language))})"
             for language, label in LOCALES.items()]
    return " · ".join(links)


def substitute(text: str, values: dict[str, str]) -> str:
    def replace(match: re.Match) -> str:
        require(match[1] in values, f"unknown placeholder: {match[1]}")
        return values[match[1]]
    rendered = TOKEN.sub(replace, text)
    require("{{" not in rendered, "unresolved placeholder")
    return rendered


def context(document: str, locale: str) -> dict[str, str]:
    page = localized_path(document, locale)
    targets = {
        "POLICY_LINK": "docs/curation-policy.md", "COC_LINK": "CODE_OF_CONDUCT.md",
        "BACKLOG_LINK": "docs/research-backlog.md", "MAINTENANCE_LINK": "docs/maintenance.md",
        "WORKFLOW_LINK": "docs/ai-workflow.md", "CONTRIBUTING_LINK": "CONTRIBUTING.md",
        "SOURCES_LINK": "docs/sources.md", "CHANGELOG_LINK": "CHANGELOG.md",
        "SUPPORT_LINK": "SUPPORT.md", "SECURITY_LINK": "SECURITY.md",
    }
    values = {key: relative_link(page, localized_path(target, locale)) for key, target in targets.items()}
    values.update({
        "LICENSE_LINK": relative_link(page, "LICENSE"),
        "AGENTS_LINK": relative_link(page, "AGENTS.md"), "COMMANDS": COMMANDS,
    })
    for key, name in (("ISSUE_URL", "account.yml"), ("CORRECTION_URL", "correction.yml")):
        values[key] = ("https://github.com/everclear077/awesome-ai-x-accounts/issues/new?template="
                       + localized_path(name, locale))
    return values


def stats_svg(total: int, categories: int, kinds: Counter, labels: list[str]) -> str:
    numbers = [total, categories, kinds["person"], kinds["organization"], kinds["media"]]
    title = " · ".join(f"{number} {label}" for number, label in zip(numbers, labels))
    pieces = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="950" height="112" viewBox="0 0 950 112" role="img" aria-labelledby="title">',
        f'<title id="title">{html.escape(title)}</title>',
        '<rect x="1" y="1" width="948" height="110" rx="18" fill="#101d31" stroke="#283b54"/>',
        '<g font-family="Arial, sans-serif" text-anchor="middle">',
    ]
    for index, (number, label) in enumerate(zip(numbers, labels)):
        x = 95 + index * 190
        pieces.append(f'<text x="{x}" y="53" font-size="32" font-weight="700" fill="#76e6d4">{number}</text>')
        pieces.append(f'<text x="{x}" y="81" font-size="12" fill="#b6c7dd">{html.escape(label)}</text>')
        if index:
            pieces.append(f'<path d="M{index * 190} 28v56" stroke="#283b54"/>')
    return "\n".join(pieces + ["</g>", "</svg>", ""])


def issue_form(ui: dict, locale: str, correction: bool = False) -> str:
    """JSON-quoted scalar values remain readable, valid YAML without a dependency."""
    terms = ui["correction" if correction else "issue"]
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    pieces = [
        f"name: {quote(LOCALES[locale] + ' · ' + terms[0])}",
        f"description: {quote(terms[1])}",
        f"title: {quote('[Correction] ' if correction else '[Account] ')}", "body:",
    ]
    if correction:
        fields = [
            ("input", "handle", terms[2], None, None),
            ("textarea", "problem", terms[3], terms[4], None),
            ("textarea", "evidence", terms[5], terms[6], None),
        ]
    else:
        fields = [
            ("input", "name", terms[2], None, None),
            ("input", "url", terms[3], None, "https://x.com/handle"),
            ("dropdown", "kind", terms[4], None, None),
            ("textarea", "reason", terms[5], terms[6], None),
            ("textarea", "evidence", terms[7], terms[8], None),
            ("input", "relation", terms[9], None, terms[10]),
        ]
    for kind, identifier, label, description, placeholder in fields:
        pieces += [f"  - type: {kind}", f"    id: {identifier}", "    attributes:", f"      label: {quote(label)}"]
        if description:
            pieces.append(f"      description: {quote(description)}")
        if placeholder:
            pieces.append(f"      placeholder: {quote(placeholder)}")
        if kind == "dropdown":
            pieces += ["      options:"] + [f"        - {quote(value)}" for value in ui["types"].values()]
        pieces += ["    validations:", "      required: true"]
    return "\n".join(pieces) + "\n"


def tool_table(page: str) -> str:
    tools = [
        ("Codex", "AGENTS.md"), ("Claude Code", "CLAUDE.md"),
        ("Gemini CLI", "GEMINI.md"), ("GitHub Copilot", ".github/copilot-instructions.md"),
        ("Cursor", ".cursor/rules/project.mdc"), ("Windsurf", ".windsurf/rules/project.md"),
        ("Cline", ".clinerules/01-project.md"),
    ]
    return "\n".join(f"- {name}: [{path}]({relative_link(page, path)})" for name, path in tools)


def generate(data: dict, template: str, locales: dict, backlog: dict) -> dict[str, str]:
    accounts = sorted(data["accounts"], key=lambda a: a["handle"].lower())
    kinds = Counter(a["kind"] for a in accounts)
    counts = Counter(a["category"] for a in accounts)
    quantities = {
        "COUNT": str(len(accounts)), "CATEGORY_COUNT": str(len(data["categories"])),
        "PEOPLE": str(kinds["person"]), "ORGS": str(kinds["organization"]), "MEDIA": str(kinds["media"]),
        "REVIEW_DATE": max(s["checked_at"] for a in accounts for s in a["sources"]),
    }
    outputs = {"data/handles.txt": "\n".join(a["handle"] for a in accounts) + "\n"}
    for locale in LOCALES:
        ui = locales[locale]["ui"]
        readme_path = localized_path("README.md", locale)
        sources_path = localized_path("docs/sources.md", locale)
        values = context("README.md", locale) | quantities
        local_accounts = [
            a if locale == "en" else a | {key: locales[locale]["accounts"][a["handle"]][key]
                                          for key in ("why", "notes")}
            for a in accounts
        ]
        directory = [f'| {ui["topic"]} | {ui["count"]} |', "| --- | ---: |"]
        sections = []
        sources = [
            GENERATED.rstrip(), "", language_nav("docs/sources.md", locale), "",
            f'# {ui["source_title"]}', "",
            substitute(ui["source_intro"], context("docs/sources.md", locale)), "",
            f'[{ui["browse"]}]({relative_link(sources_path, readme_path)})', "",
        ]
        for category in data["categories"]:
            cid = category["id"]
            title = md(ui["categories"][cid])
            directory.append(f"| [{title}](#{cid}) | {counts[cid]} |")
            sections += [
                f'<a id="{cid}"></a>', "", f"## {title}", "",
                f'**{counts[cid]} · {ui["count"]}**', "",
            ]
            # Russian words need more width than two mobile table cells provide.
            if locale != "ru":
                sections += [f'| {ui["account"]} | {ui["why"]} |', "| --- | --- |"]
            sources += [f"## {title}", ""]
            for account in local_accounts:
                if account["category"] != cid:
                    continue
                handle = account["handle"]
                anchor = handle.lower()
                name = md(account["name"])
                url = md_url(account["url"])
                languages = " / ".join(ui["language_names"][language] for language in account["languages"])
                why = md(account["why"])
                if account["notes"]:
                    why += "<br /><sub>" + md(account["notes"]) + "</sub>"
                identity = f"**{name}**<br />[@{md(handle)}]({url})<br />"
                identity += f'<sub>{ui["types"][account["kind"]]} · {languages}</sub>'
                description = f'{why}<br />[{ui["evidence"]}]({sources_path}#{anchor})'
                if locale == "ru":
                    sections += [f"- {identity}<br />{description}", ""]
                else:
                    sections.append(f"| {identity} | {description} |")
                sources += [f'<a id="{anchor}"></a>', "", f"### {name} · @{md(handle)}", "",
                            f'- {ui["profile"]}: [@{md(handle)}]({url})']
                for index, source in enumerate(account["sources"], 1):
                    sources.append(
                        f'- {ui["evidence"]} {index}: [{ui["methods"][source["method"]]}]({md_url(source["url"])})'
                        f' · {ui["checked"]}: {source["checked_at"]}'
                    )
                if account["notes"]:
                    sources.append(f'- {ui["note"]}: {md(account["notes"])}')
                sources.append("")
            sections += ["", f'[↑ {ui["back"]}](#directory)', ""]
        routes = [("llm", "research"), ("agents", "infra"), ("coding", "agents"),
                  ("creative",), ("robotics",), ("chinese",), ("labs", "media")]
        start = [] if locale == "ru" else [f'| {ui["start_header"]} | {ui["topic"]} |', "| --- | --- |"]
        for label, route in zip(ui["start_rows"], routes):
            links = " → ".join(f'[{md(ui["categories"][cid])}](#{cid})' for cid in route)
            start.append(f"- **{md(label)}**: {links}" if locale == "ru" else f"| {md(label)} | {links} |")
        export_paths = [
            ("JSON", "data/accounts.json"), ("CSV", localized_path("data/accounts.csv", locale)),
            ("TXT", "data/handles.txt"), (ui["sources"], sources_path),
            (ui["backlog_headers"][0], localized_path("docs/research-backlog.md", locale)),
        ]
        exports = [f'| {ui["format"]} | {ui["use"]} |', "| --- | --- |"]
        for (label, path), description in zip(export_paths, ui["exports"]):
            exports.append(f"| [{label}]({path}) | {md(description)} |")
        values.update({key.upper(): substitute(value, values) for key, value in ui.items() if isinstance(value, str)})
        values.update({
            "LANGUAGE_NAV": language_nav("README.md", locale),
            "STATS_PATH": localized_path("assets/stats.svg", locale),
            "STATS_ALT": html.escape(" · ".join(
                f"{number} {label}" for number, label in zip(
                    [len(accounts), len(data["categories"]), kinds["person"], kinds["organization"], kinds["media"]],
                    ui["stats"],
                )), quote=True),
            "DIRECTORY_TABLE": "\n".join(directory), "ACCOUNTS": "\n".join(sections).rstrip(),
            "START_TABLE": "\n".join(start), "EXPORT_TABLE": "\n".join(exports),
        })
        outputs[readme_path] = substitute(template, values).rstrip() + "\n"
        outputs[sources_path] = "\n".join(sources).rstrip() + "\n"
        for document in PUBLIC_DOCS:
            page = localized_path(document, locale)
            doc_values = context(document, locale)
            rows = ["| " + " | ".join(ui["backlog_headers"]) + " |", "| --- | --- | --- |"]
            for candidate in sorted(backlog["candidates"], key=lambda a: a["handle"].lower()):
                rows.append(f'| {md(candidate["name"])} | {md(candidate["handle"])} | {ui["backlog_next"]} |')
            doc_values.update({"BACKLOG_TABLE": "\n".join(rows), "TOOL_TABLE": tool_table(page),
                               "BACKLOG_DATE": backlog["research_date"]})
            outputs[page] = (GENERATED + "\n" + language_nav(document, locale) + "\n\n"
                             + substitute(locales[locale]["docs"][document], doc_values).rstrip() + "\n")
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["handle", "name", "url", "category", "kind", "languages", "why",
                         "source_urls", "source_methods", "source_checked_at", "notes"])
        for account in local_accounts:
            row = [account[key] for key in ("handle", "name", "url", "category", "kind")]
            row += [";".join(account["languages"]), account["why"]]
            row += [";".join(s[key] for s in account["sources"]) for key in ("url", "method", "checked_at")]
            row.append(account["notes"])
            writer.writerow([csv_safe(value) for value in row])
        outputs[localized_path("data/accounts.csv", locale)] = "\ufeff" + output.getvalue()
        outputs[localized_path("assets/stats.svg", locale)] = stats_svg(len(accounts), len(data["categories"]), kinds, ui["stats"])
        for name, correction in (("account.yml", False), ("correction.yml", True)):
            outputs[".github/ISSUE_TEMPLATE/" + localized_path(name, locale)] = issue_form(ui, locale, correction)
    return outputs




def check_local_links(root: Path, rendered: dict[str, str]) -> None:
    """Check local Markdown/HTML link targets; external availability is not tested."""
    texts = dict(rendered)
    for path in root.rglob("*.md"):
        if any(p.startswith(".") for p in path.relative_to(root).parts[:-1]):
            continue
        if "templates" in path.relative_to(root).parts:
            continue  # Template links resolve from the generated README location.
        texts.setdefault(path.relative_to(root).as_posix(), path.read_text(encoding="utf-8"))
    for pattern in (".github/*.md", ".cursor/rules/*.mdc", ".windsurf/rules/*.md", ".clinerules/*.md"):
        for path in root.glob(pattern):
            texts.setdefault(path.relative_to(root).as_posix(), path.read_text(encoding="utf-8"))
    for filename, content in texts.items():
        if not filename.endswith((".md", ".mdc")):
            continue
        destinations = re.findall(r"!?\[[^\n]*?\]\(([^)\s]+)\)", content)
        destinations += re.findall(r'(?:src|href)="([^"]+)"', content)
        for target in destinations:
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc:
                continue
            relative = unquote(parsed.path)
            path = ((root / filename).parent / relative).resolve() if relative else root / filename
            require(path.is_relative_to(root.resolve()), f"{filename}: link escapes repository")
            key = path.relative_to(root.resolve()).as_posix()
            require(key in rendered or path.is_file(), f"{filename}: missing link target {target}")
            if parsed.fragment:
                body = texts.get(key)
                if body is None and path.is_file():
                    body = path.read_text(encoding="utf-8")
                require(body is not None and f'id="{unquote(parsed.fragment)}"' in body,
                        f"{filename}: missing anchor {target}")


def load_catalog(root: Path = ROOT) -> tuple[dict, dict]:
    data = json.loads((root / "data/accounts.json").read_text(encoding="utf-8"))
    schema = json.loads((root / "data/accounts.schema.json").read_text(encoding="utf-8"))
    return data, schema


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "check", "digests"])
    args = parser.parse_args()
    try:
        data, schema = load_catalog()
        validate(data, schema)
        locales, backlog = load_locales(), load_backlog()
        if args.command == "digests":
            print(json.dumps({
                "interface_and_documents": digest(locales["en"]),
                "accounts": {a["handle"]: account_digest(a) for a in data["accounts"]},
            }, indent=2))
            return 0
        validate_locales(data, locales, backlog)
        outputs = generate(data, (ROOT / "templates/README.md").read_text(encoding="utf-8"), locales, backlog)
        check_local_links(ROOT, outputs)
        stale = []
        for filename, content in outputs.items():
            path = ROOT / filename
            if args.command == "build":
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8", newline="\n")
            elif not path.is_file() or path.read_bytes() != content.encode("utf-8"):
                stale.append(filename)
        require(not stale, "generated files are stale: " + ", ".join(stale)
                + "; run python scripts/catalog.py build")
        print(f'{args.command}: OK ({len(data["accounts"])} accounts, '
              f'{len(data["categories"])} categories, {len(LOCALES)} languages, {len(outputs)} generated files)')
        return 0
    except (CatalogError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"catalog: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
