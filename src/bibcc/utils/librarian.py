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
    bibcc librarian missing  BIB... LIBRARY [--skip-empty]
    bibcc librarian extra    BIB... LIBRARY
    bibcc librarian rename   BIB_FILE PDF_FOLDER [--dry-run]

BIB is a .bib file or a directory of them; LIBRARY a directory of PDFs or a
listing file.  Reports go to .bibcc/<first BIB>/: missing_pdfs.txt,
extra_pdfs.txt, and rename_report.txt; the log to its logs/librarian.log.
"""

from __future__ import annotations

import argparse
import codecs
import re
import shutil
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

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
            "empty": not span.fields,
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


class LibrarianError(Exception):
    """A .bib path or the library doesn't exist."""


def bib_files(paths: List[Path]) -> List[Path]:
    """The ``.bib`` files of *paths*: files as given, directories searched recursively (hidden ones skipped)."""
    files: List[Path] = []
    for path in paths:
        if path.is_dir():
            files += sorted(
                p for p in path.rglob("*.bib")
                if not any(part.startswith(".") for part in p.relative_to(path).parts)
            )
        elif path.is_file():
            files.append(path)
        else:
            raise LibrarianError(f"not found: {path}")
    return files


def read_library(library: Path) -> Set[str]:
    """The PDF base names in *library*: a directory (searched recursively) or a listing file."""
    if library.suffix.lower() == ".bib":
        raise LibrarianError(f"the last argument is the PDF library (a directory or a listing), not {library}")
    if library.is_dir():
        return {
            p.stem for p in library.rglob("*")
            if p.suffix.lower() == ".pdf" and not any(part.startswith(".") for part in p.relative_to(library).parts)
        }
    if library.is_file():
        return parse_library(library)
    raise LibrarianError(f"library not found: {library}")


def _library_label(library: Path) -> str:
    return f"directory {library}" if library.is_dir() else f"listing {library.name}"


def _collect_entries(
    files: List[Path], log: Callable[[str], None]
) -> List[Tuple[Path, str, Dict[str, str]]]:
    """``(file, key, info)`` for every entry of *files*; a key in several files counts once, in the first."""
    seen: Set[str] = set()
    found: List[Tuple[Path, str, Dict[str, str]]] = []
    for file in files:
        entries = parse_bib_entries(file)
        log(f"Parsed {len(entries)} bib entries from {file}")
        for key, info in entries.items():
            if key not in seen:
                seen.add(key)
                found.append((file, key, info))
    return found


def cmd_missing(
    paths: List[Path],
    library: Path,
    logger: Logger,
    skip_empty: bool = False,
) -> int:
    """Find the entries of *paths* whose ``KEY.pdf`` isn't in *library*; return how many."""
    log = logger.log
    files = bib_files(paths)
    entries = _collect_entries(files, log)
    library_keys = read_library(library)
    log(f"Found {len(library_keys)} PDFs in the library ({_library_label(library)})")

    skipped = [key for _, key, info in entries if skip_empty and info["empty"]]
    if skipped:
        log(f"Skipped {len(skipped)} empty entries (no fields yet): {', '.join(skipped)}")
    considered = [e for e in entries if not (skip_empty and e[2]["empty"])]
    missing = [e for e in considered if e[1] not in library_keys]
    log(f"\n📚 Missing PDFs: {len(missing)} of {len(considered)} entries")

    output_file = report_dir(paths[0]) / "missing_pdfs.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"% Missing PDFs: {len(missing)} / {len(considered)} entries\n")
        f.write(f"% Library size: {len(library_keys)} PDFs\n\n")
        current: Optional[Path] = None
        for file, _, info in missing:
            if len(files) > 1 and file != current:
                f.write(f"% === source: {file} ===\n\n")
                current = file
            f.write(info["raw"])
            f.write("\n\n")
    log(f"\nWrote the missing entries to {output_file}")

    if missing:
        log("\nMissing keys:")
    for file, key, info in missing:
        title = info["title_raw"] or "(no title)"
        where = f" ({file})" if len(files) > 1 else ""
        log(f"  - {key}: {title}{where}")
    return len(missing)


