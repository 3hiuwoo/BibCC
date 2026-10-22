#!/usr/bin/env python3
"""Build web/vendor/bibcc-bundle.zip: the Python sources the browser runtime needs.

Run with the project interpreter so that the vendored bibtexparser matches the one
bibcc is tested against:

    .venv/bin/python scripts/build_web_bundle.py

Pyodide's micropip can only install wheels, and bibtexparser 1.x publishes an sdist
alone, so it is vendored here instead. PyYAML and pyparsing come from the Pyodide CDN.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "web" / "vendor"
OUT_ZIP = OUT_DIR / "bibcc-bundle.zip"
PROFILES_DIR = ROOT / "web" / "data"

# Shared profiles the browser offers as a one-click library, mirroring `bibcc config profile`.
PROFILES = {
    "config/miaa.yaml": "miaa.config.yaml",
    "terms/miaa.txt": "miaa.terms.txt",
    "venues/miaa.yaml": "miaa.venues.yaml",
}

SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def package_dir(name: str) -> Path:
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.submodule_search_locations:
        sys.exit(f"error: package {name!r} is not importable; install it first (uv sync)")
    return Path(next(iter(spec.submodule_search_locations)))


def add_tree(zf: zipfile.ZipFile, src: Path, arcname: str) -> int:
    count = 0
    for path in sorted(src.rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts) or path.suffix in SKIP_SUFFIXES:
            continue
        if path.is_file():
            zf.write(path, f"{arcname}/{path.relative_to(src).as_posix()}")
            count += 1
    return count


def main() -> None:
    bibcc = package_dir("bibcc")
    bibtexparser = package_dir("bibtexparser")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        n_bibcc = add_tree(zf, bibcc, "bibcc")
        n_bp = add_tree(zf, bibtexparser, "bibtexparser")

    for candidate in sorted(bibtexparser.parent.glob("bibtexparser-*.dist-info/licenses/*")):
        shutil.copyfile(candidate, OUT_DIR / f"BIBTEXPARSER-{candidate.name}")

    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    for rel, name in PROFILES.items():
        src = ROOT / "examples" / rel
        if src.is_file():
            shutil.copyfile(src, PROFILES_DIR / name)
        else:
            print(f"  warning: example profile {rel} is missing", file=sys.stderr)

    size = OUT_ZIP.stat().st_size
    print(f"wrote {OUT_ZIP.relative_to(ROOT)} ({size / 1024:.0f} KiB)")
    print(f"  bibcc        {n_bibcc} files  (from {bibcc})")
    print(f"  bibtexparser {n_bp} files  (from {bibtexparser})")
    print(f"  profiles     {', '.join(sorted(PROFILES.values()))}  (to {PROFILES_DIR.relative_to(ROOT)})")
    if not any(OUT_DIR.glob("BIBTEXPARSER-*")):
        print("  warning: no bibtexparser license text found; add it by hand", file=sys.stderr)


if __name__ == "__main__":
    main()
