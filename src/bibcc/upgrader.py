"""
Replace preprints and interim entries with the official BibTeX of their published version.

Three kinds of entries are candidates:

* **Preprints**: ``@misc`` / ``@unpublished`` entries, or entries whose
  journal is arXiv/CoRR.  The published version is looked up the same way
  ``bibcc add`` does (the DOI linked from arXiv or known to Semantic
  Scholar, its DBLP key, an accepted OpenReview paper, or a CrossRef record
  with the same title).
* **Interim entries**: conference papers cited with the CVF Open Access or
  OpenReview booktitle (see :mod:`bibcc.venues`), whose proceedings
  (IEEE Xplore, NeurIPS, ICLR, PMLR) may now be out.
* **Metadata entries**: entries ``bibcc add --fallback`` built from API
  metadata, marked by the comment above them; the comment is removed once
  the entry is replaced by official (or interim) BibTeX.

An entry is only replaced by downloaded official BibTeX (see
:mod:`bibcc.official`).  A preprint whose published version has no
downloadable BibTeX (AAAI, ACM, Elsevier, ECCV papers not on SpringerLink
yet) is kept, and the report gives the venue and where to get the BibTeX by
hand.  A preprint may be replaced by interim BibTeX when that is all there
is yet.

The citation key is kept so ``\\cite`` commands keep working.  The old title
is kept when it matches the published one (it may carry hand-made braces),
custom fields such as ``citation`` are carried over, preprint and interim
fields (``eprint``, ``archiveprefix``, the arXiv/OpenReview/CVF ``url``,
...) are dropped, and venue fields come from the venue library.  Venues
missing from the library, and interim booktitles the upgrade links to their
proceedings, are proposed in ``.bibcc/<input>/missing_venues.yaml``.

By default nothing is written: the changes are saved as a diff under
``.bibcc/``.  Use ``--output`` or ``--in-place`` to write them.
``--report-only`` only lists, for any number of files and directories, the
entries that now have a published version, with its venue and the URL of
its official BibTeX (no BibTeX is downloaded, nothing is changed).

Usage:
    bibcc upgrade refs.bib
    bibcc upgrade refs.bib --in-place
    bibcc upgrade --report-only bib/
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import bibtexparser

from bibcc.adder import (
    BuiltEntry,
    build_entry,
    drop_metadata_comment,
    format_entry,
    metadata_keys,
    suggest_key,
    venue_proposals,
)
from bibcc.bibedit import BibEditError, read_bib, replace_entry, unified_diff, write_bib
from bibcc.helptext import ENV_S2, ENV_VENUES, VENUES_HELP, HelpFormatter, epilog
from bibcc.logging_utils import SEPARATOR_THIN, SEPARATOR_WIDTH, Logger, remove_report, report_dir, write_report
from bibcc.missing_venues import MissingVenue, update_command, write_missing_venues
from bibcc.official import Official, OfficialLookup, find_official, interim_source_of
from bibcc.sources import (
    Record,
    clean_text,
    clean_title_for_search,
    entry_arxiv_id,
    find_published_by_title,
    is_arxiv_doi,
    normalize_arxiv_id,
    normalize_doi,
    published_from_s2,
    resolve_arxiv,
    s2_match,
    titles_match,
)
from bibcc.venues import PROCEEDINGS, VenueLibrary, load_library, normalize_venue

_PREPRINT_TYPES = {"misc", "unpublished", "techreport", "online", "preprint"}
_PREPRINT_VENUE = re.compile(r"\b(arxiv|corr|preprint)\b", re.IGNORECASE)
# Fields describing the preprint, the interim entry, or the paper itself; never carried over.
_REPLACED_FIELDS = {
    "title", "author", "year", "month", "day", "journal", "booktitle", "publisher",
    "volume", "number", "pages", "eprint", "archiveprefix", "primaryclass",
    "eprinttype", "eprintclass", "howpublished", "venue", "isbn", "issn", "series",
    "editor", "address", "doi",
}
_INTERIM_URL = re.compile(r"openreview\.net|thecvf\.com", re.IGNORECASE)

PREPRINT = "preprint"
METADATA = "metadata"


def is_preprint(entry: Dict[str, str]) -> bool:
    """True for arXiv/preprint entries that may have a published version."""
    entry_type = entry.get("ENTRYTYPE", "").lower()
    venue = entry.get("journal") or entry.get("booktitle") or ""
    if entry_type in _PREPRINT_TYPES:
        return not venue or bool(_PREPRINT_VENUE.search(venue))
    return bool(_PREPRINT_VENUE.search(venue))


def candidate_kind(entry: Dict[str, str], library: VenueLibrary, from_metadata: bool = False) -> str:
    """``"metadata"``, ``"preprint"``, an interim source (``"cvf"``, ``"openreview"``), or ``""``.

    *from_metadata* is True for an entry ``bibcc add`` built from metadata
    (see :func:`bibcc.adder.metadata_keys`).
    """
    if from_metadata:
        return METADATA
    if is_preprint(entry):
        return PREPRINT
    if entry.get("ENTRYTYPE", "").lower() != "inproceedings":
        return ""
    booktitle = entry.get("booktitle", "")
    year = entry.get("year", "")
    result = library.lookup(booktitle, year, PROCEEDINGS)
    if result.interim_source:
        return result.interim_source
    return interim_source_of(booktitle, url=entry.get("url", ""), year=year)


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


def record_from_entry(entry: Dict[str, str]) -> Record:
    """A :class:`Record` with an existing entry's identifying fields."""
    fields = {
        name: clean_text(entry.get(name, "").replace("{", "").replace("}", ""))
        for name in ("title", "author", "booktitle", "journal", "year", "url")
        if entry.get(name)
    }
    doi = normalize_doi(entry.get("doi", ""))
    return Record(
        entry_type=entry.get("ENTRYTYPE", "inproceedings").lower(),
        fields=fields,
        source="bib",
        doi="" if is_arxiv_doi(doi) else doi,
        arxiv_id=entry_arxiv_id(entry),
    )


