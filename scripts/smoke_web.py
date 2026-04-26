#!/usr/bin/env python3
"""Lightweight static smoke checks for the Quiet Relay web prototype."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

REQUIRED_WEB_FILES = [
    "index.html",
    "style.css",
    "app.js",
    "manifest.json",
    "service-worker.js",
    "offline.html",
    "icons/icon-192.svg",
    "icons/icon-512.svg",
]

REQUIRED_DATA_FILES = [
    "rules.json",
    "affinities.json",
    "characters.json",
    "skills.json",
    "enemies.json",
    "bosses.json",
    "weapons.json",
    "relics.json",
    "events.json",
    "reward_tables.json",
    "districts.json",
]

MANIFEST_KEYS = [
    "name",
    "short_name",
    "description",
    "start_url",
    "scope",
    "display",
    "background_color",
    "theme_color",
    "icons",
]


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def read_text(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(errors, f"could not read {path.relative_to(ROOT)}: {exc}")
        return ""


def parse_core_assets(service_worker_text: str, errors: list[str]) -> list[str]:
    match = re.search(r"const\s+CORE_ASSETS\s*=\s*(\[[\s\S]*?\]);", service_worker_text)
    if not match:
        fail(errors, "service-worker.js does not define CORE_ASSETS")
        return []
    try:
        assets = ast.literal_eval(match.group(1))
    except (SyntaxError, ValueError) as exc:
        fail(errors, f"service-worker.js CORE_ASSETS is not parseable as a string list: {exc}")
        return []
    if not isinstance(assets, list) or not all(isinstance(item, str) for item in assets):
        fail(errors, "service-worker.js CORE_ASSETS must be a list of strings")
        return []
    return assets


def check_no_external_runtime_dependencies(files: list[Path], errors: list[str]) -> None:
    external_pattern = re.compile(r"https?://(?!localhost(?::\d+)?/)(?!127\.0\.0\.1(?::\d+)?/)")
    banned_terms = ["cdn.", "unpkg", "jsdelivr", "googleapis", "gstatic"]
    for path in files:
        text = read_text(path, errors)
        rel = path.relative_to(ROOT)
        if external_pattern.search(text):
            fail(errors, f"{rel} contains an external http(s) URL")
        lowered = text.lower()
        for term in banned_terms:
            if term in lowered:
                fail(errors, f"{rel} appears to reference external dependency host '{term}'")


def main() -> int:
    errors: list[str] = []

    for relative in REQUIRED_WEB_FILES:
        path = WEB / relative
        if not path.exists():
            fail(errors, f"missing web file: web/{relative}")

    index = read_text(WEB / "index.html", errors)
    for expected in ["./style.css", "./app.js", "./manifest.json"]:
        if expected not in index:
            fail(errors, f"index.html does not reference {expected}")

    app_js = read_text(WEB / "app.js", errors)
    if "serviceWorker" not in app_js or "register" not in app_js:
        fail(errors, "app.js does not appear to register a service worker")
    if "SAVE_SCHEMA_VERSION" not in app_js or "migrateSavePayload" not in app_js:
        fail(errors, "app.js does not expose save schema/migration logic")

    try:
        manifest = json.loads(read_text(WEB / "manifest.json", errors))
    except json.JSONDecodeError as exc:
        fail(errors, f"manifest.json is invalid JSON: {exc}")
        manifest = {}
    for key in MANIFEST_KEYS:
        if key not in manifest:
            fail(errors, f"manifest.json missing key: {key}")
    icon_entries = manifest.get("icons", [])
    icon_sizes = {entry.get("sizes") for entry in icon_entries if isinstance(entry, dict)}
    for size in ["192x192", "512x512"]:
        if size not in icon_sizes:
            fail(errors, f"manifest.json missing {size} icon entry")
    for entry in icon_entries:
        if not isinstance(entry, dict):
            fail(errors, "manifest icon entry is not an object")
            continue
        src = entry.get("src")
        if not src:
            fail(errors, "manifest icon entry missing src")
            continue
        icon_path = (WEB / src.replace("./", "", 1)).resolve()
        if WEB not in icon_path.parents and icon_path != WEB:
            fail(errors, f"manifest icon path escapes web/: {src}")
        elif not icon_path.exists():
            fail(errors, f"manifest icon file missing: {src}")

    service_worker = read_text(WEB / "service-worker.js", errors)
    assets = parse_core_assets(service_worker, errors)
    required_cached = {
        "./index.html",
        "./style.css",
        "./app.js",
        "./manifest.json",
        "./offline.html",
        "./icons/icon-192.svg",
        "./icons/icon-512.svg",
        *{f"./data/{name}" for name in REQUIRED_DATA_FILES},
    }
    missing_cached = sorted(required_cached.difference(assets))
    if missing_cached:
        fail(errors, f"service worker cache is missing: {', '.join(missing_cached)}")
    for asset in assets:
        if asset == "./":
            continue
        asset_path = WEB / asset.replace("./", "", 1)
        if not asset_path.exists():
            fail(errors, f"service worker cached asset does not exist: {asset}")

    for data_name in REQUIRED_DATA_FILES:
        path = WEB / "data" / data_name
        if not path.exists():
            fail(errors, f"missing web data file: web/data/{data_name}")
            continue
        try:
            parsed = json.loads(read_text(path, errors))
        except json.JSONDecodeError as exc:
            fail(errors, f"web/data/{data_name} is invalid JSON: {exc}")
            continue
        if not isinstance(parsed, dict):
            fail(errors, f"web/data/{data_name} must contain a JSON object")

    check_no_external_runtime_dependencies(
        [
            WEB / "index.html",
            WEB / "offline.html",
            WEB / "style.css",
            WEB / "app.js",
            WEB / "service-worker.js",
            WEB / "manifest.json",
        ],
        errors,
    )

    if errors:
        print("Quiet Relay web smoke: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Quiet Relay web smoke: PASS")
    print(f"- checked {len(REQUIRED_WEB_FILES)} web shell files")
    print(f"- checked {len(REQUIRED_DATA_FILES)} JSON data files")
    print(f"- checked {len(assets)} service worker cache entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
