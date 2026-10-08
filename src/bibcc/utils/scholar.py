#!/usr/bin/env python3
"""
Scholar - Unified citation and title management for BibTeX files.

Subcommands:
    cite    - Generate Google Scholar URLs and manage citation fields
    titles  - Check titles against CrossRef, DBLP, Semantic Scholar, arXiv

Usage:
    python utils/scholar.py cite input.bib
    python utils/scholar.py cite input.bib --interactive
    python utils/scholar.py titles input.bib
    python utils/scholar.py titles input.bib --retry-errors report.txt
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import bibtexparser

from bibcc.bibedit import BibEditError, read_bib, set_fields, write_bib
from bibcc.logging_utils import (
    SEPARATOR_HEAVY,
    SEPARATOR_LIGHT,
    SEPARATOR_WIDTH,
    Logger,
    get_output_dir,
)
from bibcc.sources import (
    clean_title_for_search,
    fetch_url,
    looks_like_html,
    titles_match,
)


# =========================
# Citation command helpers
# =========================


def build_scholar_url(title: str) -> str:
    """Build a Google Scholar search URL for a paper title."""
    clean_title = clean_title_for_search(title)
    encoded_title = urllib.parse.quote(f'"{clean_title}"')
    return f"https://scholar.google.com/scholar?q={encoded_title}"


def interactive_fill(
    input_path: Path,
    output_path: Path,
    entries_to_process: List[Dict[str, Any]],
    log: Callable[[str], None] = print,
) -> None:
    """Interactive mode: open URLs and prompt for citation counts."""
    log("\n🎯 Interactive Fill Mode")
    log(SEPARATOR_HEAVY * SEPARATOR_WIDTH)
    log("For each entry, a Google Scholar tab will open.")
    log("Enter the citation count, or:")
    log("  - Press Enter to skip (leave empty)")
    log("  - Type 'q' to quit and save progress")
    log("  - Type 's' to skip without opening URL")
    log(SEPARATOR_HEAVY * SEPARATOR_WIDTH)

    patches: Dict[str, str] = {}
    total = len(entries_to_process)

    for i, entry in enumerate(entries_to_process, 1):
        entry_id = entry.get("ID", "unknown")
        title = entry.get("title", "")
        clean_title = clean_title_for_search(title)
        display_title = (
            clean_title[:60] + "..." if len(clean_title) > 60 else clean_title
        )

        log(f"\n[{i}/{total}] {entry_id}")
        log(f"   Title: {display_title}")

        try:
            action = input("   Open in browser? [Y/n/s(kip)/q(uit)]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            log("\n\n⏹️  Interrupted. Saving progress...")
            break

        if action == "q":
            log("\n⏹️  Quitting. Saving progress...")
            break
        elif action == "s":
            log("   ⏭️  Skipped")
            continue
        elif action in ("", "y", "yes"):
            url = build_scholar_url(title)
            webbrowser.open_new_tab(url)
            time.sleep(0.5)

        try:
            citation_input = input(
                "   Enter citation count (or Enter to skip): "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            log("\n\n⏹️  Interrupted. Saving progress...")
            break

        if citation_input.lower() == "q":
            log("\n⏹️  Quitting. Saving progress...")
            break
        elif citation_input == "":
            log("   ⏭️  Skipped")
            continue
        elif citation_input.isdigit():
            patches[entry_id] = citation_input
            log(f"   ✅ Set citation = {citation_input}")
        else:
            patches[entry_id] = citation_input
            log(f"   ✅ Set citation = {citation_input}")

    log(f"\n{SEPARATOR_HEAVY * SEPARATOR_WIDTH}")
    log(f"📊 Summary: {len(patches)} citation(s) collected out of {total} entries")

    if not patches:
        log("   No changes to write.")
        return

    log(f"\n✍️  Writing to: {output_path}")

    text = read_bib(input_path)
    try:
        new_text, applied = set_fields(
            text, {eid: {"citation": value} for eid, value in patches.items()}
        )
    except BibEditError as e:
        log(f"❌ Could not write citations safely: {e}")
        log("   Nothing was written.")
        return
    write_bib(output_path, new_text)
    updated_count = len(applied)
    log(f"✅ Done! Updated {updated_count} entries.")
    log(f"   Saved to: {output_path}")


def cmd_cite(
    input_path: str | Path,
    output_path: str | Path = "",
    open_browser: bool = False,
    interactive: bool = False,
    include_filled: bool = False,
    batch_size: int = 5,
    dry_run: bool = True,
    log_dir: Optional[Path] = None,
    log: Callable[[str], None] = print,
) -> None:
    """Process BibTeX file for citation counts."""
    input_path = Path(input_path).resolve()

    if not input_path.exists():
        log(f"❌ File not found: {input_path}")
        return

    log(f"📖 Reading: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        bib_db = bibtexparser.load(f, parser=parser)

    log(f"   Found {len(bib_db.entries)} entries")

    entries_to_process: List[Dict[str, Any]] = []
    entries_with_citation: List[Tuple[str, str]] = []

    for entry in bib_db.entries:
        entry_id = entry.get("ID", "unknown")
        citation_val = entry.get("citation", None)

        if citation_val is None:
            entries_to_process.append(entry)
        elif citation_val.strip() == "":
            entries_to_process.append(entry)
        else:
            entries_with_citation.append((entry_id, citation_val.strip()))

    log(f"   Entries with citation: {len(entries_with_citation)}")
    log(f"   Entries needing citation: {len(entries_to_process)}")

    if entries_with_citation and not include_filled:
        log("\n⏭️  Skipping entries with existing citations:")
        for entry_id, cit_val in entries_with_citation[:5]:
            display_val = cit_val[:20] + "..." if len(cit_val) > 20 else cit_val
            log(f"      {entry_id}: {display_val}")
        if len(entries_with_citation) > 5:
            log(f"      ... and {len(entries_with_citation) - 5} more")

    if include_filled and entries_with_citation:
        log(
            f"\n🔄 Including {len(entries_with_citation)} entries with existing citations (--include-filled)"
        )
        for entry in bib_db.entries:
            citation_val = entry.get("citation", None)
            if citation_val is not None and citation_val.strip() != "":
                entries_to_process.append(entry)

    if not entries_to_process:
        log("\n✅ All entries already have citation values!")
        return

    if interactive:
        out_path = Path(output_path).resolve() if output_path else input_path
        interactive_fill(input_path, out_path, entries_to_process, log)
        return

    url_list: List[Tuple[str, str, str]] = []
    for entry in entries_to_process:
        entry_id = entry.get("ID", "unknown")
        title = entry.get("title", "")
        if title:
            url = build_scholar_url(title)
            url_list.append((entry_id, clean_title_for_search(title), url))
        else:
            log(f"   ⚠️  No title for entry: {entry_id}")

    log(f"\n📋 Entries to process ({len(url_list)}):")
    log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
    for i, (entry_id, title, url) in enumerate(url_list, 1):
        display_title = title[:50] + "..." if len(title) > 50 else title
        log(f"  [{i:3d}] {entry_id}")
        log(f"        {display_title}")
        if not open_browser:
            log(f"        {url}")
    log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)

    output_dir = get_output_dir(input_path, log_dir)
    url_list_path = output_dir / f"{input_path.name}.scholar_urls.txt"

    with open(url_list_path, "w", encoding="utf-8") as f:
        f.write("# Google Scholar URLs for citation lookup\n")
        f.write(f"# Generated from: {input_path.name}\n")
        f.write(f"# Entries: {len(url_list)}\n\n")
        for entry_id, title, url in url_list:
            f.write(f"{entry_id}\n")
            f.write(f"  Title: {title}\n")
            f.write(f"  URL: {url}\n\n")

    log(f"\n📝 URL list saved: {url_list_path}")

    if open_browser:
        log(f"\n🌐 Opening URLs in browser (batch size: {batch_size})...")

        total_batches = (len(url_list) + batch_size - 1) // batch_size
        end_idx = 0

        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(url_list))
            batch = url_list[start_idx:end_idx]

            log(f"\n📦 Batch {batch_num + 1}/{total_batches} ({len(batch)} entries):")
            for entry_id, title, url in batch:
                display_title = title[:40] + "..." if len(title) > 40 else title
                log(f"   Opening: {entry_id} - {display_title}")
                webbrowser.open_new_tab(url)
                time.sleep(0.3)

            if batch_num < total_batches - 1:
                log(f"\n   ⏸️  Opened {end_idx} of {len(url_list)} URLs.")
                try:
                    input("   Press Enter to open next batch (Ctrl+C to stop)...")
                except KeyboardInterrupt:
                    log("\n   Stopped by user.")
                    break

        log(f"\n✅ Opened {min(end_idx, len(url_list))} URLs in browser")

    patches: Dict[str, Dict[str, str]] = {}
    for entry in entries_to_process:
        entry_id = entry.get("ID", "unknown")
        patches[entry_id] = {"citation": ""}

    if dry_run:
        log("\n🧪 Dry-run: Would add empty 'citation' field to these entries:")
        for entry_id in list(patches.keys())[:10]:
            log(f"   {entry_id}")
        if len(patches) > 10:
            log(f"   ... and {len(patches) - 10} more")
        log("\n💡 To write changes, run with --output <file.bib>")
        return

    output_path = Path(output_path).resolve()
    log(f"\n✍️  Writing output: {output_path}")

    text = read_bib(input_path)
    try:
        new_text, applied = set_fields(text, patches, replace=False)
    except BibEditError as e:
        log(f"❌ Could not add citation fields safely: {e}")
        log("   Nothing was written.")
        return
    write_bib(output_path, new_text)
    log(f"✅ Done! Added empty 'citation' field to {len(applied)} entries.")
    log(f"   Output saved to: {output_path}")
    log("\n💡 Now fill in the citation counts from Google Scholar results!")


# ======================
# Title command helpers
# ======================


@dataclass
class TitleMatch:
    """Represents a title match from an external source."""

    source: str
    original_title: str
    confidence: str  # "high", "medium", "low"
    url: Optional[str] = None


@dataclass
class LookupResult:
    """Result of a lookup attempt, including potential errors."""

    source: str
    match: Optional[TitleMatch] = None
    error: Optional[str] = None
    searched: bool = True


@dataclass
class SourceStatus:
    """Status of a lookup attempt."""

    source: str
    status: str  # "found", "no_match", "error", "skipped"
    error: Optional[str] = None


def case_differs(title1: str, title2: str) -> bool:
    """Check if titles differ only in case (not content)."""
    if not titles_match(title1, title2):
        return False
    t1 = re.sub(r"[{}]", "", title1).strip()
    t2 = re.sub(r"[{}]", "", title2).strip()
    return t1 != t2


def lookup_crossref(doi: str) -> LookupResult:
    """Look up title via CrossRef API using DOI."""
    source = "CrossRef (DOI)"
    if not doi:
        return LookupResult(source=source, searched=False)

    doi = doi.strip()
    if doi.startswith("http"):
        doi = re.sub(r"https?://doi\.org/", "", doi)

    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}"
    content, error = fetch_url(url)

    if error:
        return LookupResult(source=source, error=error)
    if not content:
        return LookupResult(source=source, error="Empty response")

    try:
        data = json.loads(content)
        if data.get("status") == "ok":
            work = data.get("message", {})
            titles = work.get("title", [])
            if titles:
                return LookupResult(
                    source=source,
                    match=TitleMatch(
                        source=source,
                        original_title=titles[0],
                        confidence="high",
                        url=f"https://doi.org/{doi}",
                    ),
                )
        return LookupResult(source=source)
    except json.JSONDecodeError as e:
        return LookupResult(source=source, error=f"JSON parse error: {e}")


def lookup_dblp(title: str) -> LookupResult:
    """Look up title via DBLP API."""
    source = "DBLP"
    if not title:
        return LookupResult(source=source, searched=False)

    search_title = clean_title_for_search(title)
    query = urllib.parse.quote(search_title)
    url = f"https://dblp.org/search/publ/api?q={query}&format=json&h=5"

    content, error = fetch_url(url)
    if error:
        return LookupResult(source=source, error=error)
    if not content:
        return LookupResult(source=source, error="Empty response")
    if looks_like_html(content):
        return LookupResult(source=source, error="DBLP returned an HTML page (bot protection)")

    try:
        data = json.loads(content)
        hits = data.get("result", {}).get("hits", {}).get("hit", [])

        for hit in hits:
            info = hit.get("info", {})
            dblp_title = info.get("title", "").rstrip(".")
            if titles_match(title, dblp_title):
                return LookupResult(
                    source=source,
                    match=TitleMatch(
                        source=source,
                        original_title=dblp_title,
                        confidence="high",
                        url=info.get("url"),
                    ),
                )
        return LookupResult(source=source)
    except json.JSONDecodeError as e:
        return LookupResult(source=source, error=f"JSON parse error: {e}")


def lookup_semantic_scholar(title: str) -> LookupResult:
    """Look up title via Semantic Scholar API."""
    source = "Semantic Scholar"
    if not title:
        return LookupResult(source=source, searched=False)

    search_title = clean_title_for_search(title)
    query = urllib.parse.quote(search_title)
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search?"
        f"query={query}&limit=5&fields=title,url"
    )

    content, error = fetch_url(url)
    if error:
        return LookupResult(source=source, error=error)
    if not content:
        return LookupResult(source=source, error="Empty response")

    try:
        data = json.loads(content)
        papers = data.get("data", [])

        for paper in papers:
            ss_title = paper.get("title", "")
            if titles_match(title, ss_title):
                return LookupResult(
                    source=source,
                    match=TitleMatch(
                        source=source,
                        original_title=ss_title,
                        confidence="high",
                        url=paper.get("url"),
                    ),
                )
        return LookupResult(source=source)
    except json.JSONDecodeError as e:
        return LookupResult(source=source, error=f"JSON parse error: {e}")


def lookup_arxiv(entry: Dict[str, Any]) -> LookupResult:
    """Look up title via arXiv API using eprint or URL."""
    source = "arXiv"
    arxiv_id: Optional[str] = None

    eprint = entry.get("eprint", "")
    if eprint and (
        "arxiv" in entry.get("archiveprefix", "").lower()
        or re.match(r"\d{4}\.\d+", eprint)
    ):
        arxiv_id = eprint

    if not arxiv_id:
        url = entry.get("url", "")
        match = re.search(r"arxiv\.org/abs/(\d{4}\.\d+)", url)
        if match:
            arxiv_id = match.group(1)

    if not arxiv_id:
        return LookupResult(source=source, searched=False)

    api_url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    content, error = fetch_url(api_url)

    if error:
        return LookupResult(source=source, error=error)
    if not content:
        return LookupResult(source=source, error="Empty response")

    try:
        root = ET.fromstring(content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for entry_elem in root.findall("atom:entry", ns):
            title_elem = entry_elem.find("atom:title", ns)
            if title_elem is not None and title_elem.text:
                arxiv_title = re.sub(r"\s+", " ", title_elem.text).strip()
                return LookupResult(
                    source=source,
                    match=TitleMatch(
                        source=source,
                        original_title=arxiv_title,
                        confidence="high",
                        url=f"https://arxiv.org/abs/{arxiv_id}",
                    ),
                )
        return LookupResult(source=source)
    except ET.ParseError as e:
        return LookupResult(source=source, error=f"XML parse error: {e}")


def find_original_title(
    entry: Dict[str, Any], delay: float = 0.3
) -> Tuple[List[TitleMatch], List[SourceStatus]]:
    """Find original title from sources according to DOI/arXiv/DBLP/SS rules."""
    matches: List[TitleMatch] = []
    source_statuses: List[SourceStatus] = []
    current_title = entry.get("title", "")
    doi = entry.get("doi", "")

    if doi:
        result = lookup_crossref(doi)
        if result.error:
            source_statuses.append(SourceStatus(result.source, "error", result.error))
        elif result.match:
            matches.append(result.match)
            source_statuses.append(SourceStatus(result.source, "found"))
        else:
            source_statuses.append(SourceStatus(result.source, "no_match"))
        time.sleep(delay)
        return matches, source_statuses

    result = lookup_arxiv(entry)
    if result.searched:
        if result.error:
            source_statuses.append(SourceStatus(result.source, "error", result.error))
        elif result.match:
            matches.append(result.match)
            source_statuses.append(SourceStatus(result.source, "found"))
            if case_differs(current_title, result.match.original_title):
                return matches, source_statuses
        else:
            source_statuses.append(SourceStatus(result.source, "no_match"))
        time.sleep(delay)

    if current_title:
        result = lookup_dblp(current_title)
        if result.error:
            source_statuses.append(SourceStatus(result.source, "error", result.error))
        elif result.match:
            matches.append(result.match)
            source_statuses.append(SourceStatus(result.source, "found"))
            if case_differs(current_title, result.match.original_title):
                return matches, source_statuses
        else:
            source_statuses.append(SourceStatus(result.source, "no_match"))
        time.sleep(delay)

    if not matches and current_title:
        result = lookup_semantic_scholar(current_title)
        if result.error:
            source_statuses.append(SourceStatus(result.source, "error", result.error))
        elif result.match:
            matches.append(result.match)
            source_statuses.append(SourceStatus(result.source, "found"))
        else:
            source_statuses.append(SourceStatus(result.source, "no_match"))
        time.sleep(delay)

    return matches, source_statuses


def highlight_case_diff(current: str, original: str) -> str:
    """Create a visual diff highlighting case differences."""
    current_clean = re.sub(r"[{}]", "", current)
    original_clean = re.sub(r"[{}]", "", original)

    current_words = current_clean.split()
    original_words = original_clean.split()

    if len(current_words) != len(original_words):
        return f"  Current:  {current}\n  Original: {original}"

    diff_words: List[str] = []
    for cw, ow in zip(current_words, original_words):
        if cw.lower() == ow.lower() and cw != ow:
            diff_words.append(f"[{cw} → {ow}]")
        elif cw != ow:
            diff_words.append(f"[{cw} → {ow}]")

    if diff_words:
        return f"  Differences: {' '.join(diff_words)}"
    return ""


def parse_error_ids_from_report(
    report_path: str,
    log: Callable[[str], None] = print,
) -> List[str]:
    """Parse entry IDs that had errors from a previous report file."""
    error_ids: List[str] = []
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()

        in_error_section = False
        for line in content.split("\n"):
            if "LOOKUP ERRORS" in line:
                in_error_section = True
                continue
            if in_error_section:
                if line.startswith("---") and "NO MATCH FOUND" in line:
                    break
                if line.startswith("==="):
                    break
                if line.startswith("ID: "):
                    error_ids.append(line[4:].strip())
    except FileNotFoundError:
        log(f"❌ Error: Report file not found: {report_path}")
    except Exception as e:
        log(f"❌ Error reading report file: {e}")

    return error_ids


def parse_full_report(
    report_path: str,
    log: Callable[[str], None] = print,
) -> Tuple[
    List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]
]:
    """Parse full report sections: case_diffs, with_errors, no_match, metadata."""
    case_diffs: List[Dict[str, Any]] = []
    with_errors: List[Dict[str, Any]] = []
    no_match: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {"bib_path": "", "total": 0}

    try:
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        section: Optional[str] = None
        current_entry: Dict[str, Any] = {}

        def save_current_entry() -> None:
            nonlocal current_entry
            if current_entry and current_entry.get("id"):
                if section == "case_diffs":
                    case_diffs.append(current_entry)
                elif section == "with_errors":
                    with_errors.append(current_entry)
                elif section == "no_match":
                    no_match.append(current_entry)
            current_entry = {}

        for line in lines:
            if line.startswith("Generated from:"):
                metadata["bib_path"] = line.split(":", 1)[1].strip()
            elif line.startswith("Total entries checked:"):
                metadata["total"] = int(line.split(":")[1].strip())

            if "CASE DIFFERENCES FOUND" in line:
                save_current_entry()
                section = "case_diffs"
                continue
            elif "LOOKUP ERRORS" in line:
                save_current_entry()
                section = "with_errors"
                continue
            elif "NO MATCH FOUND" in line:
                save_current_entry()
                section = "no_match"
                continue

            if line.startswith("===") or line.startswith("---"):
                continue

            if section and line.startswith("ID: "):
                save_current_entry()
                current_entry = {"id": line[4:].strip()}
            elif current_entry:
                if line.startswith("Source: "):
                    current_entry["source"] = line[8:].strip()
                elif line.startswith("Current:"):
                    current_entry["current_title"] = line[9:].strip()
                elif line.startswith("Original:"):
                    current_entry["original_title"] = line[10:].strip()
                elif line.startswith("URL: "):
                    current_entry["url"] = line[5:].strip()
                elif line.startswith("Title: "):
                    current_entry["current_title"] = line[7:].strip()
                elif line.startswith("Searched: "):
                    current_entry["searched"] = line[10:].strip()

        save_current_entry()

    except Exception as e:
        log(f"❌ Error parsing report: {e}")

    return case_diffs, with_errors, no_match, metadata


def merge_and_write_report(
    report_path: str,
    new_results: List[Dict[str, Any]],
    retried_ids: List[str],
    bib_path: str,
    total_entries: int,
    log: Callable[[str], None] = print,
) -> None:
    """Merge new retry results into an existing report file."""
    old_case_diffs, old_with_errors, old_no_match, metadata = parse_full_report(
        report_path, log=log
    )

    retried_set = set(retried_ids)
    old_with_errors = [e for e in old_with_errors if e.get("id") not in retried_set]
    old_no_match = [e for e in old_no_match if e.get("id") not in retried_set]

    new_case_diffs = [r for r in new_results if not r.get("not_found")]
    new_not_found = [r for r in new_results if r.get("not_found")]
    new_with_errors = [
        r
        for r in new_not_found
        if any(ss.status == "error" for ss in r.get("source_statuses", []))
    ]
    new_no_match = [r for r in new_not_found if r not in new_with_errors]

    all_case_diffs = old_case_diffs + new_case_diffs
    all_with_errors = old_with_errors + new_with_errors
    all_no_match = old_no_match + new_no_match

    if metadata.get("bib_path"):
        bib_path = metadata["bib_path"]
    if metadata.get("total"):
        total_entries = metadata["total"]

    sep = SEPARATOR_HEAVY * SEPARATOR_WIDTH
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("TITLE CHECK REPORT\n")
        f.write(f"Generated from: {bib_path}\n")
        f.write(sep + "\n\n")
        f.write(f"Total entries checked: {total_entries}\n")
        f.write(f"Entries with case differences: {len(all_case_diffs)}\n")
        f.write(f"Entries with lookup errors: {len(all_with_errors)}\n")
        f.write(f"Entries with no match found: {len(all_no_match)}\n\n")

        if all_case_diffs:
            f.write(sep + "\n")
            f.write("CASE DIFFERENCES FOUND:\n")
            f.write(sep + "\n\n")
            for r in all_case_diffs:
                f.write(f"ID: {r.get('id', r.get('ID', 'unknown'))}\n")
                f.write(f"Source: {r.get('source', 'unknown')}\n")
                f.write(f"Current:  {r.get('current_title', '')}\n")
                f.write(f"Original: {r.get('original_title', '')}\n")
                if r.get("url"):
                    f.write(f"URL: {r['url']}\n")
                f.write("\n")

        if all_with_errors or all_no_match:
            f.write(sep + "\n")
            f.write("NOT FOUND IN ANY SOURCE (need manual check):\n")
            f.write(sep + "\n\n")

            if all_with_errors:
                f.write("--- LOOKUP ERRORS (network/API failures) ---\n\n")
                for r in all_with_errors:
                    f.write(f"ID: {r.get('id', r.get('ID', 'unknown'))}\n")
                    f.write(f"Title: {r.get('current_title', '')}\n")
                    for ss in r.get("source_statuses", []):
                        if ss.status == "error":
                            f.write(f"  ERROR {ss.source}: {ss.error}\n")
                        elif ss.status == "no_match":
                            f.write(f"  OK {ss.source}: no match\n")
                    f.write("\n")

            if all_no_match:
                f.write("--- NO MATCH FOUND (searched successfully) ---\n\n")
                for r in all_no_match:
                    f.write(f"ID: {r.get('id', r.get('ID', 'unknown'))}\n")
                    f.write(f"Title: {r.get('current_title', '')}\n")
                    sources = r.get("searched", "")
                    if not sources and r.get("source_statuses"):
                        sources = ", ".join(
                            ss.source for ss in r.get("source_statuses", [])
                        )
                    if sources:
                        f.write(f"Searched: {sources}\n")
                    f.write("\n")

    log(f"\n📝 Report updated: {report_path}")
    log(f"   Case differences: {len(all_case_diffs)}")
    log(f"   Lookup errors: {len(all_with_errors)}")
    log(f"   No match found: {len(all_no_match)}")


def check_titles(
    bib_path: str,
    output_path: Optional[str] = None,
    delay: float = 0.5,
    verbose: bool = True,
    filter_ids: Optional[List[str]] = None,
    log: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, Any]]:
    """Check all titles in a bib file against external sources."""
    log = log or print

    with open(bib_path, "r", encoding="utf-8") as f:
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        bib_db = bibtexparser.load(f, parser=parser)

    if filter_ids:
        filter_set = set(filter_ids)
        entries_to_check = [e for e in bib_db.entries if e.get("ID") in filter_set]
        log(f"🔍 Re-checking {len(entries_to_check)} specific entries from {bib_path}")
        if len(entries_to_check) < len(filter_ids):
            found_ids = {e.get("ID") for e in entries_to_check}
            missing = filter_set - found_ids
            log(
                f"⚠️  Warning: {len(missing)} IDs not found in bib file: {', '.join(list(missing)[:5])}..."
            )
    else:
        entries_to_check = bib_db.entries
        log(f"🔍 Checking {len(entries_to_check)} entries in {bib_path}")

    log("\n" + SEPARATOR_HEAVY * SEPARATOR_WIDTH)

    results: List[Dict[str, Any]] = []
    total = len(entries_to_check)

    for i, entry in enumerate(entries_to_check, 1):
        entry_id = entry.get("ID", "unknown")
        current_title = entry.get("title", "")

        if not current_title:
            continue

        if verbose:
            status = f"[{i}/{total}] Checking: {entry_id[:40]}"
            log(f"\r{status:<60}")

        matches, source_statuses = find_original_title(entry, delay)

        if not matches:
            if not source_statuses:
                reason = "No DOI, arXiv ID, or title to search"
            else:
                status_parts: List[str] = []
                has_errors = False
                for ss in source_statuses:
                    if ss.status == "error":
                        status_parts.append(f"{ss.source}: ⚠️ {ss.error}")
                        has_errors = True
                    elif ss.status == "no_match":
                        status_parts.append(f"{ss.source}: no match")

                if has_errors:
                    reason = "Errors encountered:\n    " + "\n    ".join(status_parts)
                else:
                    reason = (
                        "Tried: "
                        + ", ".join(ss.source for ss in source_statuses)
                        + " - no match found"
                    )

            results.append(
                {
                    "id": entry_id,
                    "current_title": current_title,
                    "original_title": None,
                    "source": None,
                    "confidence": None,
                    "url": None,
                    "not_found": True,
                    "reason": reason,
                    "has_doi": bool(entry.get("doi")),
                    "source_statuses": source_statuses,
                }
            )
            continue

        for match in matches:
            if case_differs(current_title, match.original_title):
                results.append(
                    {
                        "id": entry_id,
                        "current_title": current_title,
                        "original_title": match.original_title,
                        "source": match.source,
                        "confidence": match.confidence,
                        "url": match.url,
                        "not_found": False,
                    }
                )
                break

    if verbose:
        log("")

    not_found = [r for r in results if r.get("not_found")]
    case_diffs = [r for r in results if not r.get("not_found")]

    with_errors = [
        r
        for r in not_found
        if any(ss.status == "error" for ss in r.get("source_statuses", []))
    ]
    no_match = [r for r in not_found if r not in with_errors]

    log("\n📋 TITLE CHECK REPORT")
    log(SEPARATOR_HEAVY * SEPARATOR_WIDTH)
    log(f"Total entries checked: {total}")
    log(f"Entries with case differences: {len(case_diffs)}")
    log(f"Entries with lookup errors (network/API): {len(with_errors)}")
    log(f"Entries with no match found: {len(no_match)}")
    log(SEPARATOR_HEAVY * SEPARATOR_WIDTH + "\n")

    if case_diffs:
        log("📝 CASE DIFFERENCES FOUND:")
        log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
        for r in case_diffs:
            log(f"📄 {r['id']}")
            log(f"  Source: {r['source']}")
            log(f"  Current:  {r['current_title']}")
            log(f"  Original: {r['original_title']}")
            diff = highlight_case_diff(r["current_title"], r["original_title"])
            if diff:
                log(diff)
            if r["url"]:
                log(f"  URL: {r['url']}")
            log("")

    if not_found:
        log("❓ NOT FOUND IN ANY SOURCE (need manual check):")
        log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)

        if with_errors:
            log("\n⚠️  LOOKUP ERRORS (network/API failures):")
            for r in with_errors:
                log(f"📄 {r['id']}")
                log(f"  Title: {r['current_title']}")
                for ss in r.get("source_statuses", []):
                    if ss.status == "error":
                        log(f"  ❌ {ss.source}: {ss.error}")
                    elif ss.status == "no_match":
                        log(f"  ✓ {ss.source}: searched, no match")
                log("")

        if no_match:
            log("\n🔍 NO MATCH FOUND (searched successfully but not found):")
            for r in no_match:
                log(f"📄 {r['id']}")
                log(f"  Title: {r['current_title']}")
                sources = [ss.source for ss in r.get("source_statuses", [])]
                if sources:
                    log(f"  Searched: {', '.join(sources)}")
                else:
                    log(f"  Reason: {r.get('reason', 'Unknown')}")
                log("")

    if not case_diffs and not not_found:
        log("✅ All titles verified - no issues found!")

    sep = SEPARATOR_HEAVY * SEPARATOR_WIDTH
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("TITLE CHECK REPORT\n")
            f.write(f"Generated from: {bib_path}\n")
            f.write(sep + "\n\n")
            f.write(f"Total entries checked: {total}\n")
            f.write(f"Entries with case differences: {len(case_diffs)}\n")
            f.write(f"Entries not found in any source: {len(not_found)}\n\n")

            if case_diffs:
                f.write(sep + "\n")
                f.write("CASE DIFFERENCES FOUND:\n")
                f.write(sep + "\n\n")
                for r in case_diffs:
                    f.write(f"ID: {r['id']}\n")
                    f.write(f"Source: {r['source']}\n")
                    f.write(f"Current:  {r['current_title']}\n")
                    f.write(f"Original: {r['original_title']}\n")
                    if r["url"]:
                        f.write(f"URL: {r['url']}\n")
                    f.write("\n")

            if not_found:
                f.write(sep + "\n")
                f.write("NOT FOUND IN ANY SOURCE (need manual check):\n")
                f.write(sep + "\n\n")

                if with_errors:
                    f.write("--- LOOKUP ERRORS (network/API failures) ---\n\n")
                    for r in with_errors:
                        f.write(f"ID: {r['id']}\n")
                        f.write(f"Title: {r['current_title']}\n")
                        for ss in r.get("source_statuses", []):
                            if ss.status == "error":
                                f.write(f"  ERROR {ss.source}: {ss.error}\n")
                            elif ss.status == "no_match":
                                f.write(f"  OK {ss.source}: no match\n")
                        f.write("\n")

                if no_match:
                    f.write("--- NO MATCH FOUND (searched successfully) ---\n\n")
                    for r in no_match:
                        f.write(f"ID: {r['id']}\n")
                        f.write(f"Title: {r['current_title']}\n")
                        sources = [ss.source for ss in r.get("source_statuses", [])]
                        if sources:
                            f.write(f"Searched: {', '.join(sources)}\n")
                        f.write("\n")

        log(f"📝 Report saved to: {output_path}")

    return results


def cmd_titles(
    bib_file: Path,
    delay: float = 0.5,
    quiet: bool = False,
    retry_errors: Optional[str] = None,
    ids: Optional[str] = None,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Run title checking command flow."""
    log = log or print

    base_name = bib_file.name
    output_path = get_output_dir(bib_file) / f"{base_name}.title_report.txt"

    filter_ids: Optional[List[str]] = None
    retry_report_path: Optional[str] = None

    if retry_errors:
        filter_ids = parse_error_ids_from_report(retry_errors, log=log)
        if not filter_ids:
            log("No error entries found in the report file.")
            return
        log(f"📋 Found {len(filter_ids)} entries with errors to re-check")
        retry_report_path = retry_errors
    elif ids:
        filter_ids = [entry_id.strip() for entry_id in ids.split(",")]
        log(f"📋 Will check {len(filter_ids)} specified entries")

    results = check_titles(
        str(bib_file),
        output_path=(str(output_path) if not retry_report_path else None),
        delay=delay,
        verbose=not quiet,
        filter_ids=filter_ids,
        log=log,
    )

    if retry_report_path and results is not None and filter_ids is not None:
        merge_and_write_report(
            retry_report_path,
            results,
            filter_ids,
            str(bib_file),
            len(filter_ids),
            log=log,
        )