def _carried_over(entry: Dict[str, str]) -> Dict[str, str]:
    """Old fields worth keeping in the published entry (e.g. ``citation``)."""
    kept = {}
    for name, value in entry.items():
        if name in ("ID", "ENTRYTYPE") or name in _REPLACED_FIELDS:
            continue
        if name == "url" and (normalize_arxiv_id(value) or _INTERIM_URL.search(value)):
            continue
        if name == "note" and _PREPRINT_VENUE.search(value):
            continue
        kept[name] = value
    return kept


def build_upgraded_entry(
    entry: Dict[str, str], official: Official, library: VenueLibrary, doi: str = ""
) -> Tuple[str, List[str], BuiltEntry]:
    """Text of the published entry under the old key, notes, and the built entry.

    *doi* is the published version's DOI, added when the official BibTeX has none.
    """
    built = build_entry(official, library, doi=doi)
    fields = built.fields
    notes = list(built.notes)
    old_title = entry.get("title", "")
    if old_title and titles_match(clean_title_for_search(old_title), clean_title_for_search(fields.get("title", ""))):
        fields["title"] = " ".join(old_title.split())
    else:
        notes.append(f"title changed from '{' '.join(old_title.split())}'")
    for name, value in _carried_over(entry).items():
        fields.setdefault(name, " ".join(value.split()))

    key = entry["ID"]
    suggested = suggest_key(built.entry_type, fields, set())
    old_venue = key.rsplit("_", 1)[-1]
    new_venue = suggested.rsplit("_", 1)[-1]
    if old_venue != new_venue:
        notes.append(f"key kept as {key}; the convention would end in _{new_venue}")
    return format_entry(built.entry_type, key, fields), notes, built


