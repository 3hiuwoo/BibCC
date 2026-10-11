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
import codecs
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from bibcc.bibedit import BibEditError, read_bib, scan, unwrap
from bibcc.helptext import HelpFormatter, epilog
from bibcc.logging_utils import SEPARATOR_THIN, SEPARATOR_WIDTH, Logger, report_dir

_LISTING_HELP = """\
The library LISTING is a text file with one PDF name per line, such as the
output of 'ls ~/papers > papers.txt'. The command ignores other text on a
line (such as the dates and sizes of a Windows 'dir' listing), and it reads
both UTF-8 and UTF-16 files. PDF names can't contain spaces."""

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
    content = read_bib(bib_file)

    entries: Dict[str, Dict[str, str]] = {}
    for span in scan(content):
        title = span.fields.get("title")
        title_raw = unwrap(content[title.value_start : title.value_end]).strip() if title else ""
        entries[span.key] = {
            "raw": content[span.start : span.end],
            "title_raw": title_raw,
            "title_norm": normalize_title(title_raw),
        }
    return entries


# ---------------------------------------------------------------------------
# Library (papers.txt) helpers
# ---------------------------------------------------------------------------


def _decode_listing(data: bytes) -> str:
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16")
    # Without a BOM, ASCII-range UTF-16 text has a NUL in every other byte.
    if b"\x00" in data[:2]:
        return data.decode("utf-16-be" if data[0] == 0 else "utf-16-le")
    return data.decode("utf-8-sig")


