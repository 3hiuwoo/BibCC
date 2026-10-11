"""
BibTeX Completer — fill missing metadata fields from the venue library.

Each journal article or conference paper is matched against the venue
library (the user library merged with the project's ``.bibcc-venues.yaml``,
see :mod:`bibcc.venues`).
Fields the entry lacks are added; fields that differ are reported as
conflicts (in every mode, and in ``.bibcc/<input>/conflicts.txt``) and never
overwritten.  The library is the only source of added fields.

An entry whose booktitle is the interim name of a library record (the CVF
Open Access or OpenReview booktitle of proceedings that are now published
under another name) only receives the fields describing the event (venue
and month), and is reported so ``bibcc upgrade`` can replace it.

Workflow for venues missing from the library:
1. ``bibcc complete refs.bib`` writes ``.bibcc/refs.bib/missing_venues.yaml``
   with fields pre-filled from the bib entries, the previous edition of the
   same conference, and venue-name guesses (see :mod:`bibcc.missing_venues`).
   With ``--online`` CrossRef fills more fields, and every entry with a DOI
   is checked against CrossRef (see :mod:`bibcc.crosscheck`).
2. Fill in the remaining fields in that YAML file.
3. ``bibcc complete refs.bib --output out.bib --update-venues`` merges the
   YAML into the user library (``--scope project``: the project library) and
   completes with the updated library.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import bibtexparser
from bibtexparser.latexenc import latex_to_unicode

from bibcc.bibedit import BibEditError, month_macro, read_bib, set_fields, unified_diff, write_bib
from bibcc.crosscheck import Check, CrossrefCache, check_entry, entry_doi, venue_fields_from_crossref
from bibcc.helptext import ENV_VENUES, SCOPE_HELP, VENUES_HELP, HelpFormatter, epilog
from bibcc.logging_utils import Logger, remove_report, report_dir, write_report
from bibcc.missing_venues import (
    JOURNAL_FIELDS,
    PROCEEDINGS_FIELDS,
    MissingVenue,
    Suggestion,
    update_command,
    write_missing_venues,
)
from bibcc.venues import (
    EVENT_FIELDS,
    JOURNAL,
    SCOPES,
    USER_SCOPE,
    LibraryNotFound,
    Venue,
    VenueLibrary,
    load_library,
    merge_missing_venues,
    normalize_issn,
    normalize_venue,
    open_library,
    venue_kind,
)


def normalize_text(text: Optional[str]) -> str:
    """Normalize text for comparison by removing braces and lowercasing."""
    if not text:
        return ""
    return text.replace("{", "").replace("}", "").strip().lower()


def _comparable(name: str, value: Optional[str]) -> Any:
    """Reduce a field value to what matters when comparing it with the library."""
    if not value:
        return ""
    if name == "issn":
        return frozenset(normalize_issn(value)) or normalize_text(value)
    if name == "isbn":
        return frozenset(re.sub(r"[^0-9X]", "", part.upper()) for part in value.split(",") if part.strip())
    text = latex_to_unicode(value).replace("{", "").replace("}", "")
    return " ".join(text.split()).casefold()


def same_field_value(name: str, existing: Optional[str], library: Optional[str]) -> bool:
    """Whether an entry's field agrees with the library value.

    Braces, case, whitespace, and LaTeX accents (``\\"{a}`` vs ``ä``) are
    ignored; ISBNs and ISSNs compare by their digits, months by macro.
    """
    if name == "month" and month_macro(library) and month_macro(existing) == month_macro(library):
        return True
    return _comparable(name, existing) == _comparable(name, library)


@dataclass
class EntryCompletion:
    """What the venue library says about one entry."""

    status: str  # "matched", "ambiguous", "missing", or "incomplete"
    kind: str = ""
    venue: Optional[Venue] = None
    patch: Dict[str, str] = field(default_factory=dict)
    # (field, existing value, library value)
    conflicts: List[Tuple[str, str, str]] = field(default_factory=list)
    # Set when the booktitle is an interim name ("cvf", "openreview") of ``venue``.
    interim_source: Optional[str] = None
    ambiguous: List[Venue] = field(default_factory=list)


def complete_entry(entry: Mapping[str, str], library: VenueLibrary) -> EntryCompletion:
    """Match one parsed entry against *library* and compute what to add.

    Missing fields are added, differing ones become conflicts, and an entry
    matched through an interim booktitle only gets :data:`EVENT_FIELDS`.
    """
    year = entry.get("year", "")
    venue_raw = entry.get("booktitle") or entry.get("journal") or ""
    kind = venue_kind(entry.get("ENTRYTYPE", ""), entry)
    if not year or not venue_raw:
        return EntryCompletion("incomplete", kind)
    result = library.lookup(venue_raw, year, kind, issn=entry.get("issn"))
    if result.ambiguous:
        return EntryCompletion("ambiguous", kind, ambiguous=result.ambiguous)
    if result.venue is None:
        return EntryCompletion("missing", kind)

    done = EntryCompletion("matched", kind, venue=result.venue, interim_source=result.interim_source)
    for name, value in result.venue.fields.items():
        if result.interim_source and name not in EVENT_FIELDS:
            continue
        if name not in entry:
            done.patch[name] = value
        elif not same_field_value(name, entry.get(name, ""), value):
            done.conflicts.append((name, entry.get(name, ""), value))
    return done


def compute_completion(
    entries: List[Dict[str, Any]],
    library: VenueLibrary,
) -> Dict[str, Any]:
    """Match entries against the library and compute what to add.

    Returns a dict with:
      - ``patches``:    ``{entry_id: {field: value}}`` fields to add
      - ``conflicts``:  ``{entry_id: [(field, existing, library_value)]}``
      - ``ambiguous``:  ``[(entry_id, venue, [labels])]`` several records matched
      - ``interim``:    ``[(entry_id, booktitle, source, Venue)]`` interim booktitles
      - ``matched``:    ``{entry_id: Venue}`` the record each entry matched
      - ``missing``:    ``{(norm_venue, year): (venue, year, type)}`` not in library
      - ``missing_entries``: ``{(norm_venue, year): [entry_id]}``
      - ``collected``:  ``{key: {field: most common value}}`` for pre-filling
      - ``incomplete``: ``[(entry_id, venue, year)]`` entries lacking venue/year
    """
    out: Dict[str, Any] = {
        "patches": {}, "conflicts": {}, "ambiguous": [], "interim": [], "matched": {},
        "missing": {}, "missing_entries": {}, "incomplete": [],
    }
    counters: Dict[Tuple[str, str], Dict[str, Counter]] = {}

    for entry in entries:
        entry_id = entry["ID"]
        year = entry.get("year", "")
        venue_raw = entry.get("booktitle") or entry.get("journal") or ""
        done = complete_entry(entry, library)

        if done.status == "incomplete":
            out["incomplete"].append((entry_id, venue_raw, year))
        elif done.status == "ambiguous":
            out["ambiguous"].append((entry_id, venue_raw, [v.label for v in done.ambiguous]))
        elif done.status == "missing":
            key = (normalize_venue(venue_raw), "" if done.kind == JOURNAL else normalize_text(year))
            out["missing"].setdefault(key, (venue_raw, year, done.kind))
            out["missing_entries"].setdefault(key, []).append(entry_id)
            entry_counters = counters.setdefault(key, {})
            for fname in JOURNAL_FIELDS if done.kind == JOURNAL else PROCEEDINGS_FIELDS:
                val = entry.get(fname, "").strip()
                if val:
                    entry_counters.setdefault(fname, Counter())[val] += 1
        else:
            out["matched"][entry_id] = done.venue
            if done.patch:
                out["patches"][entry_id] = done.patch
            if done.conflicts:
                out["conflicts"][entry_id] = done.conflicts
            if done.interim_source:
                out["interim"].append((entry_id, venue_raw, done.interim_source, done.venue))

    out["collected"] = {
        key: {fname: counter.most_common(1)[0][0] for fname, counter in field_counters.items()}
        for key, field_counters in counters.items()
    }
    return out


def _online_checks(
    entries: List[Dict[str, Any]],
    result: Dict[str, Any],
    cache: CrossrefCache,
    log: Callable[[str], None],
) -> Tuple[List[Check], List[Tuple[str, str]], List[Suggestion], Dict[Tuple[str, str], Dict[str, str]]]:
    """Check entries against CrossRef; returns checks, unchecked entries, suggestions, and CrossRef fills."""
    by_id = {e["ID"]: e for e in entries}
    checks: List[Check] = []
    unchecked: List[Tuple[str, str]] = []
    library_votes: Dict[Tuple[int, str], Dict[str, List[str]]] = {}
    venues_by_id: Dict[int, Venue] = {}

    with_doi = [e for e in entries if entry_doi(e)]
    log(f"\n🌐 Checking {len(with_doi)} entries with a DOI against CrossRef...")
    for entry in entries:
        key = entry["ID"]
        doi = entry_doi(entry)
        if not doi:
            unchecked.append((key, "no DOI"))
            continue
        record, error = cache.get(doi)
        if record is None:
            unchecked.append((key, f"CrossRef: {error or 'no record'}"))
            continue
        venue = result["matched"].get(key)
        kind = venue_kind(entry.get("ENTRYTYPE", ""), entry)
        for check in check_entry(key, entry, kind, venue, record):
            checks.append(check)
            if venue is not None and check.verdict in ("library differs", "bib and library differ") \
                    and check.name not in ("journal", "booktitle"):
                venues_by_id[id(venue)] = venue
                votes = library_votes.setdefault((id(venue), check.name), {})
                votes.setdefault(check.crossref.split(" | ")[0], []).append(f"{key} ({doi})")

    suggestions = []
    for (venue_id, name), votes in library_votes.items():
        if len(votes) != 1:
            continue  # CrossRef itself disagrees between papers of this venue
        value, keys = next(iter(votes.items()))
        evidence = f"CrossRef for {', '.join(keys[:3])}" + (f" and {len(keys) - 3} more" if len(keys) > 3 else "")
        suggestions.append(Suggestion(venues_by_id[venue_id], name, value, evidence))

    fills: Dict[Tuple[str, str], Dict[str, str]] = {}
    for key, ids in result["missing_entries"].items():
        kind = result["missing"][key][2]
        for entry_id in ids:
            record, _ = cache.get(entry_doi(by_id[entry_id]))
            if record is not None:
                fills[key] = venue_fields_from_crossref(record, kind)
                break
    return checks, unchecked, suggestions, fills


def main(
    input_path: str,
    output_path: str,
    dry_run: bool = False,
    log_dir: Path | None = None,
    library: Optional[VenueLibrary] = None,
    log: Optional[Callable[[str], None]] = None,
    online: bool = False,
    delay: float = 1.0,
):
    """Complete *input_path* and write the result to *output_path* unless *dry_run*.

    Only the added fields change in the output; everything else in the file
    is kept byte for byte.  Reports (conflicts, missing venues, incomplete
    entries, and with *online* the CrossRef check) are written in every mode.
    Raises :class:`BibEditError` (and writes nothing) if the edits cannot be
    applied safely.
    """
    log = log or print
    library = library if library is not None else load_library(start=input_path)
    log(f"Reading {input_path}...")
    log(f"📦 Venue library: {library.describe()}")

    with open(input_path, "r", encoding="utf-8") as f:
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        bib_db = bibtexparser.load(f, parser=parser)

    result = compute_completion(bib_db.entries, library)
    patches = result["patches"]
    conflicts = result["conflicts"]
    ambiguous = result["ambiguous"]
    interim = result["interim"]
    missing = result["missing"]
    incomplete_entries = result["incomplete"]

    log(f"  Identified {len(patches)} entries to patch.")

    text = read_bib(input_path)
    new_text, applied = set_fields(text, patches, replace=False)

    output_dir = report_dir(input_path, log_dir)
    conflict_log = output_dir / "conflicts.txt"
    missing_txt_log = output_dir / "missing_venues.txt"
    missing_yaml_log = output_dir / "missing_venues.yaml"
    incomplete_log = output_dir / "incomplete_entries.txt"
    check_log = output_dir / "venue_check.txt"
    diff_log = output_dir / "complete.diff"

    checks: List[Check] = []
    unchecked: List[Tuple[str, str]] = []
    suggestions: List[Suggestion] = []
    fills: Dict[Tuple[str, str], Dict[str, str]] = {}
    if online:
        checks, unchecked, suggestions, fills = _online_checks(
            bib_db.entries, result, CrossrefCache(delay), log
        )

    conflict_rows: List[str] = []
    for eid, rows in conflicts.items():
        for k, existing_val, tmpl_val in rows:
            conflict_rows.append(f"{eid}\t{k}\tEXISTING={existing_val}\tLIBRARY={tmpl_val}")
    for eid, venue_raw, labels in ambiguous:
        conflict_rows.append(f"{eid}\t(venue)\tVENUE={venue_raw}\tAMBIGUOUS={' | '.join(labels)}")
    for eid, venue_raw, source, venue in interim:
        conflict_rows.append(
            f"{eid}\tbooktitle\tEXISTING={venue_raw}\tLIBRARY={venue.name}\t"
            f"({source} booktitle; run bibcc upgrade)"
        )

    missing_rows = [f"{v}\t{y}\t{t}" for v, y, t in missing.values()]
    incomplete_rows = [
        f"{eid}\tvenue={venue or '(empty)'}\tyear={year or '(empty)'}"
        for eid, venue, year in incomplete_entries
    ]

    if dry_run:
        diff = unified_diff(text, new_text, input_path)
        if diff:
            log(f"\n🧪 Dry-run preview ({len(applied)} fields to add):")
            log(diff.rstrip("\n"))
            diff_log.write_text(diff, encoding="utf-8")
        else:
            log("\n🧪 Dry run: no additions needed.")
            remove_report(diff_log)
    else:
        remove_report(diff_log)

    if conflicts:
        log("\n⚠️  Conflicts (existing value differs from library, not overwritten):")
        for eid, conflicts_fields in conflicts.items():
            log(f"Entry ID: {eid}")
            for k, existing_val, tmpl_val in conflicts_fields:
                log(f"  field '{k}': existing='{existing_val}', library='{tmpl_val}'")
    else:
        log("\n✅ No conflicts detected.")

    if interim:
        log("\n⏳ Interim booktitles (only venue and month added; the proceedings are out):")
        for eid, venue_raw, source, venue in interim:
            log(f"  🔸 {eid}: {source} name '{venue_raw}' → proceedings '{venue.name}'")
        log("   Run `bibcc upgrade` on this file to switch them to the proceedings' official BibTeX.")

    if ambiguous:
        log("\n⚠️  Ambiguous venues (several library records match, nothing added):")
        for eid, venue_raw, labels in ambiguous:
            log(f"  🔸 {eid}: '{venue_raw}' matches {', '.join(labels)}")

    if incomplete_entries:
        log("\n📭 Incomplete entries (missing year or venue, such as arXiv or misc entries), skipped:")
        for entry_id, venue, year in incomplete_entries:
            log(f"  🔸 {entry_id}: venue='{venue or '(empty)'}' year='{year or '(empty)'}'")

    if missing:
        log("\nℹ️  Venues not in the library (deduplicated):")
        for venue_raw, year, entry_type in missing.values():
            type_icon = "📰" if entry_type == JOURNAL else "📋"
            log(f"  {type_icon} [{entry_type}] venue='{venue_raw}' year='{year}'")
    else:
        log("\n✅ All complete entries matched the venue library.")

    if online:
        differ = [c for c in checks if c.verdict != "ok"]
        log(f"\n🌐 CrossRef check: {len(checks) - len(differ)} fields agree, {len(differ)} differ, "
            f"{len(unchecked)} entries not checked.")
        for c in differ:
            log(f"  🔸 {c.key} {c.name}: {c.verdict} (bib='{c.bib}', library='{c.library}', "
                f"CrossRef='{c.crossref}')")
        check_rows = [
            f"{c.key}\t{c.name}\t{c.verdict}\tBIB={c.bib}\tLIBRARY={c.library}\tCROSSREF={c.crossref}"
            for c in differ
        ]
        check_rows += [f"{key}\t(not checked)\t{why}" for key, why in unchecked]
        write_report(check_log, "venue check: entry_id\tfield\tverdict\tbib\tlibrary\tcrossref", check_rows)

    write_report(conflict_log, "conflicts: entry_id\tfield\texisting\tlibrary", conflict_rows)
    write_report(missing_txt_log, "missing venues: venue\tyear\ttype", missing_rows)
    write_report(
        incomplete_log,
        "incomplete entries (missing year or venue): entry_id\tvenue\tyear",
        incomplete_rows,
    )

    proposals = [
        MissingVenue(kind, venue_raw, year, collected=result["collected"].get(key, {}),
                     crossref=fills.get(key, {}))
        for key, (venue_raw, year, kind) in missing.items()
    ]
    rerun = update_command(input_path)
    counts = write_missing_venues(missing_yaml_log, proposals, library, rerun, suggestions=suggestions)
    if missing or suggestions:
        log(f"\n📝 Missing venues YAML: {missing_yaml_log} ({counts['new']} new, {counts['kept']} kept)")
        if suggestions:
            log(f"   {len(suggestions)} suggested corrections to library records are at its end (commented out).")
        log(f"   Fill in the fields and run: {rerun}")

    saved = [conflict_log, missing_txt_log, incomplete_log] + ([check_log] if online else [])
    if dry_run:
        if diff:
            saved.append(diff_log)
        log(f"\nReports saved: {', '.join(str(p) for p in saved)}")
        log("💡 To write the changes, run with --output FILE.bib or --in-place.")
        return

    write_bib(output_path, new_text)
    entries_changed = len({a.key for a in applied})
    log(f"\n✅ Added {len(applied)} fields to {entries_changed} entries. Saved to {output_path}")
    if conflicts or ambiguous:
        log(f"⚠️  {len(conflicts)} conflicting and {len(ambiguous)} ambiguous entries left unchanged.")
    log(f"Reports saved: {', '.join(str(p) for p in saved)}")


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for BibTeX completer."""
    parser = argparse.ArgumentParser(
        description="""\
Fill missing venue fields (such as publisher, ISSN, venue location, month,
ISBN, and series) in a .bib file from the venue library. Journals match by
name, alias, or ISSN; proceedings match by name or alias and the entry's
year.

The command never overwrites existing fields: it lists a different value as
a conflict (in every mode). It inserts only the new fields, and the rest of
the file stays byte for byte. Without --output or --in-place, the command
does a dry run and writes the changes that it would make as a diff.

If an entry's booktitle is the CVF Open Access or OpenReview name of
proceedings that the library knows by their published name, the entry gets
only the venue and month. The command lists the entry so that
'bibcc upgrade' can replace it.

The command writes venues that aren't in the library to a fill-in YAML file,
pre-filled from other entries of the same venue and from the previous
edition of a conference. Every run merges into this file instead of
overwriting it. Fill in the rest, and then rerun with --update-venues to add
the venues to the library and complete the file in one step.

The library is your user library merged with the project's
.bibcc-venues.yaml (whose values win); see 'bibcc venues -h'.
--update-venues writes to the user library unless you pass --scope project,
and it logs which file it writes.

--online also queries CrossRef: it pre-fills more of the fill-in YAML, and it
compares each entry that has a DOI, and its library record, with CrossRef
(such as publisher, ISSN, ISBN, pages, and volume). The command only reports
the differences, and it suggests corrections to library records, commented
out, at the end of the YAML. Fields still come only from the library.""",
        epilog=epilog(
            examples=[
                ("Preview the changes (writes .bibcc/refs.bib/complete.diff)", "bibcc complete refs.bib"),
                ("Write the completed file elsewhere", "bibcc complete refs.bib --output out.bib"),
                ("Complete the file itself", "bibcc complete refs.bib --in-place"),
                ("After you fill in .bibcc/refs.bib/missing_venues.yaml, add those venues and complete",
                 "bibcc complete refs.bib --in-place --update-venues"),
                ("Do the same, but add the venues to the project's .bibcc-venues.yaml",
                 "bibcc complete refs.bib --in-place --update-venues --scope project"),
                ("Also check the entries and the library against CrossRef", "bibcc complete refs.bib --online"),
            ],
            outputs=[
                (".bibcc/INPUT/complete.diff", "Dry run: the changes that the command would make"),
                (".bibcc/INPUT/missing_venues.yaml", "Fill-in records for venues that aren't in the library"),
                (".bibcc/INPUT/missing_venues.txt", "Entries whose venue isn't in the library"),
                (".bibcc/INPUT/conflicts.txt", "Fields that differ from the library, and interim booktitles"),
                (".bibcc/INPUT/incomplete_entries.txt", "Entries without a year or venue (skipped)"),
                (".bibcc/INPUT/venue_check.txt", "--online: differences from CrossRef, and unchecked entries"),
                (".bibcc/INPUT/logs/completer.log", "Everything printed to the terminal"),
            ],
            exit_status="0 on success, 1 if BibCC can't verify the edits (it writes nothing), 2 on usage errors.",
            env=[ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    parser.add_argument("input", type=str, help="The .bib file to complete.")
    parser.add_argument(
        "--output",
        type=str,
        default="",
        metavar="FILE",
        help="Write the completed file to FILE. For a dry run, omit both --output and --in-place.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Write the completed entries back to the input file.",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default="",
        metavar="DIR",
        help="Directory to use instead of .bibcc/ next to the input file; reports go to DIR/INPUT/.",
    )
    parser.add_argument(
        "--venues",
        type=str,
        default="",
        metavar="FILE",
        help=VENUES_HELP,
    )
    parser.add_argument(
        "--update-venues",
        "--update-templates",
        dest="update_venues",
        action="store_true",
        help="First merge the filled-in .bibcc/INPUT/missing_venues.yaml into the venue "
        "library that --scope selects (skipping records with no field filled in), and then "
        "complete the file.",
    )
    parser.add_argument("--scope", choices=SCOPES, default=None, help=SCOPE_HELP)
    parser.add_argument(
        "--online",
        action="store_true",
        help="Also query CrossRef: pre-fill the missing-venues YAML, and check entries with a "
        "DOI, and their library records, against CrossRef (report only; off by default).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="With --online, seconds to wait between CrossRef requests (default: 1).",
    )
    return parser


def update_library(args: argparse.Namespace, log_dir: Optional[Path], log: Callable[[str], None]) -> None:
    """Merge the filled-in missing-venues YAML into the one library ``--venues``/``--scope`` names."""
    yaml_path = report_dir(args.input, log_dir) / "missing_venues.yaml"
    if not yaml_path.exists():
        log(f"ℹ️  No {yaml_path.name} found — run without --output first.")
        return
    try:
        target = open_library(args.scope or USER_SCOPE, venues=args.venues or None, start=args.input)
    except LibraryNotFound as e:
        log(f"❌ {e}")
        sys.exit(1)
    label = "library" if args.venues else f"{target.scope} library"
    log(f"🔄 Merging {yaml_path} into the {label} {target.path}...")
    counts = merge_missing_venues(target, yaml_path, log=log)
    if counts["added"] or counts["updated"]:
        target.save()
        log(
            f"✅ {label.capitalize()} updated ({target.path}): +{counts['added']} new, "
            f"~{counts['updated']} updated, {counts['skipped']} skipped.\n"
        )
    else:
        log("ℹ️  Nothing new to merge.\n")


def run(args: argparse.Namespace) -> None:
    """Run completer with parsed arguments."""
    if args.in_place and args.output:
        build_parser().error("use either --output or --in-place, not both")
    if args.scope and not args.update_venues:
        build_parser().error("--scope only applies with --update-venues")
    if args.scope and args.venues:
        build_parser().error("--venues already names the library to update; drop --scope")
    output = args.input if args.in_place else args.output
    dry_run = not bool(output)
    log_dir = Path(args.log_dir) if args.log_dir else None

    with Logger("completer", input_file=args.input, log_dir=log_dir) as logger:
        if args.update_venues:
            update_library(args, log_dir, logger.log)
        library = load_library(args.venues or None, start=args.input)

        try:
            main(
                args.input,
                output or args.input,
                dry_run=dry_run,
                log_dir=log_dir,
                library=library,
                log=logger.log,
                online=args.online,
                delay=args.delay,
            )
        except BibEditError as e:
            logger.log(f"❌ Could not apply the edits safely: {e}")
            logger.log("   Nothing was written.")
            sys.exit(1)


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    run(args)