def _link_proposals(
    entry: Dict[str, str], source: str, built: BuiltEntry, library: VenueLibrary, proposals: List[MissingVenue]
) -> List[MissingVenue]:
    """Interim booktitle → proceedings links shown by replacing an interim entry."""
    old_name = " ".join(entry.get("booktitle", "").split())
    if not old_name or normalize_venue(old_name) == normalize_venue(built.venue_name):
        return proposals
    evidence = f"{entry['ID']} was '{old_name}' ({source}) and is '{built.venue_name}' in the proceedings"
    for proposal in proposals:
        proposal.interim.setdefault(source, []).append(old_name)
        proposal.notes.append(f"interim booktitle: {evidence}")
        return proposals
    record = library.lookup(built.venue_name, built.year, PROCEEDINGS).venue
    if record is None or normalize_venue(old_name) in record.all_names():
        return proposals
    return [MissingVenue(PROCEEDINGS, record.name, str(record.year), interim={source: [old_name]},
                         notes=[f"links an interim booktitle: {evidence}"], link_only=True)]


def _lookup_for(
    entry: Dict[str, str], kind: str, library: VenueLibrary, download: bool
) -> Tuple[Optional[Record], Optional[OfficialLookup], Optional[str], List[str]]:
    """``(published record, official lookup, error, notes)`` for one candidate."""
    if kind == PREPRINT:
        record, error, notes = find_upgrade(entry, library)
        if record is None:
            return None, None, error, notes
        return record, find_official(record, download=download), None, notes
    record = record_from_entry(entry)
    # Interim BibTeX is still better than metadata; an interim entry is upgraded later.
    interim = kind == METADATA
    return record, find_official(record, download=download, interim=interim), None, []


def _venue_label(record: Record) -> str:
    venue = record.fields.get("journal") or record.fields.get("booktitle") or record.entry_type
    return f"{venue} ({record.fields.get('year', '')})"


