"""
Replace arXiv preprint entries with their published versions.

For every preprint in a .bib file (``@misc`` / ``@unpublished`` entries,
or entries whose journal is arXiv/CoRR), the published version is looked
up the same way ``bibcc add`` does (Semantic Scholar's DOI or DBLP key,
the DOI linked from arXiv, an accepted OpenReview paper, or a CrossRef
record with the same title).

The citation key is kept so ``\\cite`` commands keep working.  The old title
is kept when it matches the published one (it may carry hand-made braces),
custom fields such as ``citation`` are carried over, and arXiv-only fields
(``eprint``, ``archiveprefix``, the arXiv ``url``, ...) are dropped.

By default nothing is written: the changes are saved as a diff under
``.bibcc/``.  Use ``--output`` or ``--in-place`` to write them.

Usage:
    bibcc upgrade refs.bib
    bibcc upgrade refs.bib --in-place
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import bibtexparser

from bibcc.adder import format_entry, polish, suggest_key
from bibcc.bibedit import BibEditError, read_bib, replace_entry, unified_diff, write_bib
from bibcc.helptext import ENV_S2, ENV_VENUES, VENUES_HELP, HelpFormatter, epilog
from bibcc.logging_utils import SEPARATOR_THIN, SEPARATOR_WIDTH, Logger, get_output_dir, write_report
from bibcc.sources import (
    Record,
    clean_title_for_search,
    entry_arxiv_id,
    find_published_by_title,
    is_arxiv_doi,
    normalize_arxiv_id,
    published_from_s2,
    resolve_arxiv,
    s2_match,
    titles_match,
)
from bibcc.venues import VenueLibrary

_PREPRINT_TYPES = {"misc", "unpublished", "techreport", "online", "preprint"}
_PREPRINT_VENUE = re.compile(r"\b(arxiv|corr|preprint)\b", re.IGNORECASE)
# Fields describing the preprint or the paper itself; never carried over.
_REPLACED_FIELDS = {
    "title", "author", "year", "month", "journal", "booktitle", "publisher",
    "volume", "number", "pages", "eprint", "archiveprefix", "primaryclass",
    "eprinttype", "eprintclass", "howpublished",
}


def is_preprint(entry: Dict[str, str]) -> bool:
    """True for arXiv/preprint entries that may have a published version."""
    entry_type = entry.get("ENTRYTYPE", "").lower()
    venue = entry.get("journal") or entry.get("booktitle") or ""
    if entry_type in _PREPRINT_TYPES:
        return not venue or bool(_PREPRINT_VENUE.search(venue))
    return bool(_PREPRINT_VENUE.search(venue))


def find_upgrade(
    entry: Dict[str, str], library: VenueLibrary
) -> Tuple[Optional[Record], Optional[str], List[str]]:
    """Look up the published version of a preprint entry.

    Returns ``(record_or_None, error_or_None, notes)``.
    """
    title = clean_title_for_search(entry.get("title", ""))
    arxiv_id = entry_arxiv_id(entry)
    if arxiv_id:
        found = resolve_arxiv(arxiv_id, library, fallback_title=title)
        return found.published, found.error, found.notes

    if not title:
        return None, "entry has neither an arXiv ID nor a title", []
    paper, error = s2_match(title)
    if paper:
        record, _ = published_from_s2(paper, library)
        if record:
            return record, None, []
    record, cr_error = find_published_by_title(title, library)
    if record:
        return record, None, []
    return None, error or cr_error, []


def _carried_over(entry: Dict[str, str]) -> Dict[str, str]:
    """Old fields worth keeping in the published entry (e.g. ``citation``)."""
    kept = {}
    for name, value in entry.items():
        if name in ("ID", "ENTRYTYPE") or name in _REPLACED_FIELDS:
            continue
        if name == "url" and normalize_arxiv_id(value):
            continue
        if name == "doi" and is_arxiv_doi(value):
            continue
        if name == "note" and _PREPRINT_VENUE.search(value):
            continue
        kept[name] = value
    return kept


def build_upgraded_entry(
    entry: Dict[str, str], record: Record, library: VenueLibrary
) -> Tuple[str, List[str]]:
    """Text of the published entry under the old key, plus notes."""
    fields, notes = polish(record, library)
    old_title = entry.get("title", "")
    if old_title and titles_match(clean_title_for_search(old_title), clean_title_for_search(fields.get("title", ""))):
        fields["title"] = " ".join(old_title.split())
    else:
        notes.append(f"title changed from '{' '.join(old_title.split())}'")
    # Semantic Scholar author names are often abbreviated; arXiv's are not.
    if record.source.startswith("Semantic Scholar") and entry.get("author"):
        fields["author"] = " ".join(entry["author"].split())
    for name, value in _carried_over(entry).items():
        fields.setdefault(name, " ".join(value.split()))

    key = entry["ID"]
    suggested = suggest_key(record.entry_type, fields, set())
    old_venue = key.rsplit("_", 1)[-1]
    new_venue = suggested.rsplit("_", 1)[-1]
    if old_venue != new_venue:
        notes.append(f"key kept as {key}; the convention would end in _{new_venue}")
    return format_entry(record.entry_type, key, fields), notes


def upgrade_bib(
    input_path: str | Path,
    output_path: Optional[str | Path],
    library: VenueLibrary,
    ids: Optional[List[str]] = None,
    delay: float = 1.0,
    log_dir: Optional[Path] = None,
    log: Optional[Callable[[str], None]] = None,
) -> Dict[str, list]:
    """Upgrade preprints in *input_path*; write to *output_path* unless it is None.

    Returns ``{"upgraded": [(key, source)], "unchanged": [(key, reason)],
    "failed": [(key, error)]}``.
    """
    log = log or print
    text = read_bib(input_path)
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    entries = bibtexparser.loads(text, parser=parser).entries
    candidates = [e for e in entries if is_preprint(e) and (not ids or e["ID"] in ids)]
    log(f"🔎 {len(candidates)} preprint entries out of {len(entries)} in {input_path}.")

    upgraded: List[Tuple[str, str]] = []
    unchanged: List[Tuple[str, str]] = []
    failed: List[Tuple[str, str]] = []
    new_text = text

    for n, entry in enumerate(candidates):
        if n and delay:
            time.sleep(delay)
        key = entry["ID"]
        log(f"\n📄 {key}")
        record, error, notes = find_upgrade(entry, library)
        for note in notes:
            log(f"   ℹ️  {note}")
        if record is None:
            if error:
                log(f"   ❌ {error}")
                failed.append((key, error))
            else:
                log("   ⏳ no published version found")
                unchanged.append((key, notes[0] if notes else "no published version found"))
            continue
        entry_text, entry_notes = build_upgraded_entry(entry, record, library)
        try:
            new_text = replace_entry(new_text, key, entry_text)
        except BibEditError as e:
            log(f"   ❌ {e}")
            failed.append((key, str(e)))
            continue
        venue = record.fields.get("journal") or record.fields.get("booktitle") or record.entry_type
        log(f"   ✅ {record.source}: @{record.entry_type} in {venue} ({record.fields.get('year', '')})")
        for note in [*record.notes, *entry_notes]:
            log(f"   ℹ️  {note}")
        upgraded.append((key, record.source))

    output_dir = get_output_dir(input_path, log_dir)
    base = Path(input_path).name
    report = output_dir / f"{base}.upgrade.txt"
    rows = [f"{k}\tupgraded\t{s}" for k, s in upgraded]
    rows += [f"{k}\tunchanged\t{r}" for k, r in unchanged]
    rows += [f"{k}\tfailed\t{e}" for k, e in failed]
    write_report(report, "upgrade: entry_id\tstatus\tdetail", rows)

    log(f"\n{SEPARATOR_THIN * SEPARATOR_WIDTH}")
    log(f"Upgraded {len(upgraded)}; {len(unchanged)} still preprints; {len(failed)} failed.")
    if output_path is None:
        diff = unified_diff(text, new_text, input_path)
        diff_path = output_dir / f"{base}.upgrade.diff"
        if diff:
            diff_path.write_text(diff, encoding="utf-8")
            log(f"🧪 Dry run. Preview: {diff_path}")
            log("💡 To write the changes, run with --output <file.bib> or --in-place")
        log(f"Report: {report}")
    elif upgraded:
        write_bib(output_path, new_text)
        log(f"✅ Saved to {output_path}. Report: {report}")
    return {"upgraded": upgraded, "unchanged": unchanged, "failed": failed}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="""\
