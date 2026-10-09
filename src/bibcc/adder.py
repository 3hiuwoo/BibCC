"""
Add papers to a staging .bib file from a DOI, arXiv ID/URL, or title.

For each identifier the metadata is fetched (see :mod:`bibcc.sources`),
arXiv papers are replaced by their published version when one is found, the
title is title-cased with technical terms brace-protected, venue fields are
filled from the venue library, and a ``METHOD_AUTHOR_VENUEYEAR`` key is
suggested.  Papers already present in the ``--against`` bibliography (same
DOI, arXiv ID, or title) are skipped.

New entries are appended to the staging file only; move them into the
topic files yourself after reviewing them.

Usage:
    bibcc add 10.1109/TPAMI.2024.3429383 2501.13198 --against bib/
    bibcc add --from new_papers.txt --against bib/ --output added.bib
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

import bibtexparser

from bibcc.bibedit import BibEditError, month_macro, read_bib, scan, write_bib
from bibcc.checkers.citation_keys import abbreviate_venue
from bibcc.checkers.smart_protection import find_unprotected_terms, protect_terms
from bibcc.helptext import ENV_S2, ENV_VENUES, VENUES_HELP, HelpFormatter, epilog
from bibcc.logging_utils import SEPARATOR_THIN, SEPARATOR_WIDTH, Logger
from bibcc.sources import (
    Record,
    clean_title_for_search,
    entry_arxiv_id,
    is_arxiv_doi,
    normalize_doi,
    normalize_for_comparison,
    parse_identifier,
    resolve,
)
from bibcc.titlecases import APA_STOPWORDS, suggest_title_case
from bibcc.venues import (
    PROCEEDINGS,
    VenueLibrary,
    normalize_venue,
    previous_edition,
    venue_kind,
)

DEFAULT_OUTPUT = "added.bib"

FIELD_ORDER = [
    "title",
    "author",
    "journal",
    "booktitle",
    "year",
    "month",
    "volume",
    "number",
    "pages",
    "publisher",
    "series",
    "editor",
    "address",
    "venue",
    "isbn",
    "issn",
    "doi",
    "eprint",
    "archiveprefix",
    "primaryclass",
    "url",
]

_NAME_PARTICLES = {"van", "von", "de", "der", "den", "di", "da", "del", "della", "du", "dos", "la", "le", "ter", "ten"}
# Fields fetched as plain text that need LaTeX escaping and dash conversion.
_TEXT_FIELDS = ("title", "author", "journal", "booktitle", "publisher", "series", "venue")


# ------------------------------------------------------------- formatting


def latex_escape(text: str) -> str:
    """Escape ``& % # _`` outside ``$...$`` math, leaving existing escapes alone."""
    parts = re.split(r"(?<!\\)(\$[^$]*\$)", text)
    return "".join(
        part if part.startswith("$") and part.endswith("$") and len(part) > 1
        else re.sub(r"(?<!\\)([&%#_])", r"\\\1", part)
        for part in parts
    )


def _texify(value: str) -> str:
    return latex_escape(value.replace("—", "---").replace("–", "--"))


def format_entry(entry_type: str, key: str, fields: Dict[str, str]) -> str:
    """Format an entry in the survey's style: aligned ``=``, months as macros."""
    names = [n for n in FIELD_ORDER if fields.get(n)]
    names += [n for n in fields if n not in FIELD_ORDER and fields[n]]
    width = max((len(n) for n in names), default=0)
    lines = [f"@{entry_type}{{{key},"]
    for i, name in enumerate(names):
        macro = month_macro(fields[name]) if name == "month" else None
        value = macro or f"{{{fields[name]}}}"
        comma = "," if i < len(names) - 1 else ""
        lines.append(f"  {name.ljust(width)} = {value}{comma}")
    lines.append("}")
    return "\n".join(lines)


# ------------------------------------------------------------------- keys