def upgrade_bib(
    input_path: str | Path,
    output_path: Optional[str | Path],
    library: VenueLibrary,
    ids: Optional[List[str]] = None,
    delay: float = 1.0,
    log_dir: Optional[Path] = None,
    log: Optional[Callable[[str], None]] = None,
) -> Dict[str, list]:
    """Upgrade candidates in *input_path*; write to *output_path* unless it is None.

    Returns ``{"upgraded": [(key, provider)], "unchanged": [(key, reason)],
    "failed": [(key, error)]}``.
    """
    log = log or print
    text = read_bib(input_path)
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    entries = bibtexparser.loads(text, parser=parser).entries
    marked = metadata_keys(text)
    candidates = [
        (e, kind) for e in entries
        if (not ids or e["ID"] in ids) and (kind := candidate_kind(e, library, e["ID"] in marked))
    ]
    n_preprint = sum(1 for _, kind in candidates if kind == PREPRINT)
    n_metadata = sum(1 for _, kind in candidates if kind == METADATA)
    log(f"🔎 {n_preprint} preprints, {len(candidates) - n_preprint - n_metadata} interim entries, and "
        f"{n_metadata} entries built from metadata out of {len(entries)} in {input_path}.")

    upgraded: List[Tuple[str, str]] = []
    unchanged: List[Tuple[str, str]] = []
    failed: List[Tuple[str, str]] = []
    proposals: List[MissingVenue] = []
    new_text = text

    for n, (entry, kind) in enumerate(candidates):
        if n and delay:
            time.sleep(delay)
        key = entry["ID"]
        label = {PREPRINT: "", METADATA: " (built from metadata)"}.get(kind, f" ({kind} booktitle)")
        log(f"\n📄 {key}{label}")
        record, lookup, error, notes = _lookup_for(entry, kind, library, download=True)
        for note in notes:
            log(f"   ℹ️  {note}")
        if record is None or lookup is None:
            if error:
                log(f"   ❌ {error}")
                failed.append((key, error))
            else:
                log("   ⏳ no published version found")
                unchanged.append((key, notes[0] if notes else "no published version found"))
            continue
        if lookup.official is None:
            if lookup.error:
                log(f"   ❌ could not get the official BibTeX: {lookup.error}")
                failed.append((key, lookup.error))
                continue
            where = f"; get it from {lookup.manual_url}" if lookup.manual_url else ""
            if kind == PREPRINT:
                reason = f"published in {_venue_label(record)}, no official BibTeX: {lookup.reason}{where}"
            elif kind == METADATA:
                reason = f"still no official BibTeX: {lookup.reason}{where}"
            else:
                reason = f"proceedings not available yet: {lookup.reason}{where}"
            log(f"   ⏳ kept: {reason}")
            unchanged.append((key, reason))
            continue

        official = lookup.official
        entry_text, entry_notes, built = build_upgraded_entry(entry, official, library, doi=record.doi)
        try:
            new_text = replace_entry(new_text, key, entry_text)
        except BibEditError as e:
            log(f"   ❌ {e}")
            failed.append((key, str(e)))
            continue
        if kind == METADATA:
            new_text = drop_metadata_comment(new_text, key)
        found = venue_proposals(built, official, library, key, record)
        if kind not in (PREPRINT, METADATA) and not official.interim:
            found = _link_proposals(entry, kind, built, library, found)
        proposals.extend(found)
        log(f"   ✅ {official.provider}: @{built.entry_type} in {built.venue_name} ({built.year})")
        for note in ([lookup.reason] if lookup.reason else []) + [
            n for n in record.notes if not n.startswith("booktitle ")
        ] + entry_notes:
            log(f"   ℹ️  {note}")
        upgraded.append((key, official.provider))

    output_dir = report_dir(input_path, log_dir)
    report = output_dir / "upgrade.txt"
    rows = [f"{k}\tupgraded\t{s}" for k, s in upgraded]
    rows += [f"{k}\tunchanged\t{r}" for k, r in unchanged]
    rows += [f"{k}\tfailed\t{e}" for k, e in failed]
    write_report(report, "upgrade: entry_id\tstatus\tdetail", rows)
    if proposals:
        yaml_path = output_dir / "missing_venues.yaml"
        rerun = update_command(input_path)
        counts = write_missing_venues(yaml_path, proposals, library, rerun)
        log(f"\n📝 {counts['new']} venue records proposed in {yaml_path}")

    log(f"\n{SEPARATOR_THIN * SEPARATOR_WIDTH}")
    log(f"Upgraded {len(upgraded)}; {len(unchanged)} unchanged; {len(failed)} failed.")
    if output_path is None:
        diff = unified_diff(text, new_text, input_path)
        diff_path = output_dir / "upgrade.diff"
        if diff:
            diff_path.write_text(diff, encoding="utf-8")
            log(f"🧪 Dry run. Preview: {diff_path}")
            log("💡 To write the changes, run with --output FILE.bib or --in-place.")
        else:
            remove_report(diff_path)
        log(f"Report: {report}")
        return {"upgraded": upgraded, "unchanged": unchanged, "failed": failed}
    remove_report(output_dir / "upgrade.diff")
    if upgraded:
        write_bib(output_path, new_text)
        log(f"✅ Saved to {output_path}. Report: {report}")
    return {"upgraded": upgraded, "unchanged": unchanged, "failed": failed}


