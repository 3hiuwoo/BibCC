"""The release helper and the version/changelog conventions it enforces."""

import importlib.util
import re
from pathlib import Path

import pytest

from bibcc import __version__

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("release", ROOT / ".github" / "scripts" / "release.py")
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)


def _project(tmp_path: Path, version: str, changelog: str) -> Path:
    (tmp_path / "src" / "bibcc").mkdir(parents=True)
    (tmp_path / "src" / "bibcc" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    return tmp_path


CHANGELOG = """\
# Changelog

## [0.3.0] - {date}

### Added

- Something.

## [0.2.0] - 2026-10-20

- Older.

[0.3.0]: https://github.com/3hiuwoo/BibCC/compare/v0.2.0...v0.3.0
"""


def test_top_changelog_section_is_the_package_version():
    version = re.sub(r"\.dev\d+$", "", __version__)
    first = release._HEADING.search((ROOT / "CHANGELOG.md").read_text())
    assert first and first.group("version") == version


def test_check_accepts_a_dated_matching_release(tmp_path: Path):
    root = _project(tmp_path, "0.3.0", CHANGELOG.format(date="2026-11-02"))
    assert release.check("v0.3.0", root) is False
    date, body = release.changelog_section("0.3.0", root)
    assert date == "2026-11-02" and body.startswith("### Added") and "compare" not in body


def test_check_flags_prereleases(tmp_path: Path):
    root = _project(tmp_path, "0.3.0rc1", CHANGELOG.replace("[0.3.0] - {date}", "[0.3.0rc1] - 2026-11-01"))
    assert release.check("v0.3.0rc1", root) is True


@pytest.mark.parametrize(
    "tag,version,date,message",
    [
        ("v0.3.0", "0.3.0", "Unreleased", "set the release date"),
        ("v0.3.0", "0.3.0.dev0", "2026-11-02", "does not match"),
        ("v0.4.0", "0.4.0", "2026-11-02", "no '## [0.4.0]"),
        ("0.3.0", "0.3.0", "2026-11-02", "is not vMAJOR"),
    ],
)
def test_check_rejects_mismatches(tmp_path: Path, tag, version, date, message):
    root = _project(tmp_path, version, CHANGELOG.format(date=date))
    with pytest.raises(SystemExit, match=re.escape(message)):
        release.check(tag, root)
