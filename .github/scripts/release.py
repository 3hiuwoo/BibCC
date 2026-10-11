"""Release checks: the tag, the package version, and the changelog must agree.

    python .github/scripts/release.py check v0.2.0   # exit 1 with a message if they disagree
    python .github/scripts/release.py notes v0.2.0   # print that version's changelog section

``check`` also writes ``prerelease=true|false`` to ``$GITHUB_OUTPUT`` when run
in GitHub Actions.  Standard library only, so it runs before ``uv sync``.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
_HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\](?: - (?P<date>.+?))?\s*$", re.MULTILINE)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def package_version(root: Path = ROOT) -> str:
    text = (root / "src" / "bibcc" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("src/bibcc/__init__.py has no __version__")
    return match.group(1)


def changelog_section(version: str, root: Path = ROOT) -> Optional[Tuple[str, str]]:
    """``(date, body)`` of *version*'s section in CHANGELOG.md, or None."""
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = list(_HEADING.finditer(text))
    for i, match in enumerate(headings):
        if match.group("version") == version:
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            body = text[match.end():end]
            # Drop the link definitions that end the file.
            body = re.sub(r"^\[[^\]]+\]: \S+\s*$", "", body, flags=re.MULTILINE)
            return (match.group("date") or "").strip(), body.strip() + "\n"
    return None


def check(tag: str, root: Path = ROOT) -> bool:
    """Validate a release tag; returns whether it is a pre-release."""
    if not re.fullmatch(r"v\d+\.\d+\.\d+((a|b|rc)\d+)?", tag):
        raise SystemExit(f"tag {tag!r} is not vMAJOR.MINOR.PATCH, optionally followed by a1, b1, or rc1")
    version = tag[1:]
    found = package_version(root)
    if found != version:
        raise SystemExit(f"tag {tag} does not match __version__ = {found!r} in src/bibcc/__init__.py")
    section = changelog_section(version, root)
    if section is None:
        raise SystemExit(f"CHANGELOG.md has no '## [{version}] - YYYY-MM-DD' section")
    date, body = section
    if not _DATE.match(date):
        raise SystemExit(f"CHANGELOG.md section [{version}] is dated {date or '(nothing)'!r}; set the release date")
    if not body.strip():
        raise SystemExit(f"CHANGELOG.md section [{version}] is empty")
    return bool(re.search(r"(a|b|rc)\d+$", version))


def main(argv: list[str]) -> None:
    if len(argv) != 2 or argv[0] not in ("check", "notes"):
        raise SystemExit(__doc__)
    command, tag = argv
    if command == "check":
        prerelease = check(tag)
        print(f"✅ {tag}: version, tag, and changelog agree{' (pre-release)' if prerelease else ''}")
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with open(output, "a", encoding="utf-8") as f:
                f.write(f"prerelease={'true' if prerelease else 'false'}\n")
    else:
        section = changelog_section(tag.lstrip("v"))
        if section is None:
            raise SystemExit(f"CHANGELOG.md has no section for {tag}")
        sys.stdout.write(section[1])


if __name__ == "__main__":
    main(sys.argv[1:])