def _bib_files(paths: List[str], log: Callable[[str], None]) -> List[Path]:
    files: List[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files += sorted(
                p for p in path.rglob("*.bib")
                if not any(part.startswith(".") for part in p.relative_to(path).parts)
            )
        elif path.exists():
            files.append(path)
        else:
            log(f"⚠️  not found: {path}")
    return files


def report_published(
    paths: List[str],
    library: VenueLibrary,
    delay: float = 1.0,
    log_dir: Optional[Path] = None,
    log: Optional[Callable[[str], None]] = None,
) -> Dict[str, list]:
    """List candidates in *paths* that now have a published version; change nothing.

    No BibTeX is downloaded: for each such entry the report gives the venue
    and the URL of its official BibTeX (or why there is none).  Returns
    ``{"published": [row], "failed": [(file, key, error)], "checked": n}``.
    """
    log = log or print
    files = _bib_files(paths, log)
    published: List[Tuple[str, str, str, str, str, str]] = []
    failed: List[Tuple[str, str, str]] = []
    checked = 0
    for file in files:
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        try:
            text = read_bib(file)
            entries = bibtexparser.loads(text, parser=parser).entries
            marked = metadata_keys(text)
        except Exception as e:  # noqa: BLE001 - a broken file should not stop the report
            log(f"⚠️  Could not read {file}: {e}")
            continue
        for entry in entries:
            kind = candidate_kind(entry, library, entry["ID"] in marked)
            if not kind:
                continue
            if checked and delay:
                time.sleep(delay)
            checked += 1
            key = entry["ID"]
            record, lookup, error, _ = _lookup_for(entry, kind, library, download=False)
            if record is None or lookup is None:
                if error:
                    log(f"❌ {file}: {key}: {error}")
                    failed.append((str(file), key, error))
                continue
            if lookup.error and lookup.official is None:
                log(f"❌ {file}: {key}: {lookup.error}")
                failed.append((str(file), key, lookup.error))
                continue
            if lookup.official is None and kind != PREPRINT:
                continue  # interim or metadata entry whose official BibTeX is not out yet
            label = _venue_label(record) if kind in (PREPRINT, METADATA) else record.fields.get("booktitle", "")
            if lookup.official:
                status = "interim" if lookup.official.interim else "published"
                if kind == METADATA and not lookup.official.interim:
                    status = "official BibTeX available"
                row = (str(file), key, status, label, lookup.official.provider, lookup.official.url)
                log(f"📗 {key}: {status} — {label}; {lookup.official.provider}: {lookup.official.url}")
            else:
                row = (str(file), key, "published, no official BibTeX", label, lookup.reason, lookup.manual_url)
                log(f"📙 {key}: published — {label}; no official BibTeX ({lookup.reason})")
            published.append(row)

    first = paths[0] if paths else "."
    report = report_dir(first, log_dir) / "published.txt"
    write_report(
        report,
        "published versions: file\tentry_id\tstatus\tvenue\tofficial BibTeX source\turl",
        ["\t".join(row) for row in published] + [f"{f}\t{k}\tfailed\t{e}" for f, k, e in failed],
    )
    log(f"\n{SEPARATOR_THIN * SEPARATOR_WIDTH}")
    log(f"Checked {checked} candidates in {len(files)} files: {len(published)} have a published "
        f"version; {len(failed)} failed. Report: {report}")
    if published:
        log("💡 To replace them, run `bibcc upgrade FILE.bib --in-place`.")
    return {"published": published, "failed": failed, "checked": checked}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="""\
Find preprints and interim entries in a .bib file that are now published,
and replace them with the official BibTeX of the published version.

Preprints are @misc, @unpublished, @techreport, @online, and @preprint
entries without a venue, and any entry whose journal or booktitle is arXiv,
CoRR, or a preprint. The command looks up their published version the same
way as 'bibcc add': the DOI linked from arXiv or known to Semantic Scholar,
an accepted OpenReview paper, the DBLP key that Semantic Scholar reports, or
a CrossRef record with the same title.

Interim entries are conference papers cited with the CVF Open Access
booktitle (CVPR, ICCV, and WACV) or the OpenReview one (NeurIPS, ICLR 2024
and later, and ICML): the venue library's interim names, or an openreview.net
or thecvf.com URL. The command replaces them when the paper is in IEEE
Xplore, the NeurIPS or ICLR proceedings, or PMLR.

Metadata entries are the ones that 'bibcc add --fallback' built from API
metadata, marked by a '% BibCC: not the official BibTeX' comment before them
(keep the comment when you move the entry). The command replaces them, and
removes the comment, when their official BibTeX (or interim CVF or
OpenReview BibTeX) becomes available for download.

The command replaces an entry only with downloaded official BibTeX (for the
sources, see 'bibcc add -h'). If the published version of a preprint has no
official BibTeX (AAAI, ACM, Elsevier, and ECCV papers that aren't on
SpringerLink yet), the command keeps the preprint and lists it with the
venue and where to get the BibTeX by hand. The replacement keeps the
citation key (so \\cite commands keep working), keeps your title when it
matches the published one, keeps custom fields such as citation, drops
preprint fields (eprint, archiveprefix, primaryclass, and the arXiv,
OpenReview, or CVF URL), and adds venue fields from the venue library. The
rest of the file stays byte for byte. The command proposes venues that are
missing from the library in a fill-in YAML file, together with the interim
booktitles that the upgrade linked to their proceedings.

Without --output or --in-place, the command does a dry run and writes the
changes that it would make as a diff. With --report-only, the command only
lists the entries of any number of files and directories that now have a
published version, with the venue and the URL of the official BibTeX; it
downloads no BibTeX and changes nothing.""",
        epilog=epilog(
            examples=[
                ("Preview the changes (writes a report and a diff in .bibcc/refs.bib/)", "bibcc upgrade refs.bib"),
                ("Replace the entries in the file itself", "bibcc upgrade refs.bib --in-place"),
                ("Upgrade only some entries, and write them to another file",
                 "bibcc upgrade refs.bib --ids KeyA,KeyB --output out.bib"),
                ("List which entries of a whole bibliography are now published",
                 "bibcc upgrade --report-only bib/ extra.bib"),
            ],
            outputs=[
                (".bibcc/INPUT/upgrade.txt", "Upgraded, unchanged, and failed entries"),
                (".bibcc/INPUT/upgrade.diff", "Dry run: the changes that the command would make"),
                (".bibcc/INPUT/missing_venues.yaml", "Fill-in records for venues that aren't in the library"),
                (".bibcc/PATH/published.txt", "--report-only: entries with a published version"),
                (".bibcc/INPUT/logs/upgrader.log", "Everything printed to the terminal"),
            ],
            exit_status="0 on success, 1 if a lookup or download fails (for example, because of rate\n"
            "limits; run again later or set S2_API_KEY), 2 on usage errors.",
            env=[ENV_S2, ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="+",
        metavar="PATH",
        help="The .bib file to upgrade (with --report-only, any number of .bib files and "
        "directories).",
    )
    parser.add_argument(
        "--output",
        default="",
        metavar="FILE",
        help="Write the upgraded file to FILE. For a dry run, omit both --output and --in-place.",
    )
    parser.add_argument("--in-place", action="store_true", help="Write the upgraded entries back to the input file.")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Only report the entries that now have a published version, and where to find "
        "its official BibTeX; download nothing and change nothing.",
    )
    parser.add_argument(
        "--ids",
        default="",
        metavar="KEYS",
        help="Comma-separated citation keys to upgrade (default: all candidates).",
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
        help="Directory to use instead of .bibcc/ next to the input file; reports go to DIR/INPUT/.",
    )
    return parser


def run(args: argparse.Namespace) -> None:
    log_dir = Path(args.log_dir) if args.log_dir else None
    if args.report_only:
        if args.output or args.in_place or args.ids:
            build_parser().error("--report-only cannot be combined with --output, --in-place, or --ids")
        with Logger("upgrader", input_file=args.paths[0], log_dir=log_dir) as logger:
            library = load_library(args.venues or None, start=args.paths[0])
            logger.log(f"📦 Venue library: {library.describe()}")
            summary = report_published(args.paths, library, delay=args.delay, log_dir=log_dir, log=logger.log)
        if summary["failed"]:
            sys.exit(1)
        return

    if len(args.paths) != 1 or Path(args.paths[0]).is_dir():
        build_parser().error("give exactly one .bib file (several files or directories need --report-only)")
    if args.in_place and args.output:
        build_parser().error("use either --output or --in-place, not both")
    input_path = args.paths[0]
    output = input_path if args.in_place else (args.output or None)
    ids = [i.strip() for i in args.ids.split(",") if i.strip()] or None

    with Logger("upgrader", input_file=input_path, log_dir=log_dir) as logger:
        library = load_library(args.venues or None, start=input_path)
        logger.log(f"📦 Venue library: {library.describe()}")
        summary = upgrade_bib(
            input_path,
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