Find arXiv preprints in a .bib file that have since been published, and
replace them with the published entry. Preprints are @misc, @unpublished,
@techreport, @online, and @preprint entries without a venue, and any entry
whose journal or booktitle is arXiv, CoRR, or a preprint.

The published version is looked up the same way as in 'bibcc add': the DOI
linked from arXiv or known to Semantic Scholar, an accepted OpenReview paper,
the DBLP key Semantic Scholar reports, or a CrossRef record with the same
title. The replacement keeps the citation key (so \\cite commands keep
working), keeps your title when it matches the published one, keeps custom
fields such as citation, drops arXiv-only fields (eprint, archiveprefix,
primaryclass, the arXiv url), and fills venue fields from the venue library.
The rest of the file stays byte for byte.

Without --output or --in-place this is a dry run that writes the would-be
changes as a diff. Preprints without a published version are listed as
unchanged, with the arXiv comment when it says the paper was accepted.""",
        epilog=epilog(
            examples=[
                ("preview: report and diff in .bibcc/", "bibcc upgrade refs.bib"),
                ("replace the preprints in the file itself", "bibcc upgrade refs.bib --in-place"),
                ("only some entries, written to another file",
                 "bibcc upgrade refs.bib --ids KeyA,KeyB --output out.bib"),
            ],
            outputs=[
                (".bibcc/<input>.upgrade.txt", "upgraded, unchanged, and failed preprints"),
                (".bibcc/<input>.upgrade.diff", "dry run: the changes that would be made"),
                (".bibcc/logs/<input>.upgrader.log", "everything printed to the terminal"),
            ],
            exit_status="0 on success, 1 if any lookup failed (for example rate limits; run\n"
            "again later or set S2_API_KEY), 2 on usage errors.",
            env=[ENV_S2, ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    parser.add_argument("input", help="The .bib file to upgrade.")
    parser.add_argument(
        "--output",
        default="",
        metavar="FILE",
        help="Write the upgraded file here (omit both --output and --in-place for a dry run).",
    )
    parser.add_argument("--in-place", action="store_true", help="Write back to the input file.")
    parser.add_argument(
        "--ids",
        default="",
        metavar="KEYS",
        help="Comma-separated citation keys to upgrade (default: all preprints).",
    )
    parser.add_argument("--venues", default="", metavar="FILE", help=VENUES_HELP)
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="Seconds to wait between entries, to respect API rate limits (default: 1).",
    )
    parser.add_argument(
        "--log-dir",
        default="",
        metavar="DIR",
        help="Directory for reports and logs (default: .bibcc/ next to the input file).",
    )
    return parser


def run(args: argparse.Namespace) -> None:
    if args.in_place and args.output:
        build_parser().error("use either --output or --in-place, not both")
    output = args.input if args.in_place else (args.output or None)
    log_dir = Path(args.log_dir) if args.log_dir else None
    ids = [i.strip() for i in args.ids.split(",") if i.strip()] or None

    with Logger("upgrader", input_file=args.input, log_dir=log_dir) as logger:
        library = VenueLibrary.load(args.venues or None)
        summary = upgrade_bib(
            args.input,
            output,
            library,
            ids=ids,
            delay=args.delay,
            log_dir=log_dir,
            log=logger.log,
        )
    if summary["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    run(build_parser().parse_args())