# =========================
# Parser and entry point
# =========================


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser with scholar subcommands."""
    parser = argparse.ArgumentParser(
        description="Scholar: citation and title management for BibTeX files.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_cite = subparsers.add_parser(
        "cite", help="Google Scholar URLs and citation fields"
    )
    p_cite.add_argument("bib_file", type=Path, help="Path to .bib file")
    p_cite.add_argument(
        "--output",
        "-o",
        type=str,
        default="",
        help="Output file (omit for dry-run)",
    )
    p_cite.add_argument("--open", action="store_true", help="Open URLs in browser")
    p_cite.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Interactive citation fill",
    )
    p_cite.add_argument(
        "--include-filled",
        action="store_true",
        help="Include entries with citations",
    )
    p_cite.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="URLs per batch (default: 5)",
    )
    p_cite.add_argument(
        "--log-dir",
        type=str,
        default="",
        help="Directory to write logs and reports. Default: .bibcc/ next to the input file.",
    )

    p_titles = subparsers.add_parser(
        "titles", help="Check titles against external sources"
    )
    p_titles.add_argument("bib_file", type=Path, help="Path to .bib file")
    p_titles.add_argument(
        "--delay",
        "-d",
        type=float,
        default=0.5,
        help="API delay in seconds",
    )
    p_titles.add_argument(
        "--quiet", "-q", action="store_true", help="Suppress progress"
    )
    p_titles.add_argument(
        "--retry-errors",
        metavar="REPORT",
        help="Re-check error entries from report",
    )
    p_titles.add_argument("--ids", help="Comma-separated entry IDs to check")

    return parser


def main() -> None:
    """Main entry point for scholar tool."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "cite":
        if args.interactive and not args.output:
            args.output = str(args.bib_file)

        dry_run = not bool(args.output) and not args.interactive
        log_dir = Path(args.log_dir) if args.log_dir else None

        with Logger(
            "scholar.cite", input_file=str(args.bib_file), log_dir=log_dir
        ) as logger:
            cmd_cite(
                args.bib_file,
                args.output or str(args.bib_file),
                open_browser=args.open,
                interactive=args.interactive,
                include_filled=args.include_filled,
                batch_size=args.batch_size,
                dry_run=dry_run,
                log_dir=log_dir,
                log=logger.log,
            )
    elif args.command == "titles":
        with Logger("scholar.titles", input_file=str(args.bib_file)) as logger:
            cmd_titles(
                args.bib_file,
                delay=args.delay,
                quiet=args.quiet,
                retry_errors=args.retry_errors,
                ids=args.ids,
                log=logger.log,
            )


if __name__ == "__main__":
    main()
