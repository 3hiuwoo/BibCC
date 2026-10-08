#!/usr/bin/env python3
"""
Title Checker - Find original titles from multiple sources and report differences.

Source strategy:
- Entries WITH DOI: Use CrossRef ONLY (DOI lookup is authoritative)
  If CrossRef fails, the entry is reported as failed - no fallback.
- Entries WITHOUT DOI: Use these sources in order:
  1. arXiv API (if arXiv ID is present)
  2. DBLP API (search by title)
  3. Semantic Scholar API (search by title, as backup)

Usage:
    python titleretriever.py <bib_file>
    python titleretriever.py <bib_file> --retry-errors report.txt  # Re-check only failed entries
    python titleretriever.py <bib_file> --ids ID1,ID2,ID3          # Check specific entries

Output:
    - Automatically generates <bib_file>.titleretriever.log
    - Report saved to <bib_file>.title_report.txt
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import bibtexparser

from bibcc.logging_utils import Logger, get_repo_dir


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
    error: Optional[str] = None  # Error message if lookup failed
    searched: bool = True  # False if skipped (no DOI, etc.)


def normalize_for_comparison(text: str) -> str:
    """Normalize text for comparison (lowercase, remove special chars)."""
    if not text:
        return ""
    # Remove braces, normalize whitespace, lowercase
    text = re.sub(r"[{}\[\]]", "", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    # Remove common punctuation for comparison
    text = re.sub(r"[:\-–—,.'\"?!]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_title_for_search(title: str) -> str:
    """Clean a BibTeX title for API search queries."""
    if not title:
        return ""
    # Remove braces
    title = re.sub(r"[{}\[\]]", "", title)
    # Convert common LaTeX commands
    title = title.replace(r"\&", "&")
    title = title.replace(r"\'", "'")
    title = title.replace(r"\$", "")
    title = title.replace(r"\textasciicircum", "^")
    title = re.sub(r"\\[a-zA-Z]+", "", title)  # Remove other LaTeX commands
    # Clean up whitespace
    title = re.sub(r"\s+", " ", title).strip()
    return title


def titles_match(title1: str, title2: str) -> bool:
    """Check if two titles are essentially the same (ignoring case and formatting)."""
    return normalize_for_comparison(title1) == normalize_for_comparison(title2)


def case_differs(title1: str, title2: str) -> bool:
    """Check if titles differ only in case (not content)."""
    if not titles_match(title1, title2):
        return False
    # Remove braces for comparison
    t1 = re.sub(r"[{}]", "", title1).strip()
    t2 = re.sub(r"[{}]", "", title2).strip()
    return t1 != t2


def fetch_url(
    url: str, headers: Optional[Dict] = None, timeout: int = 10
) -> Tuple[Optional[str], Optional[str]]:
    """Fetch URL content with error handling. Returns (content, error)."""
    try:
        req = urllib.request.Request(url)
        if headers:
            for key, value in headers.items():
                req.add_header(key, value)
        req.add_header(
            "User-Agent", "BibCC-TitleChecker/1.0 (mailto:research@example.com)"
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8"), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return None, f"Network error: {e.reason}"
    except TimeoutError:
        return None, "Request timed out"
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)}"


def lookup_crossref(doi: str) -> LookupResult:
    """Look up title via CrossRef API using DOI."""
    source = "CrossRef (DOI)"
    if not doi:
        return LookupResult(source=source, searched=False)

    # Clean DOI
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
        return LookupResult(source=source)  # No match found
    except json.JSONDecodeError as e:
        return LookupResult(source=source, error=f"JSON parse error: {e}")


def lookup_dblp(title: str) -> LookupResult:
    """Look up title via DBLP API."""
    source = "DBLP"
    if not title:
        return LookupResult(source=source, searched=False)

    # Clean title for search (remove braces, LaTeX commands)
    search_title = clean_title_for_search(title)
    query = urllib.parse.quote(search_title)
    url = f"https://dblp.org/search/publ/api?q={query}&format=json&h=5"

    content, error = fetch_url(url)
    if error:
        return LookupResult(source=source, error=error)

    if not content:
        return LookupResult(source=source, error="Empty response")

    try:
        data = json.loads(content)
        hits = data.get("result", {}).get("hits", {}).get("hit", [])

        for hit in hits:
            info = hit.get("info", {})
            dblp_title = info.get("title", "")

            # Remove trailing period that DBLP sometimes adds
            dblp_title = dblp_title.rstrip(".")

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
        return LookupResult(source=source)  # No match found
    except json.JSONDecodeError as e:
        return LookupResult(source=source, error=f"JSON parse error: {e}")


def lookup_semantic_scholar(title: str) -> LookupResult:
    """Look up title via Semantic Scholar API."""
    source = "Semantic Scholar"
    if not title:
        return LookupResult(source=source, searched=False)

    search_title = clean_title_for_search(title)
    query = urllib.parse.quote(search_title)
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={query}&limit=5&fields=title,url"

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
        return LookupResult(source=source)  # No match found
    except json.JSONDecodeError as e:
        return LookupResult(source=source, error=f"JSON parse error: {e}")


def lookup_arxiv(entry: Dict) -> LookupResult:
    """Look up title via arXiv API using eprint or URL."""
    source = "arXiv"
    # Try to find arXiv ID
    arxiv_id = None

    eprint = entry.get("eprint", "")
    if eprint and (
        "arxiv" in entry.get("archiveprefix", "").lower()
        or re.match(r"\d{4}\.\d+", eprint)
    ):
        arxiv_id = eprint

    # Check URL for arXiv
    if not arxiv_id:
        url = entry.get("url", "")
        match = re.search(r"arxiv\.org/abs/(\d{4}\.\d+)", url)
        if match:
            arxiv_id = match.group(1)

    if not arxiv_id:
        return LookupResult(source=source, searched=False)

    # Query arXiv API
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
                # arXiv titles often have newlines, clean them
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
        return LookupResult(source=source)  # No match found
    except ET.ParseError as e:
        return LookupResult(source=source, error=f"XML parse error: {e}")


@dataclass
class SourceStatus:
    """Status of a lookup attempt."""

    source: str
    status: str  # "found", "no_match", "error", "skipped"
    error: Optional[str] = None


def find_original_title(
    entry: Dict, delay: float = 0.3
) -> Tuple[List[TitleMatch], List[SourceStatus]]:
    """
    Find original title from multiple sources.
    Returns (matches, source_statuses) - list of matches and status of each source tried.

    Strategy:
    - If entry has DOI: Use ONLY CrossRef (DOI lookup is authoritative)
      If CrossRef fails, report as error - no fallback to other sources.
    - If entry has no DOI: Use arXiv (if applicable), DBLP, Semantic Scholar.
    """
    matches = []
    source_statuses = []
    current_title = entry.get("title", "")
    doi = entry.get("doi", "")

    # If entry has DOI, use ONLY CrossRef (authoritative lookup)
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
        # DOI entries only use CrossRef - return immediately
        return matches, source_statuses

    # No DOI - use other sources

    # 1. Try arXiv (if applicable)
    result = lookup_arxiv(entry)
    if result.searched:  # Only if arXiv ID was found
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

    # 2. Try DBLP
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

    # 3. Try Semantic Scholar (as backup, only if no matches yet)
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
    # Simple word-by-word comparison
    current_clean = re.sub(r"[{}]", "", current)
    original_clean = re.sub(r"[{}]", "", original)

    current_words = current_clean.split()
    original_words = original_clean.split()

    if len(current_words) != len(original_words):
        return f"  Current:  {current}\n  Original: {original}"

    diff_words = []
    for cw, ow in zip(current_words, original_words):
        if cw.lower() == ow.lower() and cw != ow:
            diff_words.append(f"[{cw} → {ow}]")
        elif cw != ow:
            diff_words.append(f"[{cw} → {ow}]")

    if diff_words:
        return f"  Differences: {' '.join(diff_words)}"
    return ""


def parse_error_ids_from_report(report_path: str) -> List[str]:
    """Parse entry IDs that had errors from a previous report file."""
    error_ids = []
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find the LOOKUP ERRORS section
        in_error_section = False
        for line in content.split("\n"):
            if "LOOKUP ERRORS" in line:
                in_error_section = True
                continue
            if in_error_section:
                # Stop at next section
                if line.startswith("---") and "NO MATCH FOUND" in line:
                    break
                if line.startswith("==="):
                    break
                # Extract ID lines
                if line.startswith("ID: "):
                    error_ids.append(line[4:].strip())
    except FileNotFoundError:
        print(f"❌ Error: Report file not found: {report_path}")
    except Exception as e:
        print(f"❌ Error reading report file: {e}")

    return error_ids


def parse_full_report(
    report_path: str,
) -> Tuple[List[Dict], List[Dict], List[Dict], Dict]:
    """
    Parse a full report file to extract all sections.
    Returns (case_diffs, with_errors, no_match, metadata).
    """
    case_diffs = []
    with_errors = []
    no_match = []
    metadata = {"bib_path": "", "total": 0}

    try:
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        section = None
        current_entry = {}

        def save_current_entry():
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
            # Parse metadata
            if line.startswith("Generated from:"):
                metadata["bib_path"] = line.split(":", 1)[1].strip()
            elif line.startswith("Total entries checked:"):
                metadata["total"] = int(line.split(":")[1].strip())

            # Detect sections (check before === handling)
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

            # Skip separator lines
            if line.startswith("===") or line.startswith("---"):
                continue

            # Parse entries
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

        # Save last entry
        save_current_entry()

    except Exception as e:
        print(f"❌ Error parsing report: {e}")

    return case_diffs, with_errors, no_match, metadata


def merge_and_write_report(
    report_path: str,
    new_results: List[Dict],
    retried_ids: List[str],
    bib_path: str,
    total_entries: int,
):
    """
    Merge new retry results into an existing report.
    Replaces entries that were retried with their new results.
    """
    # Parse existing report
    old_case_diffs, old_with_errors, old_no_match, metadata = parse_full_report(
        report_path
    )

    # Remove retried entries from old lists
    retried_set = set(retried_ids)
    old_with_errors = [e for e in old_with_errors if e.get("id") not in retried_set]
    old_no_match = [e for e in old_no_match if e.get("id") not in retried_set]

    # Separate new results
    new_case_diffs = [r for r in new_results if not r.get("not_found")]
    new_not_found = [r for r in new_results if r.get("not_found")]
    new_with_errors = [
        r
        for r in new_not_found
        if any(ss.status == "error" for ss in r.get("source_statuses", []))
    ]
    new_no_match = [r for r in new_not_found if r not in new_with_errors]

    # Merge
    all_case_diffs = old_case_diffs + new_case_diffs
    all_with_errors = old_with_errors + new_with_errors
    all_no_match = old_no_match + new_no_match

    # Use original metadata if available
    if metadata.get("bib_path"):
        bib_path = metadata["bib_path"]
    if metadata.get("total"):
        total_entries = metadata["total"]

    # Write merged report
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"TITLE CHECK REPORT\n")
        f.write(f"Generated from: {bib_path}\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Total entries checked: {total_entries}\n")
        f.write(f"Entries with case differences: {len(all_case_diffs)}\n")
        f.write(f"Entries with lookup errors: {len(all_with_errors)}\n")
        f.write(f"Entries with no match found: {len(all_no_match)}\n\n")

        if all_case_diffs:
            f.write("=" * 80 + "\n")
            f.write("CASE DIFFERENCES FOUND:\n")
            f.write("=" * 80 + "\n\n")
            for r in all_case_diffs:
                f.write(f"ID: {r.get('id', r.get('ID', 'unknown'))}\n")
                f.write(f"Source: {r.get('source', 'unknown')}\n")
                f.write(f"Current:  {r.get('current_title', '')}\n")
                f.write(f"Original: {r.get('original_title', '')}\n")
                if r.get("url"):
                    f.write(f"URL: {r['url']}\n")
                f.write("\n")

        if all_with_errors or all_no_match:
            f.write("=" * 80 + "\n")
            f.write("NOT FOUND IN ANY SOURCE (need manual check):\n")
            f.write("=" * 80 + "\n\n")

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

    print(f"\n📝 Report updated: {report_path}")
    print(f"   Case differences: {len(all_case_diffs)}")
    print(f"   Lookup errors: {len(all_with_errors)}")
    print(f"   No match found: {len(all_no_match)}")


def check_titles(
    bib_path: str,
    output_path: Optional[str] = None,
    delay: float = 0.5,
    verbose: bool = True,
    filter_ids: Optional[List[str]] = None,
    log: Optional[Callable[[str], None]] = None,
) -> List[Dict]:
    """
    Check all titles in a bib file against external sources.
    Returns list of entries with differences.
    Sequential processing for maximum reliability.

    Args:
        filter_ids: If provided, only check entries with these IDs
        log: Optional logging function (default: print)
    """
    log = log or print

    # Load bib file
    with open(bib_path, "r", encoding="utf-8") as f:
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        bib_db = bibtexparser.load(f, parser=parser)

    # Filter entries if IDs specified
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

    log("\n" + "=" * 80)

    results = []
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

        # Track entries not found in any source
        if not matches:
            # Build detailed reason from source statuses
            if not source_statuses:
                reason = "No DOI, arXiv ID, or title to search"
            else:
                status_parts = []
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

        # Check for case differences
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
        log("")  # Clear progress line

    # Separate results
    not_found = [r for r in results if r.get("not_found")]
    case_diffs = [r for r in results if not r.get("not_found")]

    # Further separate not_found into errors vs no-match
    with_errors = [
        r
        for r in not_found
        if any(ss.status == "error" for ss in r.get("source_statuses", []))
    ]
    no_match = [r for r in not_found if r not in with_errors]

    # Print report
    log(f"\n📋 TITLE CHECK REPORT")
    log("=" * 80)
    log(f"Total entries checked: {total}")
    log(f"Entries with case differences: {len(case_diffs)}")
    log(f"Entries with lookup errors (network/API): {len(with_errors)}")
    log(f"Entries with no match found: {len(no_match)}")
    log("=" * 80 + "\n")

    if case_diffs:
        log("📝 CASE DIFFERENCES FOUND:")
        log("-" * 80)
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
        log("-" * 80)

        # Show entries with errors first
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

        # Show entries with no match (but no errors)
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

    # Write to file if requested
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"TITLE CHECK REPORT\n")
            f.write(f"Generated from: {bib_path}\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Total entries checked: {total}\n")
            f.write(f"Entries with case differences: {len(case_diffs)}\n")
            f.write(f"Entries not found in any source: {len(not_found)}\n\n")

            if case_diffs:
                f.write("=" * 80 + "\n")
                f.write("CASE DIFFERENCES FOUND:\n")
                f.write("=" * 80 + "\n\n")
                for r in case_diffs:
                    f.write(f"ID: {r['id']}\n")
                    f.write(f"Source: {r['source']}\n")
                    f.write(f"Current:  {r['current_title']}\n")
                    f.write(f"Original: {r['original_title']}\n")
                    if r["url"]:
                        f.write(f"URL: {r['url']}\n")
                    f.write("\n")

            if not_found:
                f.write("=" * 80 + "\n")
                f.write("NOT FOUND IN ANY SOURCE (need manual check):\n")
                f.write("=" * 80 + "\n\n")

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


def main():
    parser = argparse.ArgumentParser(
        description="Check BibTeX titles against external sources (CrossRef, DBLP, Semantic Scholar, arXiv)"
    )
    parser.add_argument("input", help="Path to the input BibTeX (.bib) file")
    parser.add_argument(
        "--delay",
        "-d",
        type=float,
        default=0.5,
        help="Delay between API requests in seconds (default: 0.5)",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress output",
    )
    parser.add_argument(
        "--retry-errors",
        metavar="REPORT",
        help="Re-check only entries that had errors in a previous report file",
    )
    parser.add_argument(
        "--ids",
        help="Comma-separated list of entry IDs to check (e.g., --ids ID1,ID2,ID3)",
    )

    args = parser.parse_args()

    # Auto-generate output path in repo directory
    repo_dir = get_repo_dir()
    input_path = Path(args.input)
    base_name = input_path.name
    output_path = repo_dir / f"{base_name}.title_report.txt"

    # Create unified logger
    with Logger("titleretriever", input_file=args.input) as logger:
        log = logger.log

        # Determine which entries to check
        filter_ids = None
        retry_report_path = None

        if args.retry_errors:
            filter_ids = parse_error_ids_from_report(args.retry_errors)
            if not filter_ids:
                log("No error entries found in the report file.")
                return
            log(f"📋 Found {len(filter_ids)} entries with errors to re-check")
            retry_report_path = args.retry_errors  # Will merge back into this report
        elif args.ids:
            filter_ids = [id.strip() for id in args.ids.split(",")]
            log(f"📋 Will check {len(filter_ids)} specified entries")

        # Run the check
        results = check_titles(
            args.input,
            output_path=(
                str(output_path) if not retry_report_path else None
            ),  # Don't write if retrying
            delay=args.delay,
            verbose=not args.quiet,
            filter_ids=filter_ids,
            log=log,
        )

        # If retrying, merge results back into original report
        if retry_report_path and results is not None and filter_ids is not None:
            merge_and_write_report(
                retry_report_path,
                results,
                filter_ids,
                args.input,
                len(filter_ids),
            )


if __name__ == "__main__":
    main()