def cmd_extra(
    paths: List[Path],
    library: Path,
    logger: Logger,
) -> int:
    """Find the PDFs in *library* whose name isn't a key in *paths*; return how many."""
    log = logger.log
    entries = _collect_entries(bib_files(paths), log)
    library_keys = read_library(library)
    log(f"Found {len(library_keys)} PDFs in the library ({_library_label(library)})")

    extra_keys = library_keys - {key for _, key, _ in entries}
    log(f"\n📄 Extra PDFs (not in bib): {len(extra_keys)}")

    output_file = report_dir(paths[0]) / "extra_pdfs.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"% PDFs in library but not in bib: {len(extra_keys)} entries\n\n")
        for key in sorted(extra_keys):
            f.write(f"{key}.pdf\n")

    log(f"\nWrote the extra PDFs to {output_file}")

    log("\nExtra keys:")
    for key in sorted(extra_keys):
        log(f"  - {key}")
    return len(extra_keys)


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
step with your .bib files. For details, run 'bibcc librarian SUBCOMMAND -h'.

{_LISTING_HELP}""",
        epilog=epilog(
            examples=[
                ("List the entries that have no PDF yet", "bibcc librarian missing refs.bib ~/papers"),
                ("List the PDFs that have no entry", "bibcc librarian extra bib/ ~/papers"),
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
        description=f"""\
List the entries of the BIB files that have no KEY.pdf in LIBRARY.

Each BIB is a .bib file or a directory, searched recursively for .bib files
(hidden directories such as .bibcc/ are skipped). A key that's in several
files counts once. LIBRARY, the last argument, is a directory of PDFs
(searched recursively) or a listing file.

{_LISTING_HELP}""",
        epilog=epilog(
            examples=[
                ("Check a directory of PDFs", "bibcc librarian missing refs.bib ~/papers"),
                ("Check several files and directories, and skip empty entries",
                 "bibcc librarian missing bib/ extra.bib ~/papers --skip-empty"),
                ("Check against a listing", "ls ~/papers > papers.txt\n"
                 "  bibcc librarian missing refs.bib papers.txt"),
            ],
            outputs=[
                (".bibcc/BIB/missing_pdfs.txt", "The full BibTeX entries without a PDF (next to the first BIB)"),
                (".bibcc/BIB/logs/librarian.log", "Everything printed to the terminal"),
            ],
            exit_status="0 if every entry has a PDF, 1 if some PDFs are missing, 2 on usage errors\n"
            "(for example, a BIB or LIBRARY that doesn't exist).",
        ),
        formatter_class=HelpFormatter,
    )
    p_missing.add_argument("paths", type=Path, nargs="+", metavar="BIB", help="A .bib file or a directory.")
    p_missing.add_argument("library", type=Path, metavar="LIBRARY",
                           help="Directory of PDFs, or a text file listing them.")
    p_missing.add_argument("--skip-empty", action="store_true",
                           help="Skip the empty entries (keys without fields, waiting for their BibTeX).")

    # --- extra ---
    p_extra = subparsers.add_parser(
        "extra",
        help="List library PDFs that have no bib entry.",
        description=f"""\
List the PDFs in LIBRARY whose name isn't a key in any of the BIB files.

Each BIB is a .bib file or a directory, searched recursively for .bib files.
LIBRARY, the last argument, is a directory of PDFs (searched recursively) or a
listing file.

{_LISTING_HELP}""",
        epilog=epilog(
            examples=[
                ("List PDFs without an entry", "bibcc librarian extra bib/ ~/papers"),
                ("Use a listing", "ls ~/papers > papers.txt\n"
                 "  bibcc librarian extra refs.bib papers.txt"),
            ],
            outputs=[
                (".bibcc/BIB/extra_pdfs.txt", "PDF names without an entry (next to the first BIB)"),
                (".bibcc/BIB/logs/librarian.log", "Everything printed to the terminal"),
            ],
        ),
        formatter_class=HelpFormatter,
    )
    p_extra.add_argument("paths", type=Path, nargs="+", metavar="BIB", help="A .bib file or a directory.")
    p_extra.add_argument("library", type=Path, metavar="LIBRARY",
                         help="Directory of PDFs, or a text file listing them.")

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
    first = args.bib_file if args.command == "rename" else args.paths[0]

    status = 0
    with Logger("librarian", input_file=first) as logger:
        try:
            if args.command == "missing":
                status = 1 if cmd_missing(args.paths, args.library, logger, skip_empty=args.skip_empty) else 0
            elif args.command == "extra":
                cmd_extra(args.paths, args.library, logger)
            elif args.command == "rename":
                cmd_rename(args.bib_file, args.pdf_folder, args.dry_run, logger)
        except LibrarianError as e:
            logger.log(f"❌ {e}")
            status = 2
        except BibEditError as e:
            logger.log(f"❌ Cannot read {first}: {e}")
            status = 2
    sys.exit(status)


if __name__ == "__main__":
    main()
