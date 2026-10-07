import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(\s*<([^>]+)>|!\[[^\]]*\]\(\s*([^)\s]+)")


def welcome_paths() -> list[str]:
    interface = json.loads((PROJECT_ROOT / "interface.json").read_text(encoding="utf-8"))
    entries = interface["welcome"]
    if isinstance(entries, str):
        entries = [entries]

    paths = []
    for entry in entries:
        assert entry.startswith("$"), f"welcome entry must use an i18n key: {entry}"
        key = entry[1:]
        for locale_name in interface["languages"].values():
            locales = json.loads((PROJECT_ROOT / locale_name).read_text(encoding="utf-8"))
            assert key in locales, f"{key} is missing from {locale_name}"
            paths.append(locales[key])
    return paths


def test_welcome_notices_exist() -> None:
    for relative_path in welcome_paths():
        assert (PROJECT_ROOT / relative_path).is_file(), relative_path


def test_welcome_markdown_images_resolve_from_project_root() -> None:
    for relative_path in welcome_paths():
        content = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        for match in IMAGE_PATTERN.finditer(content):
            target = unquote(next(value for value in match.groups() if value is not None))
            if urlparse(target).scheme:
                continue

            resolved = (PROJECT_ROOT / target).resolve()
            assert resolved.is_relative_to(PROJECT_ROOT), f"image in {relative_path} escapes the project root: {target}"
            assert resolved.is_file(), f"image in {relative_path} is missing: {target}"