def parse_library(papers_file: Path) -> Set[str]:
    """Return the set of PDF base names (without .pdf) from a library listing.

    The file may be UTF-16 (e.g. a Windows ``dir`` redirect) or UTF-8/ASCII,
    with or without a byte-order mark.
    """
    keys: Set[str] = set()
    for line in _decode_listing(papers_file.read_bytes()).splitlines():
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
) -> List[str]:
    """Return the keys of all bib entries whose normalised title equals *query_title_norm*.

    Several keys mean the title is ambiguous (e.g. a conference paper and its
    journal version share it), so callers must not pick one.
    """
    if not query_title_norm:
        return []
    return [key for key, info in bib_entries.items() if info["title_norm"] and query_title_norm == info["title_norm"]]


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
    output_file = report_dir(bib_file) / "missing_pdfs.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"% Missing PDFs: {len(missing_keys)} / {len(bib_entries)} entries\n")
        f.write(f"% Library size: {len(library_keys)} PDFs\n\n")
        for key in sorted(missing_keys):
            f.write(bib_entries[key]["raw"])
            f.write("\n\n")

    log(f"\nWrote the missing entries to {output_file.name}")

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
    output_file = report_dir(bib_file) / "extra_pdfs.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"% PDFs in library but not in bib: {len(extra_keys)} entries\n\n")
        for key in sorted(extra_keys):
            f.write(f"{key}.pdf\n")

    log(f"\nWrote the extra PDFs to {output_file.name}")

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
        log(f"❌ PDF directory not found: {pdf_folder}")
        return

    bib_entries = parse_bib_entries(bib_file)
    log(f"Parsed {len(bib_entries)} bib entries from {bib_file.name}")

    pdfs = sorted(pdf_folder.glob("*.pdf"))
    log(f"Found {len(pdfs)} PDFs in {pdf_folder}")

    matched: List[Tuple[str, str]] = []  # (old_name, new_name)
    unmatched: List[str] = []
    ambiguous: List[Tuple[str, List[str]]] = []  # (old_name, candidate keys)

    prefix = "[DRY RUN] " if dry_run else ""
    log(f"\n{prefix}Matching and renaming PDFs:\n")

    for pdf in pdfs:
        query_norm = extract_title_from_filename(pdf.name)
        keys = match_title_to_bib(query_norm, bib_entries)

        if not keys:
            unmatched.append(pdf.name)
            log(f"  ✗ {pdf.name}")
            log("       No match found")
            continue
        if len(keys) > 1:
            ambiguous.append((pdf.name, keys))
            log(f"  ? {pdf.name}")
            log(f"       Several entries have this title, not renamed: {', '.join(keys)}")
            continue

        key = keys[0]
        new_name = f"{key}.pdf"
        new_path = pdf_folder / new_name

        log(f"  ✓ {pdf.name}")
        log(f"       → {new_name}")

        if not dry_run:
            if new_path.exists() and new_path != pdf:
                log("       ⚠️  Target already exists, skipping")
                continue
            shutil.move(str(pdf), str(new_path))

        matched.append((pdf.name, new_name))

    # Summary
    log(f"\n{SEPARATOR_THIN * SEPARATOR_WIDTH}")
    log(f"{prefix}Summary:")
    log(f"  Matched : {len(matched)}")
    log(f"  Unmatched : {len(unmatched)}")
    log(f"  Ambiguous : {len(ambiguous)}")

    if unmatched:
        log("\nUnmatched files:")
        for name in unmatched:
            log(f"  - {name}")

    if ambiguous:
        log("\nAmbiguous files (rename by hand to one of the keys):")
        for name, keys in ambiguous:
            log(f"  - {name}: {', '.join(keys)}")

    if dry_run:
        log(f"\n{prefix}No files renamed. To rename them, run without --dry-run.")

    # Write report
    output_file = report_dir(bib_file) / "rename_report.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(
            f"% Rename report: {len(matched)} matched, {len(unmatched)} unmatched, {len(ambiguous)} ambiguous\n"
        )
        f.write(f"% Source directory: {pdf_folder}\n")
        f.write(f"% {'DRY RUN — no files renamed' if dry_run else 'Applied'}\n\n")

        if matched:
            f.write("% Matched\n")
            for old, new in matched:
                f.write(f"{old}  →  {new}\n")

        if unmatched:
            f.write(f"\n% Unmatched ({len(unmatched)})\n")
            for name in unmatched:
                f.write(f"{name}\n")

        if ambiguous:
            f.write(f"\n% Ambiguous ({len(ambiguous)}): several entries have the title\n")
            for name, keys in ambiguous:
                f.write(f"{name}\t{', '.join(keys)}\n")

    log(f"\nWrote the rename report to {output_file.name}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        description=f"""\
Keep a directory of PDFs named after citation keys (ISPC_Wang_CVPR2024.pdf) in
step with a .bib file. For details, run 'bibcc librarian SUBCOMMAND -h'.

{_LISTING_HELP}""",
        epilog=epilog(
            examples=[
                ("List the entries that have no PDF yet", "bibcc librarian missing refs.bib papers.txt"),
                ("List the PDFs that have no entry", "bibcc librarian extra refs.bib papers.txt"),
                ("Preview renaming downloaded PDFs to their citation keys",
                 "bibcc librarian rename refs.bib ~/Downloads/papers --dry-run"),
            ],
        ),
        formatter_class=HelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="SUBCOMMAND")

    # --- missing ---
    p_missing = subparsers.add_parser(
        "missing",
        help="List bib entries whose PDF isn't in the library.",
        description=f"List the entries of BIB_FILE that have no KEY.pdf in the library.\n\n{_LISTING_HELP}",
        epilog=epilog(
            examples=[("List entries without a PDF", "ls ~/papers > papers.txt\n"
                       "  bibcc librarian missing refs.bib papers.txt")],
            outputs=[
                (".bibcc/BIB_FILE/missing_pdfs.txt", "The full BibTeX entries without a PDF"),
                (".bibcc/BIB_FILE/logs/librarian.log", "Everything printed to the terminal"),
            ],
        ),
        formatter_class=HelpFormatter,
    )
    p_missing.add_argument("bib_file", type=Path, metavar="BIB_FILE", help="The .bib file.")
    p_missing.add_argument("papers_file", type=Path, metavar="LISTING", help="Text file listing the library's PDFs.")

    # --- extra ---
    p_extra = subparsers.add_parser(
        "extra",
        help="List library PDFs that have no bib entry.",
        description=f"List the PDFs in the library whose name isn't a key in BIB_FILE.\n\n{_LISTING_HELP}",
        epilog=epilog(
            examples=[("List PDFs without an entry", "ls ~/papers > papers.txt\n"
                       "  bibcc librarian extra refs.bib papers.txt")],
            outputs=[
                (".bibcc/BIB_FILE/extra_pdfs.txt", "PDF names without an entry"),
                (".bibcc/BIB_FILE/logs/librarian.log", "Everything printed to the terminal"),
            ],
        ),
        formatter_class=HelpFormatter,
    )
    p_extra.add_argument("bib_file", type=Path, metavar="BIB_FILE", help="The .bib file.")
    p_extra.add_argument("papers_file", type=Path, metavar="LISTING", help="Text file listing the library's PDFs.")

    # --- rename ---
    p_rename = subparsers.add_parser(
        "rename",
        help="Rename downloaded PDFs to CITATION_KEY.pdf by matching titles.",
        description="""\
Rename the PDFs in PDF_FOLDER to CITATION_KEY.pdf by matching the title in
each file name against the titles in BIB_FILE.

File names must end with the full title, as Zotero and similar tools export
them: 'Author et al. - 2025 - Full Paper Title.pdf'. The command takes the
text after the last ' - ' as the title. It compares titles ignoring case,
braces, and punctuation, and they must otherwise match exactly. The command
renames files in place and never overwrites an existing KEY.pdf. It doesn't
rename files without a match or files whose title several entries share; it
lists them instead.""",
        epilog=epilog(
            examples=[
                ("Preview the renames", "bibcc librarian rename refs.bib ~/Downloads/papers --dry-run"),
                ("Rename the PDFs", "bibcc librarian rename refs.bib ~/Downloads/papers"),
            ],
            outputs=[
                (".bibcc/BIB_FILE/rename_report.txt", "Old and new names, and unmatched files"),
                (".bibcc/BIB_FILE/logs/librarian.log", "Everything printed to the terminal"),
            ],
        ),
        formatter_class=HelpFormatter,
    )
    p_rename.add_argument("bib_file", type=Path, metavar="BIB_FILE", help="The .bib file.")
    p_rename.add_argument("pdf_folder", type=Path, metavar="PDF_FOLDER", help="Folder with the downloaded PDFs.")
    p_rename.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the renames without renaming anything.",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    with Logger("librarian", input_file=args.bib_file) as logger:
        try:
            if args.command == "missing":
                cmd_missing(args.bib_file, args.papers_file, logger)
            elif args.command == "extra":
                cmd_extra(args.bib_file, args.papers_file, logger)
            elif args.command == "rename":
                cmd_rename(args.bib_file, args.pdf_folder, args.dry_run, logger)
        except BibEditError as e:
            logger.log(f"❌ Cannot read {args.bib_file}: {e}")


if __name__ == "__main__":
    main()
