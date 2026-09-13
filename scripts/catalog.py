"""Validate the catalog and generate its public views. Python 3.11+, stdlib only."""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
KINDS = {"person": "个人", "organization": "组织", "media": "媒体"}
LANGUAGES = {
    "zh": "中文", "en": "英文", "fr": "法文", "ja": "日文", "ko": "韩文",
    "es": "西班牙文", "de": "德文", "pt": "葡萄牙文", "ar": "阿拉伯文", "hi": "印地文",
}
METHODS = {"x-index": "X 索引", "owner-link": "本人/官网外链"}


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


def stats_svg(total: int, categories: int, kinds: Counter) -> str:
    cells = [
        (total, "ACCOUNTS"), (categories, "TOPICS"),
        (kinds["person"], "PEOPLE"), (kinds["organization"], "ORGANIZATIONS"),
        (kinds["media"], "MEDIA"),
    ]
    pieces = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="950" height="112" viewBox="0 0 950 112" role="img" aria-labelledby="title">',
        f'<title id="title">{total} accounts across {categories} topics</title>',
        '<rect x="1" y="1" width="948" height="110" rx="18" fill="#101d31" stroke="#283b54"/>',
        '<g font-family="Arial, sans-serif" text-anchor="middle">',
    ]
    for index, (number, label) in enumerate(cells):
        x = 95 + index * 190
        pieces.append(f'<text x="{x}" y="53" font-size="32" font-weight="700" fill="#76e6d4">{number}</text>')
        pieces.append(f'<text x="{x}" y="81" font-size="11" letter-spacing="1.3" fill="#b6c7dd">{label}</text>')
        if index:
            pieces.append(f'<path d="M{index * 190} 28v56" stroke="#283b54"/>')
    return "\n".join(pieces + ["</g>", "</svg>", ""])


def generate(data: dict, template: str) -> dict[str, str]:
    accounts = sorted(data["accounts"], key=lambda a: a["handle"].lower())
    kinds = Counter(a["kind"] for a in accounts)
    counts = Counter(a["category"] for a in accounts)
    latest = max(s["checked_at"] for a in accounts for s in a["sources"])
    directory = ["| 主题 | 账号数 |", "| --- | ---: |"]
    sections: list[str] = []
    sources = [
        "<!-- Generated by scripts/catalog.py. Do not edit directly. -->",
        "# 账号来源与核对记录", "",
        "这里记录名字与账号对应关系的依据。日期是查阅来源的日期，不是账号最近发帖日期。",
        "X 索引可能滞后，来源帖也不一定是代表作。推荐理由是编辑概括。",
        "方法与限制见 [收录标准](curation-policy.md)。[返回目录](../README.md)。", "",
    ]
    for category in data["categories"]:
        cid = category["id"]
        title = md(category["title"])
        directory.append(f"| [{title}](#{cid}) | {counts[cid]} |")
        sections += [
            f'<a id="{cid}"></a>', "", f"## {title}", "",
            f'{md(category["title_en"])} · **{counts[cid]} 个账号**', "",
            "| 账号 | 关注什么 |",
            "| --- | --- |",
        ]
        sources += [f"## {title}", ""]
        for account in accounts:
            if account["category"] != cid:
                continue
            handle = account["handle"]
            anchor = handle.lower()
            name = md(account["name"])
            url = md_url(account["url"])
            languages = " / ".join(LANGUAGES[l] for l in account["languages"])
            why = md(account["why"])
            if account["notes"]:
                why += "<br /><sub>" + md(account["notes"]) + "</sub>"
            sections.append(
                f"| **{name}**<br />[@{md(handle)}]({url})<br />"
                f'<sub>{KINDS[account["kind"]]} · {languages}</sub> | {why}<br />'
                f"[来源依据](docs/sources.md#{anchor}) |"
            )
            sources += [f'<a id="{anchor}"></a>', "", f"### {name} · @{md(handle)}", ""]
            sources.append(f"- 主页：[@{md(handle)}]({url})")
            for index, source in enumerate(account["sources"], 1):
                sources.append(
                    f'- 依据 {index}：[{METHODS[source["method"]]}]({md_url(source["url"])})'
                    f'；核对日期：{source["checked_at"]}。'
                )
            if account["notes"]:
                sources.append(f'- 备注：{md(account["notes"])}')
            sources.append("")
        sections += ["", "[↑ 返回分类目录](#directory)", ""]
    values = {
        "COUNT": str(len(accounts)), "CATEGORY_COUNT": str(len(data["categories"])),
        "PEOPLE": str(kinds["person"]), "ORGS": str(kinds["organization"]),
        "MEDIA": str(kinds["media"]), "REVIEW_DATE": latest,
        "DIRECTORY": "\n".join(directory), "ACCOUNTS": "\n".join(sections).rstrip(),
        "STATS_ALT": (
            f'{len(accounts)} 个账号，{len(data["categories"])} 个主题，'
            f'{kinds["person"]} 位个人，{kinds["organization"]} 个组织，{kinds["media"]} 家媒体'
        ),
    }
    readme = re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values[m[1]], template)
    require("{{" not in readme, "unresolved README placeholder")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["handle", "name", "url", "category", "kind", "languages", "why",
                     "source_urls", "source_methods", "source_checked_at", "notes"])
    for a in accounts:
        row = [
            a["handle"], a["name"], a["url"], a["category"], a["kind"],
            ";".join(a["languages"]), a["why"],
            ";".join(s["url"] for s in a["sources"]),
            ";".join(s["method"] for s in a["sources"]),
            ";".join(s["checked_at"] for s in a["sources"]), a["notes"],
        ]
        writer.writerow([csv_safe(value) for value in row])
    return {
        "README.md": readme.rstrip() + "\n",
        "docs/sources.md": "\n".join(sources).rstrip() + "\n",
        "data/accounts.csv": "\ufeff" + output.getvalue(),
        "data/handles.txt": "\n".join(a["handle"] for a in accounts) + "\n",
        "assets/stats.svg": stats_svg(len(accounts), len(data["categories"]), kinds),
    }


def check_local_links(root: Path, rendered: dict[str, str]) -> None:
    """Check local Markdown/HTML link targets; external availability is not tested."""
    texts = dict(rendered)
    for path in root.rglob("*.md"):
        if any(p.startswith(".") for p in path.relative_to(root).parts[:-1]):
            continue
        if path.parts[-2] == "templates":
            continue  # Template links resolve from the generated README location.
        texts.setdefault(path.relative_to(root).as_posix(), path.read_text(encoding="utf-8"))
    for pattern in (".github/*.md", ".cursor/rules/*.mdc", ".windsurf/rules/*.md", ".clinerules/*.md"):
        for path in root.glob(pattern):
            texts[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
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
    parser.add_argument("command", choices=["build", "check"])
    args = parser.parse_args()
    try:
        data, schema = load_catalog()
        validate(data, schema)
        outputs = generate(data, (ROOT / "templates/README.md").read_text(encoding="utf-8"))
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
              f'{len(data["categories"])} categories, {len(outputs)} generated files)')
        return 0
    except (CatalogError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"catalog: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
