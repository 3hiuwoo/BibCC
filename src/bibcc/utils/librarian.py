#!/usr/bin/env python3
"""
Librarian: Unified alignment between PDF library and bibliography.

Integrates and replaces pdfrenamer.py and missingfinder.py with title-based
matching, eliminating the requirement of temporal order matching.

Supports three modes:
    missing  - Find bib entries whose PDFs are not in the library
    extra    - Find PDFs in the library that are not in the bib
    rename   - Rename new PDFs to match bib keys via title matching

Usage:
    python librarian.py missing  <bib_file> <papers_txt>
    python librarian.py extra    <bib_file> <papers_txt>
    python librarian.py rename   <bib_file> <pdf_folder> [--dry-run]

Output files (auto-generated in repo directory):
    - <bib>.missing_pdfs.txt         Missing PDF entries
    - <bib>.extra_pdfs.txt           Library PDFs not in bib
    - <bib>.rename_report.txt        Rename mapping report
    - <bib>.librarian.log            Execution log
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from bibcc.logging_utils import SEPARATOR_THIN, SEPARATOR_WIDTH, Logger, get_output_dir


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------


def normalize_title(text: Optional[str]) -> str:
    """Normalize a title for fuzzy comparison.

    Strips LaTeX braces, removes punctuation, collapses whitespace, and
    lowercases the result so that minor formatting differences do not prevent a
    match.
    """
    if not text:
        return ""
    # Remove LaTeX braces
    s = text.replace("{", "").replace("}", "")
    # Remove common punctuation (keep alphanumerics and spaces)
    s = re.sub(r"[^a-zA-Z0-9\s]", " ", s)
    # Collapse whitespace and lowercase
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


# ---------------------------------------------------------------------------
# BibTeX helpers
# ---------------------------------------------------------------------------


def parse_bib_entries(bib_file: Path) -> Dict[str, Dict[str, str]]:
    """Parse a .bib file and return a dict keyed by citation key.

    Each value is a dict with at least ``"raw"`` (the full entry text) and
    ``"title"`` (the normalised title extracted from the entry).
    """
    content = bib_file.read_text(encoding="utf-8")

    entries: Dict[str, Dict[str, str]] = {}
    # Match @type{key,
    header_pattern = re.compile(r"@\w+\s*\{\s*([^,]+),")
    # Match title = {…} or title = "…" (greedy within braces, handles nesting)
    title_pattern = re.compile(
        r"^\s*title\s*=\s*\{(.+?)\}\s*[,}]?\s*$",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )

    for header_match in header_pattern.finditer(content):
        key = header_match.group(1).strip()
        start = header_match.start()

        # Walk to find the matching closing brace for the entry
        brace_count = 0
        end = start
        for i, char in enumerate(content[start:], start):
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    end = i + 1
                    break

        raw = content[start:end]

        # Extract title field from the raw entry
        title_raw = ""
        title_match = title_pattern.search(raw)
        if title_match:
            title_raw = title_match.group(1).strip()

        entries[key] = {
            "raw": raw,
            "title_raw": title_raw,
            "title_norm": normalize_title(title_raw),
        }

    return entries


# ---------------------------------------------------------------------------
# Library (papers.txt) helpers
# ---------------------------------------------------------------------------


def parse_library(papers_file: Path) -> Set[str]:
    """Return the set of PDF base names (without .pdf) from a library listing.

    The file may be UTF-16 (e.g. Windows ``dir`` redirect) or UTF-8/ASCII.
    Auto-detects encoding by trying UTF-16 first, then falling back to UTF-8.
    """
    keys: Set[str] = set()
    try:
        text = papers_file.read_text(encoding="utf-16")
    except (UnicodeError, UnicodeDecodeError):
        text = papers_file.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        m = re.search(r"(\S+)\.pdf\b", line, re.IGNORECASE)
        if m:
            keys.add(m.group(1))
    return keys


# ---------------------------------------------------------------------------
# Title extraction from new-PDF filenames
# ---------------------------------------------------------------------------


def extract_title_from_filename(filename: str) -> str:
    """Extract and normalise a title from a downloaded-PDF filename.

    Handles common export formats such as:
        ``Author 等 - 2025 - Some Paper Title.pdf``
        ``Author 等 - Some Paper Title.pdf``
        ``Some Paper Title.pdf``

    The heuristic splits on `` - `` and takes the *last* segment as the title.
    """
    stem = Path(filename).stem  # strip .pdf
    parts = stem.split(" - ")
    title_part = parts[-1].strip()
    return normalize_title(title_part)


# ---------------------------------------------------------------------------
# Title matching engine
# ---------------------------------------------------------------------------


def match_title_to_bib(
    query_title_norm: str,
    bib_entries: Dict[str, Dict[str, str]],
) -> Optional[str]:
    """Find the bib entry whose normalised title exactly matches *query_title_norm*.

    Returns the citation key on match, or ``None`` if no match is found.
    """
    if not query_title_norm:
        return None

    for key, info in bib_entries.items():
        if info["title_norm"] and query_title_norm == info["title_norm"]:
            return key

    return None


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_missing(
    bib_file: Path,
    papers_file: Path,
    logger: Logger,
) -> None:
    """Find bib entries whose PDFs are not in the library."""
    log = logger.log
    bib_entries = parse_bib_entries(bib_file)
    log(f"Parsed {len(bib_entries)} bib entries from {bib_file.name}")

    library_keys = parse_library(papers_file)
    log(f"Found {len(library_keys)} PDFs in library ({papers_file.name})")

    missing_keys = set(bib_entries.keys()) - library_keys
    log(f"\n📚 Missing PDFs: {len(missing_keys)} entries")

    # Write report
    output_file = get_output_dir(bib_file) / f"{bib_file.name}.missing_pdfs.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"% Missing PDFs: {len(missing_keys)} / {len(bib_entries)} entries\n")
        f.write(f"% Library size: {len(library_keys)} PDFs\n\n")
        for key in sorted(missing_keys):
            f.write(bib_entries[key]["raw"])
            f.write("\n\n")

    log(f"\nMissing entries written to {output_file.name}")

    log("\nMissing keys:")
    for key in sorted(missing_keys):
        title = bib_entries[key]["title_raw"] or "(no title)"
        log(f"  - {key}: {title}")


def cmd_extra(
    bib_file: Path,
    papers_file: Path,
    logger: Logger,
) -> None:
    """Find PDFs in the library that have no corresponding bib entry."""
    log = logger.log
    bib_entries = parse_bib_entries(bib_file)
    log(f"Parsed {len(bib_entries)} bib entries from {bib_file.name}")

    library_keys = parse_library(papers_file)
    log(f"Found {len(library_keys)} PDFs in library ({papers_file.name})")

    extra_keys = library_keys - set(bib_entries.keys())
    log(f"\n📄 Extra PDFs (not in bib): {len(extra_keys)}")

    # Write report
    output_file = get_output_dir(bib_file) / f"{bib_file.name}.extra_pdfs.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"% PDFs in library but not in bib: {len(extra_keys)} entries\n\n")
        for key in sorted(extra_keys):
            f.write(f"{key}.pdf\n")

    log(f"\nExtra PDFs written to {output_file.name}")

    log("\nExtra keys:")
    for key in sorted(extra_keys):
        log(f"  - {key}")


def cmd_rename(
    bib_file: Path,
    pdf_folder: Path,
    dry_run: bool,
    logger: Logger,
) -> None:
    """Rename new PDFs to bib-key names via title matching."""
    log = logger.log

    if not pdf_folder.is_dir():
        log(f"❌ PDF folder not found: {pdf_folder}")
        return

    bib_entries = parse_bib_entries(bib_file)
    log(f"Parsed {len(bib_entries)} bib entries from {bib_file.name}")

    pdfs = sorted(pdf_folder.glob("*.pdf"))
    log(f"Found {len(pdfs)} PDFs in {pdf_folder}")

    matched: List[Tuple[str, str]] = []  # (old_name, new_name)
    unmatched: List[str] = []

    prefix = "[DRY RUN] " if dry_run else ""
    log(f"\n{prefix}Matching & renaming PDFs:\n")

    for pdf in pdfs:
        query_norm = extract_title_from_filename(pdf.name)
        key = match_title_to_bib(query_norm, bib_entries)

        if key is None:
            unmatched.append(pdf.name)
            log(f"  ✗ {pdf.name}")
            log(f"       No match found")
            continue

        new_name = f"{key}.pdf"
        new_path = pdf_folder / new_name

        log(f"  ✓ {pdf.name}")
        log(f"       → {new_name}")

        if not dry_run:
            if new_path.exists() and new_path != pdf:
                log(f"       ⚠️  Target already exists, skipping")
                continue
            shutil.move(str(pdf), str(new_path))

        matched.append((pdf.name, new_name))

    # Summary
    log(f"\n{SEPARATOR_THIN * SEPARATOR_WIDTH}")
    log(f"{prefix}Summary:")
    log(f"  Matched : {len(matched)}")
    log(f"  Unmatched : {len(unmatched)}")

    if unmatched:
        log(f"\nUnmatched files:")
        for name in unmatched:
            log(f"  - {name}")

    if dry_run:
        log(f"\n{prefix}No files were renamed. Remove --dry-run to apply.")

    # Write report
    output_file = get_output_dir(bib_file) / f"{bib_file.name}.rename_report.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(
            f"% Rename report: {len(matched)} matched, " f"{len(unmatched)} unmatched\n"
        )
        f.write(f"% Source folder: {pdf_folder}\n")
        f.write(f"% {'DRY RUN — no files renamed' if dry_run else 'Applied'}\n\n")

        if matched:
            f.write("% Matched\n")
            for old, new in matched:
                f.write(f"{old}  →  {new}\n")

        if unmatched:
            f.write(f"\n% Unmatched ({len(unmatched)})\n")
            for name in unmatched:
                f.write(f"{name}\n")

    log(f"\nRename report written to {output_file.name}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        description="Librarian: align PDF library with BibTeX bibliography.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- missing ---
    p_missing = subparsers.add_parser(
        "missing",
        help="Find bib entries whose PDFs are not in the library.",
    )
    p_missing.add_argument("bib_file", type=Path, help="Path to the .bib file")
    p_missing.add_argument("papers_file", type=Path, help="Library listing (.txt)")

    # --- extra ---
    p_extra = subparsers.add_parser(
        "extra",
        help="Find PDFs in the library that are not in the bib.",
    )
    p_extra.add_argument("bib_file", type=Path, help="Path to the .bib file")
    p_extra.add_argument("papers_file", type=Path, help="Library listing (.txt)")

    # --- rename ---
    p_rename = subparsers.add_parser(
        "rename",
        help="Rename new PDFs to bib-key names via title matching.",
    )
    p_rename.add_argument("bib_file", type=Path, help="Path to the .bib file")
    p_rename.add_argument("pdf_folder", type=Path, help="Folder with new PDFs")
    p_rename.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview renames without actually renaming",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    with Logger("librarian", input_file=args.bib_file) as logger:
        if args.command == "missing":
            cmd_missing(args.bib_file, args.papers_file, logger)
        elif args.command == "extra":
            cmd_extra(args.bib_file, args.papers_file, logger)
        elif args.command == "rename":
            cmd_rename(args.bib_file, args.pdf_folder, args.dry_run, logger)


if __name__ == "__main__":
    main()