def _ascii_name(text: str) -> str:
    text = re.sub(r"\\[a-zA-Z]+|\\.", "", text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z'\-]", "", text)


def first_author_surname(author: str) -> str:
    """Surname of the first author, ASCII-folded, particles joined (``vandeVen``)."""
    first = re.split(r"\s+and\s+", author.strip())[0]
    if "," in first:
        surname = first.split(",")[0]
    else:
        tokens = first.split()
        if not tokens:
            return ""
        parts = [tokens[-1]]
        i = len(tokens) - 2
        while i >= 1 and tokens[i].lower() in _NAME_PARTICLES:
            parts.insert(0, tokens[i])
            i -= 1
        surname = "".join(parts)
    return _ascii_name(surname.replace(" ", ""))


def suggest_method(title: str) -> str:
    """Method name from a ``Name: ...`` title prefix, else the first two content words."""
    plain = clean_title_for_search(title)
    m = re.match(r"^\s*([^\s:]{2,30})\s*:", plain)
    if m:
        token = re.sub(r"[^A-Za-z0-9+\-]", "", m.group(1))
        if token:
            return token
    words = [w for w in re.findall(r"[A-Za-z0-9]+", plain) if w.lower() not in APA_STOPWORDS]
    return "".join(w[:1].upper() + w[1:] for w in words[:2]) or "Paper"


def suggest_key(entry_type: str, fields: Dict[str, str], taken: Set[str]) -> str:
    """``METHOD_AUTHOR_VENUEYEAR``, made unique against *taken* (lower-cased keys)."""
    method = suggest_method(fields.get("title", ""))
    author = first_author_surname(fields.get("author", "")) or "Anon"
    if entry_type == "misc" and fields.get("archiveprefix", "").lower() == "arxiv":
        venue = "arXiv"
    else:
        venue = abbreviate_venue(fields.get("journal") or fields.get("booktitle")) or "Venue"
    year = fields.get("year", "")
    key = f"{method}_{author}_{venue}{year}"
    n = 2
    while key.lower() in taken:
        key = f"{method}{n}_{author}_{venue}{year}"
        n += 1
    return key


# ------------------------------------------------------------ duplicates


@dataclass
class Duplicate:
    """An existing entry that is the same paper."""

    key: str
    where: str
    reason: str


def _title_key(title: str) -> str:
    return normalize_for_comparison(clean_title_for_search(title))


class BibIndex:
    """DOI / arXiv ID / title index of existing entries, for duplicate checks."""

    def __init__(self) -> None:
        self._doi: Dict[str, Tuple[str, str]] = {}
        self._arxiv: Dict[str, Tuple[str, str]] = {}
        self._title: Dict[str, Tuple[str, str]] = {}
        self.keys: Set[str] = set()
        self.key_where: Dict[str, str] = {}
        self.files = 0

    def add(self, entry: Dict[str, str], where: str) -> None:
        key = entry.get("ID", "")
        self.keys.add(key.lower())
        self.key_where.setdefault(key.lower(), where)
        loc = (key, where)
        doi = normalize_doi(entry.get("doi", "")).lower()
        if doi and not is_arxiv_doi(doi):
            self._doi.setdefault(doi, loc)
        arxiv_id = entry_arxiv_id(entry)
        if arxiv_id:
            self._arxiv.setdefault(arxiv_id, loc)
        title = _title_key(entry.get("title", ""))
        if title:
            self._title.setdefault(title, loc)

    def add_text(self, text: str, where: str) -> int:
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        entries = bibtexparser.loads(text, parser=parser).entries
        for entry in entries:
            self.add(entry, where)
        return len(entries)

    def add_paths(
        self, paths: Iterable[str | Path], exclude: Optional[Path], log: Callable[[str], None]
    ) -> int:
        """Index .bib files and directories (recursively); returns the entry count."""
        excluded = exclude.resolve() if exclude else None
        count = 0
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                files = sorted(
                    p for p in path.rglob("*.bib")
                    if not any(part.startswith(".") for part in p.relative_to(path).parts)
                )
            elif path.exists():
                files = [path]
            else:
                log(f"⚠️  --against path not found: {path}")
                continue
            for file in files:
                if excluded and file.resolve() == excluded:
                    continue
                try:
                    count += self.add_text(read_bib(file), str(file))
                    self.files += 1
                except Exception as e:  # noqa: BLE001 - a broken file should not stop the run
                    log(f"⚠️  Could not read {file}: {e}")
        return count

    def find(self, doi: str = "", arxiv_id: str = "", title: str = "") -> Optional[Duplicate]:
        doi = normalize_doi(doi).lower()
        if doi and doi in self._doi:
            return Duplicate(*self._doi[doi], reason=f"same DOI {doi}")
        if arxiv_id and arxiv_id in self._arxiv:
            return Duplicate(*self._arxiv[arxiv_id], reason=f"same arXiv ID {arxiv_id}")
        title_key = _title_key(title)
        if title_key and title_key in self._title:
            return Duplicate(*self._title[title_key], reason="same title")
        return None


# ---------------------------------------------------------------- polish


def polish(
    record: Record, library: VenueLibrary, keep_title: bool = False
) -> Tuple[Dict[str, str], List[str]]:
    """Turn a fetched record into BibTeX field values; returns ``(fields, notes)``."""
    fields = {k: _texify(v) if k in _TEXT_FIELDS else v for k, v in record.fields.items() if v}
    notes: List[str] = []

    kind = venue_kind(record.entry_type, fields)
    venue_text = fields.get("journal") or fields.get("booktitle") or ""
    if venue_text:
        result = library.lookup(venue_text, record.fields.get("year"), kind, issn=record.fields.get("issn"))
        if result.venue:
            for name, value in result.venue.fields.items():
                current = fields.get(name)
                if current and normalize_venue(current) != normalize_venue(value):
                    notes.append(f"{name}: library value '{value}' replaces fetched '{current}'")
                fields[name] = value
        elif result.ambiguous:
            labels = ", ".join(v.label for v in result.ambiguous)
            notes.append(f"venue matches several library records ({labels}); fields not filled")
        else:
            year = f" {record.fields.get('year')}" if kind == PROCEEDINGS else ""
            notes.append(
                f"venue '{venue_text}'{year} is not in the venue library; "
                "run `bibcc complete` on the output to get a fill-in YAML"
            )
            prior = (
                previous_edition(library, venue_text, record.fields.get("year", ""))
                if kind == PROCEEDINGS
                else None
            )
            if prior:
                taken = []
                if prior.fields.get("publisher"):
                    fields["publisher"] = prior.fields["publisher"]
                    taken.append("publisher")
                for name in ("issn", "series", "address"):
                    if prior.fields.get(name) and not fields.get(name):
                        fields[name] = prior.fields[name]
                        taken.append(name)
                if taken:
                    notes.append(f"{', '.join(taken)} taken from the {prior.year} edition")

    title = fields.get("title", "").rstrip(".")
    if title:
        if not keep_title:
            title = suggest_title_case(title)
        words = [w for w, _ in find_unprotected_terms(title, fields.get("author", ""))]
        fields["title"] = protect_terms(title, words)
    for name in ("journal", "booktitle"):
        if fields.get(name):
            words = [
                w for w, reason in find_unprotected_terms(fields[name], vocab_terms=[])
                if reason in ("Acronym", "Mixed Case")
            ]
            fields[name] = protect_terms(fields[name], words)
    return fields, notes


# ------------------------------------------------------------------ main


def read_identifiers(path: str | Path) -> List[str]:
    """One identifier per line; blank lines and ``#`` comments are ignored."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _check_entry(text: str, key: str) -> None:
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    entries = bibtexparser.loads(text, parser=parser).entries
    if [e["ID"] for e in entries] != [key]:
        raise BibEditError(f"generated entry '{key}' does not parse back")


def add_papers(
    identifiers: List[str],
    output: str | Path,
    library: VenueLibrary,
    against: Optional[List[str]] = None,
    prefer_published: bool = True,
    keep_title: bool = False,
    dry_run: bool = False,
    delay: float = 1.0,
    log: Optional[Callable[[str], None]] = None,
) -> Dict[str, list]:
    """Resolve *identifiers* and append new entries to *output*.

    Returns ``{"added": [(identifier, key)], "duplicates": [(identifier,
    Duplicate)], "failed": [(identifier, error)]}``.
    """
    log = log or print
    output = Path(output)
    index = BibIndex()
    if against:
        count = index.add_paths(against, exclude=output, log=log)
        log(f"📚 Checking duplicates against {count} entries in {index.files} files.")
    else:
        log("⚠️  No --against bibliography given: duplicates are only checked against the output.")

    old_text = read_bib(output) if output.exists() else ""
    if old_text:
        index.add_text(old_text, str(output))

    added: List[Tuple[str, str]] = []
    duplicates: List[Tuple[str, Duplicate]] = []
    failed: List[Tuple[str, str]] = []
    chunks: List[str] = []

    for n, identifier in enumerate(identifiers):
        if n and delay:
            time.sleep(delay)
        log(f"\n🔎 {identifier}")
        kind, value = parse_identifier(identifier)
        dup = index.find(doi=value if kind == "doi" else "", arxiv_id=value if kind == "arxiv" else "")
        if dup:
            log(f"   ⏭️  Already present as {dup.key} ({dup.where}): {dup.reason}")
            duplicates.append((identifier, dup))
            continue

        result = resolve(identifier, library, prefer_published=prefer_published, log=log)
        record = result.record
        if record is None:
            log(f"   ❌ {result.error}")
            failed.append((identifier, result.error or "not found"))
            continue

        dup = index.find(doi=record.doi, arxiv_id=record.arxiv_id, title=record.fields.get("title", ""))
        if dup:
            hint = ""
            if record.entry_type != "misc" and dup.reason.startswith("same arXiv"):
                hint = " (the bibliography has the preprint; `bibcc upgrade` can replace it)"
            log(f"   ⏭️  Already present as {dup.key} ({dup.where}): {dup.reason}{hint}")
            duplicates.append((identifier, dup))
            continue

        fields, notes = polish(record, library, keep_title=keep_title)
        key = suggest_key(record.entry_type, fields, index.keys)
        entry_text = format_entry(record.entry_type, key, fields)
        try:
            _check_entry(entry_text, key)
        except BibEditError as e:
            log(f"   ❌ {e}")
            failed.append((identifier, str(e)))
            continue

        log(f"   ✅ {record.source}: {key}")
        for note in [*record.notes, *notes]:
            log(f"   ℹ️  {note}")
        log("\n".join("   " + line for line in entry_text.splitlines()))
        index.add({"ID": key, **fields}, str(output))
        added.append((identifier, key))
        chunks.append(entry_text)

    if chunks and not dry_run:
        new_text = old_text.rstrip()
        new_text = (new_text + "\n\n" if new_text else "") + "\n\n".join(chunks) + "\n"
        old_keys = [e.key for e in scan(old_text)] if old_text else []
        if [e.key for e in scan(new_text)] != old_keys + [k for _, k in added]:
            raise BibEditError("appending changed the existing entries of the output file")
        output.parent.mkdir(parents=True, exist_ok=True)
        write_bib(output, new_text)

    log(f"\n{SEPARATOR_THIN * SEPARATOR_WIDTH}")
    target = "(dry run, nothing written)" if dry_run else f"to {output}"
    log(f"Added {len(added)} {target}; {len(duplicates)} already present; {len(failed)} failed.")
    if added and not dry_run:
        log("💡 Review the keys (METHOD is a guess), then run:")
        log(f"   bibcc check {output} --check-keys --title-case --quote")
        log(f"   bibcc complete {output}")
    return {"added": added, "duplicates": duplicates, "failed": failed}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"""\
Fetch papers by DOI, arXiv ID or URL, or title, and append them as BibTeX
entries to a staging file ({DEFAULT_OUTPUT} by default). Review the entries
there, then move them into your topic files.

Metadata comes from CrossRef (DOIs), arXiv (arXiv IDs), and, for titles,
Semantic Scholar, OpenReview, CrossRef, and arXiv; a title only counts as
found when it matches exactly (ignoring case and punctuation). For arXiv
papers the published version is used when one exists (pass --preprint to
keep the arXiv entry).

Each entry is formatted like the rest of the bibliography: Title Case,
{{braces}} around acronyms and technical terms, -- page ranges, month macros,
venue fields from the venue library, and a suggested METHOD_AUTHOR_VENUEYEAR
key (check the METHOD part). Papers already in the --against files or in the
staging file (same DOI, arXiv ID, or title) are skipped.""",
        epilog=epilog(
            examples=[
                ("a DOI and an arXiv ID, skipping papers already in bib/",
                 "bibcc add 10.1109/TPAMI.2024.3429383 2501.13198 --against bib/"),
                ("a paper by its title (quote it)",
                 'bibcc add "SD-LoRA: Scalable Decoupled Low-Rank Adaptation for Class '
                 'Incremental Learning"'),
                ("many papers from a file, one identifier per line",
                 "bibcc add --from new_papers.txt --against bib/ --output new.bib"),
                ("print the entries without writing anything", "bibcc add 2501.13198 --dry-run"),
            ],
            outputs=[
                ("<output>", f"staging file the new entries are appended to (default: {DEFAULT_OUTPUT})"),
                (".bibcc/logs/<output>.adder.log", "everything printed to the terminal"),
            ],
            exit_status="0 if every paper was added or skipped as a duplicate, 1 if any lookup\n"
            "failed or the staging file could not be written safely, 2 on usage errors.",
            env=[ENV_S2, ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    parser.add_argument(
        "identifiers",
        nargs="*",
        metavar="IDENTIFIER",
        help="A DOI (10.xxxx/...), an arXiv ID or URL (2501.13198, arxiv.org/abs/...), "
        "or a quoted title.",
    )
    parser.add_argument(
        "--from",
        dest="from_file",
        default="",
        metavar="FILE",
        help="Read more identifiers from FILE, one per line ('#' starts a comment).",
    )
    parser.add_argument(
        "--against",
        action="append",
        default=[],
        metavar="PATH",
        help="Existing .bib file or directory (searched recursively) to check for "
        "duplicates. Repeatable.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        metavar="FILE",
        help=f"Staging .bib file new entries are appended to (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--venues",
        default="",
        metavar="FILE",
        help=VENUES_HELP,
    )
    parser.add_argument(
        "--preprint",
        action="store_true",
        help="Keep arXiv papers as preprints instead of looking for a published version.",
    )
    parser.add_argument(
        "--keep-title",
        action="store_true",
        help="Do not title-case fetched titles (term protection still applies).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the entries without writing the staging file.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="Seconds to wait between papers, to respect API rate limits (default: 1).",
    )
    parser.add_argument(
        "--log-dir",
        default="",
        metavar="DIR",
        help="Directory for the log (default: .bibcc/logs/ next to the staging file).",
    )
    return parser


def run(args: argparse.Namespace) -> None:
    identifiers = list(args.identifiers)
    if args.from_file:
        identifiers += read_identifiers(args.from_file)
    if not identifiers:
        build_parser().error("give at least one identifier or --from FILE")

    with Logger("adder", input_file=args.output, log_dir=args.log_dir or None) as logger:
        library = VenueLibrary.load(args.venues or None)
        try:
            summary = add_papers(
                identifiers,
                args.output,
                library,
                against=args.against,
                prefer_published=not args.preprint,
                keep_title=args.keep_title,
                dry_run=args.dry_run,
                delay=args.delay,
                log=logger.log,
            )
        except BibEditError as e:
            logger.log(f"❌ Could not write {args.output} safely: {e}")
            sys.exit(1)
    if summary["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    run(build_parser().parse_args())
