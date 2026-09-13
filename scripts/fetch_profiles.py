"""Read one public X profile into a candidate JSON record; never edits the catalog."""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .catalog import CatalogError, load_catalog, require, validate
else:
    from catalog import CatalogError, load_catalog, require, validate


def parse_profile(payload: dict, handle: str, category: str, observed_at: str) -> dict:
    require(isinstance(payload, dict) and payload.get("code") == 200 and isinstance(payload.get("user"), dict), "profile unavailable")
    user = payload["user"]
    require(user.get("screen_name", "").lower() == handle.lower(), "returned handle differs; investigate a possible rename")
    require(user.get("protected") is False, "protected or unspecified profile visibility")
    require(isinstance(user.get("raw_description"), dict) and "text" in user["raw_description"], "missing original bio")
    require(isinstance(user["raw_description"]["text"], str), "invalid original bio")
    require(type(user.get("followers")) is int and user["followers"] >= 0, "missing or invalid exact follower count")
    return {
        "id": user["id"], "handle": user["screen_name"], "name": user["name"],
        "url": "https://x.com/" + user["screen_name"], "category": category,
        "bio": user["raw_description"]["text"], "followers_count": user["followers"],
        "observed_at": observed_at,
        "source_url": "https://api.fxtwitter.com/2/profile/" + handle,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handle", help="X handle, without @")
    parser.add_argument("--category", required=True, help="An existing category ID in data/accounts.json")
    parser.add_argument("--output", type=Path, help="Optional new JSON file; refuses to overwrite an existing file")
    args = parser.parse_args()
    try:
        require(re.fullmatch(r"[A-Za-z0-9_]{1,15}", args.handle) is not None, "invalid X handle")
        data, schema = load_catalog()
        require(args.category in {c["id"] for c in data["categories"]}, "unknown category")
        if args.output:
            require(not args.output.exists(), "output already exists; choose a new candidate path")
        url = "https://api.fxtwitter.com/2/profile/" + args.handle
        request = urllib.request.Request(url, headers={"User-Agent": "awesome-ai-x-accounts/0.3"})
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.load(response)
        record = parse_profile(payload, args.handle, args.category, datetime.now(timezone.utc).isoformat(timespec="seconds"))
        validate(data | {"accounts": [record]}, schema)
        content = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8", newline="\n") as target:
                target.write(content)
            print(f"Candidate saved to {args.output}. Review it before editing data/accounts.json.")
        else:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")
            print(content, end="")
        return 0
    except (CatalogError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"profile: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
