"""
BibTeX Completer — fill missing metadata fields from the venue library.

Each journal article or conference paper is matched against the venue
library (``bibcc/data/venues.yaml`` by default, see :mod:`bibcc.venues`).
Fields the entry lacks are added; fields that differ are reported as
conflicts and never overwritten.

Workflow for venues missing from the library:
1. ``bibcc complete refs.bib`` writes ``.bibcc/refs.bib.missing_venues.yaml``
   with fields pre-filled from the bib entries, the previous edition of the
   same conference, and venue-name guesses.
2. Fill in the remaining fields in that YAML file.
3. ``bibcc complete refs.bib --output out.bib --update-venues`` merges the
   YAML into the library and completes with the updated library.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import bibtexparser

from bibcc.logging_utils import Logger, get_output_dir, write_report
from bibcc.venues import (
    JOURNAL,
    PROCEEDINGS,
    Venue,
    VenueLibrary,
    default_library_path,
    merge_missing_venues,
    normalize_venue,
)


def normalize_text(text: Optional[str]) -> str:
    """Normalize text for comparison by removing braces and lowercasing."""
    if not text:
        return ""
    return text.replace("{", "").replace("}", "").strip().lower()


# Publisher inference from venue name patterns
_PUBLISHER_PATTERNS: List[Tuple[str, str]] = [
    ("ieee", "IEEE"),
    ("acm", "Association for Computing Machinery"),
    ("springer", "Springer"),
    ("lecture notes", "Springer"),
    ("elsevier", "Elsevier"),
    ("aaai", "AAAI Press"),
    ("pmlr", "PMLR"),
    ("jmlr", "JMLR"),
    ("nature", "Springer Nature"),
    ("wiley", "Wiley"),
    ("mdpi", "MDPI"),
    ("oxford", "Oxford University Press"),
    ("cambridge", "Cambridge University Press"),
]

# Known conference month patterns
_CONFERENCE_MONTHS: Dict[str, str] = {
    "cvpr": "June",
    "iccv": "October",
    "eccv": "October",
    "neurips": "December",
    "nips": "December",
    "icml": "July",
    "iclr": "May",
    "aaai": "February",
    "ijcai": "August",
    "acl": "July",
    "emnlp": "November",
    "naacl": "June",
    "kdd": "August",
    "sigir": "July",
    "www": "May",
    "mm": "October",
    "interspeech": "September",
    "bmvc": "November",
    "wacv": "January",
    "miccai": "October",
    "coling": "October",
}


# Fields to collect from bib entries for pre-filling the missing-venues YAML
_JOURNAL_COLLECT_FIELDS = ["publisher", "issn", "address"]
_PROCEEDINGS_COLLECT_FIELDS = [
    "venue",
    "publisher",
    "month",
    "isbn",
    "issn",
    "editor",
    "series",
    "address",
]

# Fields that usually stay the same from one conference edition to the next.
_EDITION_STABLE_FIELDS = ["publisher", "issn", "month", "series", "address"]


def _guess_publisher(venue: str) -> str:
    """Infer publisher from venue name patterns. Returns empty string if unknown."""
    lower = venue.lower()
    for pattern, publisher in _PUBLISHER_PATTERNS:
        if pattern in lower:
            return publisher
    return ""


def _guess_month(venue: str) -> str:
    """Infer conference month from known conference name patterns."""
    lower = venue.lower()
    for pattern, month in _CONFERENCE_MONTHS.items():
        if re.search(rf"\b{re.escape(pattern)}\b", lower):
            return month
    return ""


def _edition_key(name: str) -> str:
    """Venue name with years and ordinals removed, to relate editions."""
    text = normalize_venue(name)
    text = re.sub(r"\b(19|20)\d{2}\b", "#", text)
    text = re.sub(r"\b\d+(st|nd|rd|th)\b", "#", text)
    text = re.sub(
        r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
        r"eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|"
        r"eighteenth|nineteenth|twentieth|thirtieth|fortieth)\b",
        "#",
        text,
    )
    text = re.sub(r"\b(twenty|thirty|forty)-#", "#", text)
    return " ".join(text.split())


def previous_edition(library: VenueLibrary, name: str, year: str) -> Optional[Venue]:
    """Most recent earlier proceedings record of the same conference series."""
    key = _edition_key(name)
    best: Optional[Venue] = None
    for venue in library.proceedings:
        if _edition_key(venue.name) != key or not str(venue.year).isdigit():
            continue
        if year.isdigit() and int(venue.year) >= int(year):
            continue
        if best is None or int(venue.year) > int(best.year):
            best = venue
    return best


def _yaml_str(value: str) -> str:
    """Quote a string as a YAML double-quoted scalar (JSON escaping is valid YAML)."""
    return json.dumps(value, ensure_ascii=False)


def _write_yaml_missing_venues(
    path: Path,
    missing: Dict[Tuple[str, str], Tuple[str, str, str]],
    library: VenueLibrary,
    bib_collected: Optional[Dict[Tuple[str, str], Dict[str, str]]] = None,
) -> None:
    """Write venues missing from the library to a YAML file for the user to fill in.

    The file uses the library schema, so ``--update-venues`` can merge it
    directly. Fields are pre-filled from (highest priority first):
      1. Values found in the bib entries (``# from bib``)
      2. The previous edition of the same conference (``# from <year>``)
      3. Guesses from the venue name (``# auto-guessed``)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    bib_collected = bib_collected or {}

    sections: Dict[str, List[str]] = {JOURNAL: [], PROCEEDINGS: []}

    for key, (venue_raw, year, entry_type) in missing.items():
        collected = bib_collected.get(key, {})
        prior = previous_edition(library, venue_raw, year) if entry_type == PROCEEDINGS else None
        lines = sections[entry_type]
        lines.append(f"  - name: {_yaml_str(venue_raw)}")
        if entry_type == PROCEEDINGS:
            lines.append(f"    year: {_yaml_str(year)}")
        lines.append("    # aliases: []  # other spellings of this venue")
        lines.append("    fields:")

        def resolve(name: str, guessed: str = "", hint: str = "", optional: bool = False) -> None:
            value, comment = "", f"  {hint}" if hint else ""
            if collected.get(name):
                value, comment = collected[name], "  # from bib"
            elif prior and name in _EDITION_STABLE_FIELDS and prior.fields.get(name):
                value, comment = prior.fields[name], f"  # from {prior.year} edition"
            elif guessed:
                value, comment = guessed, "  # auto-guessed"
            prefix = "# " if optional and not value else ""
            lines.append(f"      {prefix}{name}: {_yaml_str(value)}{comment}")

        guessed_publisher = _guess_publisher(venue_raw)
        if entry_type == JOURNAL:
            resolve("publisher", guessed_publisher, "# e.g., IEEE, Elsevier, Springer")
            resolve("issn")
            resolve("address", hint="# optional, e.g., New York, NY, USA", optional=True)
        else:
            resolve("venue", hint="# e.g., City, Country")
            resolve("publisher", guessed_publisher)
            resolve("month", _guess_month(venue_raw), "# e.g., June, October")
            for name in ("isbn", "issn", "editor", "series", "address"):
                resolve(name, optional=True)
        lines.append("")

    out = [
        "# Venues missing from the BibCC venue library.",
        "# Fill in the fields, then run:",
        "#   bibcc complete <input.bib> --output <out.bib> --update-venues",
        "#",
        "# '# from bib'          value found in your entries",
        "# '# from <year> edition' value copied from the previous edition in the library",
        "# '# auto-guessed'      inferred from the venue name; please verify",
        "# Records whose fields are all empty are skipped when merging.",
        "",
    ]
    for kind, key in ((JOURNAL, "journals"), (PROCEEDINGS, "proceedings")):
        if sections[kind]:
            out.append(f"{key}:")
            out.extend(sections[kind])

    path.write_text("\n".join(out), encoding="utf-8")


def _detect_entry_type(entry: Dict[str, Any]) -> str:
    """Detect if an entry is a journal article or proceedings."""
    entry_type = entry.get("ENTRYTYPE", "").lower()

    if entry_type == "article":
        return JOURNAL
    if entry_type in ("inproceedings", "proceedings", "conference"):
        return PROCEEDINGS

    if entry.get("journal"):
        return JOURNAL
    if entry.get("booktitle"):
        return PROCEEDINGS

    return PROCEEDINGS


def compute_completion(
    entries: List[Dict[str, Any]],
    library: VenueLibrary,
) -> Dict[str, Any]:
    """Match entries against the library and compute what to add.

    Returns a dict with:
      - ``patches``:    ``{entry_id: {field: value}}`` fields to add
      - ``conflicts``:  ``{entry_id: [(field, existing, library_value)]}``
      - ``ambiguous``:  ``[(entry_id, venue, [labels])]`` several records matched
      - ``missing``:    ``{(norm_venue, year): (venue, year, type)}`` not in library
      - ``collected``:  ``{key: {field: most common value}}`` for pre-filling
      - ``incomplete``: ``[(entry_id, venue, year)]`` entries lacking venue/year
    """
    patches: Dict[str, Dict[str, str]] = {}
    conflicts: Dict[str, List[Tuple[str, str, str]]] = {}
    ambiguous: List[Tuple[str, str, List[str]]] = []
    missing: Dict[Tuple[str, str], Tuple[str, str, str]] = {}
    counters: Dict[Tuple[str, str], Dict[str, Counter]] = {}
    incomplete: List[Tuple[str, str, str]] = []

    for entry in entries:
        entry_id = entry["ID"]
        year = entry.get("year", "")
        venue_raw = entry.get("booktitle") or entry.get("journal") or ""
        entry_type = _detect_entry_type(entry)

        if not year or not venue_raw:
            incomplete.append((entry_id, venue_raw, year))
            continue

        result = library.lookup(venue_raw, year, entry_type, issn=entry.get("issn"))
        if result.ambiguous:
            ambiguous.append((entry_id, venue_raw, [v.label for v in result.ambiguous]))
            continue

        if result.venue is None:
            key = (normalize_venue(venue_raw), "" if entry_type == JOURNAL else normalize_text(year))
            missing.setdefault(key, (venue_raw, year, entry_type))
            collect_fields = (
                _JOURNAL_COLLECT_FIELDS if entry_type == JOURNAL else _PROCEEDINGS_COLLECT_FIELDS
            )
            entry_counters = counters.setdefault(key, {})
            for fname in collect_fields:
                val = entry.get(fname, "").strip()
                if val:
                    entry_counters.setdefault(fname, Counter())[val] += 1
            continue

        fields_to_add = {}
        entry_conflicts = []
        for k, v in result.venue.fields.items():
            if k not in entry:
                fields_to_add[k] = v
            elif normalize_text(entry.get(k, "")) != normalize_text(v):
                entry_conflicts.append((k, entry.get(k, ""), v))

        if fields_to_add:
            patches[entry_id] = fields_to_add
        if entry_conflicts:
            conflicts[entry_id] = entry_conflicts

    collected = {
        key: {fname: counter.most_common(1)[0][0] for fname, counter in field_counters.items()}
        for key, field_counters in counters.items()
    }
    return {
        "patches": patches,
        "conflicts": conflicts,
        "ambiguous": ambiguous,
        "missing": missing,
        "collected": collected,
        "incomplete": incomplete,
    }


def main(
    input_path: str,
    output_path: str,
    dry_run: bool = False,
    log_dir: Path | None = None,
    library: Optional[VenueLibrary] = None,
    log: Optional[Callable[[str], None]] = None,
):
    """Complete *input_path* and write the result to *output_path* unless *dry_run*."""
    log = log or print
    library = library if library is not None else VenueLibrary.load()
    log(f"Reading {input_path}...")
    log(
        f"📦 Venue library: {library.path} "
        f"({len(library.journals)} journals, {len(library.proceedings)} proceedings)"
    )

    with open(input_path, "r", encoding="utf-8") as f:
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        bib_db = bibtexparser.load(f, parser=parser)

    result = compute_completion(bib_db.entries, library)
    patches = result["patches"]
    conflicts = result["conflicts"]
    ambiguous = result["ambiguous"]
    missing = result["missing"]
    incomplete_entries = result["incomplete"]

    log(f"  Identified {len(patches)} entries to patch.")

    output_dir = get_output_dir(input_path, log_dir)
    base = Path(input_path).name
    conflict_log = output_dir / f"{base}.conflicts.txt"
    missing_txt_log = output_dir / f"{base}.missing_venues.txt"
    missing_yaml_log = output_dir / f"{base}.missing_venues.yaml"
    incomplete_log = output_dir / f"{base}.incomplete_entries.txt"

    conflict_rows: List[str] = []
    for eid, rows in conflicts.items():
        for k, existing_val, tmpl_val in rows:
            conflict_rows.append(f"{eid}\t{k}\tEXISTING={existing_val}\tLIBRARY={tmpl_val}")
    for eid, venue_raw, labels in ambiguous:
        conflict_rows.append(f"{eid}\t(venue)\tVENUE={venue_raw}\tAMBIGUOUS={' | '.join(labels)}")

    missing_rows = [f"{v}\t{y}\t{t}" for v, y, t in missing.values()]
    incomplete_rows = [
        f"{eid}\tvenue={venue or '(empty)'}\tyear={year or '(empty)'}"
        for eid, venue, year in incomplete_entries
    ]

    if dry_run:
        if patches:
            log("\n🧪 Dry-run additions:")
            for eid, fields in patches.items():
                log(f"Entry ID: {eid}")
                for k, v in fields.items():
                    log(f"    add {k} = {{{v}}}")
        else:
            log("\n🧪 Dry-run: no additions needed.")

        if conflicts:
            log("\n⚠️  Conflicts (existing value differs from library, not overwritten):")
            for eid, conflicts_fields in conflicts.items():
                log(f"Entry ID: {eid}")
                for k, existing_val, tmpl_val in conflicts_fields:
                    log(f"  field '{k}': existing='{existing_val}', library='{tmpl_val}'")
        else:
            log("\n✅ No conflicts detected.")

        if ambiguous:
            log("\n⚠️  Ambiguous venues (several library records match, nothing added):")
            for eid, venue_raw, labels in ambiguous:
                log(f"  🔸 {eid}: '{venue_raw}' matches {', '.join(labels)}")

        if incomplete_entries:
            log("\n📭 Incomplete entries (missing year or venue, e.g., arxiv/misc) - skipped:")
            for entry_id, venue, year in incomplete_entries:
                log(f"  🔸 {entry_id}: venue='{venue or '(empty)'}' year='{year or '(empty)'}'")

        if missing:
            log("\nℹ️  Venues not in the library (deduplicated):")
            for venue_raw, year, entry_type in missing.values():
                type_icon = "📰" if entry_type == JOURNAL else "📋"
                log(f"  {type_icon} [{entry_type}] venue='{venue_raw}' year='{year}'")
        else:
            log("\n✅ All complete entries matched the venue library.")

        write_report(conflict_log, "conflicts: entry_id\tfield\texisting\tlibrary", conflict_rows)
        write_report(missing_txt_log, "missing venues: venue\tyear\ttype", missing_rows)
        write_report(
            incomplete_log,
            "incomplete entries (missing year or venue): entry_id\tvenue\tyear",
            incomplete_rows,
        )

        if missing:
            _write_yaml_missing_venues(missing_yaml_log, missing, library, result["collected"])
            log(f"\n📝 Missing venues YAML created: {missing_yaml_log}")
            log(
                f"   Fill in the fields and run: bibcc complete {input_path} "
                "--output <out.bib> --update-venues"
            )

        log(f"\nLogs saved: {conflict_log}, {missing_txt_log}, {incomplete_log}")
        return

    # Write pass: re-read raw lines so comments and formatting are kept.
    with open(input_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    with open(output_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line)

            match = re.search(r"@\w+\s*\{\s*([^,]+),", line)

            if match:
                current_id = match.group(1).strip()

                if current_id in patches:
                    new_data = patches[current_id]

                    for key, val in new_data.items():
                        f.write(f"  {key:<12} = {{{val}}},\n")

                    del patches[current_id]

    log(f"✅ Done! Saved to {output_path} (Comments preserved)")


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for BibTeX completer."""
    parser = argparse.ArgumentParser(
        description="Enhance a BibTeX (.bib) file by adding missing metadata fields "
        "from the venue library."
    )
    parser.add_argument("input", type=str, help="Path to the input BibTeX (.bib) file")
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Path to save the output enhanced BibTeX (.bib) file (omit for dry-run).",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default="",
        help="Directory to write logs and reports. Default: .bibcc/ next to the input file.",
    )
    parser.add_argument(
        "--venues",
        type=str,
        default="",
        help=f"Venue library YAML (default: $BIBCC_VENUES or {default_library_path()}).",
    )
    parser.add_argument(
        "--update-venues",
        "--update-templates",
        dest="update_venues",
        action="store_true",
        help="Merge the filled-in *.missing_venues.yaml into the venue library "
        "before completing.",
    )
    return parser


def run(args: argparse.Namespace) -> None:
    """Run completer with parsed arguments."""
    dry_run = not bool(args.output)
    log_dir = Path(args.log_dir) if args.log_dir else None

    with Logger("completer", input_file=args.input, log_dir=log_dir) as logger:
        library = VenueLibrary.load(args.venues or None)

        if args.update_venues:
            base = Path(args.input).name
            yaml_path = get_output_dir(args.input, log_dir) / f"{base}.missing_venues.yaml"
            if not yaml_path.exists():
                logger.log(f"ℹ️  No {yaml_path.name} found — run without --output first.")
            else:
                logger.log(f"🔄 Merging {yaml_path} into {library.path}...")
                counts = merge_missing_venues(library, yaml_path, log=logger.log)
                if counts["added"] or counts["updated"]:
                    library.save()
                    logger.log(
                        f"✅ Venue library updated: +{counts['added']} new, "
                        f"~{counts['updated']} updated, {counts['skipped']} skipped.\n"
                    )
                else:
                    logger.log("ℹ️  Nothing new to merge.\n")

        main(
            args.input,
            args.output or args.input,
            dry_run=dry_run,
            log_dir=log_dir,
            library=library,
            log=logger.log,
        )


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    run(args)
