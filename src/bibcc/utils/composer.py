#!/usr/bin/env python3
"""
Composer - compose BibTeX files from folders into one .bib file.

This tool supports bibliography projects organized across folders by combining
all `.bib` files into a single composed file with source separators.

Features:
- Recursive discovery of `.bib` files
- Source path separators between files
- Full preservation of original file content (including comments)
- Optional duplicate entry-id warnings

Usage:
    python utils/composer.py compose ./my-bibs combined.bib
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Set, Tuple

from bibcc.logging_utils import Logger

SOURCE_MARKER_PREFIX = "% === source:"
SOURCE_MARKER_SUFFIX = "==="


@dataclass
class ComposeStats:
    """Summary statistics for a composition run."""

    file_count: int
    entry_count: int
    duplicate_count: int


def _extract_entry_ids(raw_text: str) -> List[str]:
    """Extract BibTeX entry IDs from raw text."""
    return [
        match.strip() for match in re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", raw_text)
    ]


def _discover_bib_files(input_dir: Path) -> List[Path]:
    """Discover `.bib` files recursively in deterministic order."""
    files = [p for p in input_dir.rglob("*.bib") if p.is_file()]
    return sorted(files, key=lambda p: str(p).lower())


def compose_bibliographies(
    input_dir: Path,
    output_file: Path,
    warn_duplicates: bool = True,
    log: Callable[[str], None] = print,
) -> ComposeStats:
    """Compose all .bib files under `input_dir` into `output_file`."""
    if not input_dir.exists() or not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    bib_files = _discover_bib_files(input_dir)
    if not bib_files:
        raise ValueError(f"No .bib files found under: {input_dir}")

    output_file.parent.mkdir(parents=True, exist_ok=True)

    all_ids: Dict[str, List[Path]] = {}
    total_entries = 0
    duplicate_ids: Set[str] = set()

    log(f"🔎 Found {len(bib_files)} .bib files under {input_dir}")

    with open(output_file, "w", encoding="utf-8") as out:
        out.write("% Composed by BibCC composer.py\n")
        out.write(f"% Root: {input_dir}\n")
        out.write("\n")

        for idx, bib_path in enumerate(bib_files, 1):
            rel_path = bib_path.relative_to(input_dir)
            marker = (
                f"{SOURCE_MARKER_PREFIX} {rel_path.as_posix()} {SOURCE_MARKER_SUFFIX}"
            )

            out.write(f"{marker}\n")
            raw_text = bib_path.read_text(encoding="utf-8")
            out.write(raw_text)

            if not raw_text.endswith("\n"):
                out.write("\n")
            out.write("\n")

            entry_ids = _extract_entry_ids(raw_text)
            total_entries += len(entry_ids)
            for entry_id in entry_ids:
                all_ids.setdefault(entry_id, []).append(rel_path)

            log(
                f"  [{idx:>3}/{len(bib_files)}] added {rel_path} ({len(entry_ids)} entries)"
            )

    if warn_duplicates:
        for entry_id, paths in all_ids.items():
            if len(paths) > 1:
                duplicate_ids.add(entry_id)

        if duplicate_ids:
            log("\n⚠️  Duplicate BibTeX IDs found across files:")
            for entry_id in sorted(duplicate_ids):
                paths = ", ".join(str(p) for p in all_ids[entry_id])
                log(f"  - {entry_id}: {paths}")
        else:
            log("\n✅ No duplicate BibTeX IDs found across source files.")

    log(f"\n🧩 Composed bibliography written to: {output_file}")
    log(f"   Source files: {len(bib_files)}")
    log(f"   Total entries: {total_entries}")
    log(f"   Duplicate IDs: {len(duplicate_ids)}")

    return ComposeStats(
        file_count=len(bib_files),
        entry_count=total_entries,
        duplicate_count=len(duplicate_ids),
    )


def build_parser() -> argparse.ArgumentParser:
    """Build parser with composer subcommands."""
    parser = argparse.ArgumentParser(
        description="Composer: compose .bib files from folders into one file.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_compose = subparsers.add_parser(
        "compose",
        help="Recursively compose .bib files into one output file.",
    )
    p_compose.add_argument(
        "input_dir",
        type=Path,
        help="Root directory containing .bib files (recursive).",
    )
    p_compose.add_argument(
        "output_file",
        type=Path,
        help="Output composed .bib file.",
    )
    p_compose.add_argument(
        "--no-dup-warning",
        action="store_true",
        help="Disable duplicate entry-id warning.",
    )

    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "compose":
        resolved_input = args.input_dir.resolve()
        resolved_output = args.output_file.resolve()

        if resolved_output.suffix.lower() != ".bib":
            parser.error("output_file must end with .bib")

        with Logger("composer", input_file=str(resolved_output)) as logger:
            compose_bibliographies(
                input_dir=resolved_input,
                output_file=resolved_output,
                warn_duplicates=not args.no_dup_warning,
                log=logger.log,
            )


if __name__ == "__main__":
    main()
