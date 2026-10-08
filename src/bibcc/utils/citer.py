#!/usr/bin/env python3
"""
Citation Importer - Generate Google Scholar URLs and manage citation fields.

This tool helps with manual citation count entry by:
1. Finding entries missing 'citation' field or with empty citation
2. Generating Google Scholar search URLs for each
3. Opening URLs in browser (in batches or interactively)
4. Injecting citation values into the BibTeX file

Usage:
    # Preview mode - show entries and URLs without changes
    python utils/citer.py input.bib

    # Open URLs in browser (batch of 5)
    python utils/citer.py input.bib --open

    # Open with custom batch size
    python utils/citer.py input.bib --open --batch-size 10

    # Interactive mode - open URLs one by one and prompt for citation count
    python utils/citer.py input.bib --interactive

    # Write output with empty citation fields
    python utils/citer.py input.bib --output output.bib

    # Full workflow: open URLs and write output
    python utils/citer.py input.bib --open --output output.bib
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import bibtexparser

from bibcc.logging_utils import Logger, get_repo_dir


def clean_title_for_search(title: str) -> str:
    """Clean a BibTeX title for search queries."""
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


def build_scholar_url(title: str) -> str:
    """Build a Google Scholar search URL for a paper title."""
    clean_title = clean_title_for_search(title)
    # Use exact phrase match by wrapping in quotes
    encoded_title = urllib.parse.quote(f'"{clean_title}"')
    return f"https://scholar.google.com/scholar?q={encoded_title}"


def interactive_fill(
    input_path: Path,
    output_path: Path,
    entries_to_process: List[Dict[str, Any]],
    log: Callable[[str], None] = print,
) -> None:
    """
    Interactive mode: open URLs one by one and prompt for citation counts.

    Args:
        input_path: Path to input .bib file
        output_path: Path to output .bib file
        entries_to_process: List of entries needing citation
        log: Logging function
    """
    log("\n🎯 Interactive Fill Mode")
    log("=" * 70)
    log("For each entry, a Google Scholar tab will open.")
    log("Enter the citation count, or:")
    log("  - Press Enter to skip (leave empty)")
    log("  - Type 'q' to quit and save progress")
    log("  - Type 's' to skip without opening URL")
    log("=" * 70)

    # Build citation patches
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

        # Prompt before opening
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
            # Open Google Scholar
            url = build_scholar_url(title)
            webbrowser.open_new_tab(url)
            time.sleep(0.5)  # Give browser time to open

        # Prompt for citation count
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
            # Accept non-numeric input too (e.g., "~100", "N/A")
            patches[entry_id] = citation_input
            log(f"   ✅ Set citation = {citation_input}")

    # Summary
    log(f"\n{'=' * 70}")
    log(f"📊 Summary: {len(patches)} citation(s) collected out of {total} entries")

    if not patches:
        log("   No changes to write.")
        return

    # Write output
    log(f"\n✍️  Writing to: {output_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    with open(output_path, "w", encoding="utf-8") as f:
        current_entry_id: Optional[str] = None
        entry_has_citation: Dict[str, bool] = {}

        # First pass: check which entries have citation field
        for entry in entries_to_process:
            entry_id = entry.get("ID", "unknown")
            entry_has_citation[entry_id] = "citation" in entry

        for line in lines:
            # Check if this line starts a new entry
            entry_match = re.search(r"@\w+\s*\{\s*([^,]+),", line)
            if entry_match:
                current_entry_id = entry_match.group(1).strip()
                f.write(line)
                # If this entry needs citation and doesn't have one, inject it
                if current_entry_id in patches and not entry_has_citation.get(
                    current_entry_id, True
                ):
                    new_value = patches[current_entry_id]
                    f.write(f"  citation     = {{{new_value}}},\n")
                    del patches[current_entry_id]
                continue

            # Check if this is a citation field line (for entries that have one)
            citation_match = re.match(r"(\s*citation\s*=\s*\{)([^}]*)(\},?)", line)
            if citation_match and current_entry_id in patches:
                # Replace the citation value
                prefix, _, suffix = citation_match.groups()
                new_value = patches[current_entry_id]
                f.write(f"{prefix}{new_value}{suffix}\n")
                del patches[current_entry_id]
                continue

            f.write(line)

    updated_count = len(
        [e for e in entries_to_process if e.get("ID", "unknown") not in patches]
    )
    log(f"✅ Done! Updated {updated_count} entries.")
    log(f"   Saved to: {output_path}")


def main(
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
    """
    Main function to process BibTeX file for citation counts.

    Args:
        input_path: Path to input .bib file
        output_path: Path to output .bib file (empty = dry run)
        open_browser: Whether to open Google Scholar URLs in browser
        interactive: Whether to use interactive fill mode
        include_filled: Include entries that already have citation values
        batch_size: Number of URLs to open per batch
        dry_run: If True, don't write output file
        log_dir: Directory for log files
        log: Logging function
    """
    input_path = Path(input_path).resolve()

    if not input_path.exists():
        log(f"❌ File not found: {input_path}")
        return

    log(f"📖 Reading: {input_path}")

    # --- PASS 1: Parse and analyze ---
    with open(input_path, "r", encoding="utf-8") as f:
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        bib_db = bibtexparser.load(f, parser=parser)

    log(f"   Found {len(bib_db.entries)} entries")

    # Find entries missing 'citation' field OR with empty citation
    entries_to_process: List[Dict[str, Any]] = []
    entries_with_citation: List[Tuple[str, str]] = []  # (entry_id, citation_value)

    for entry in bib_db.entries:
        entry_id = entry.get("ID", "unknown")
        citation_val = entry.get("citation", None)

        if citation_val is None:
            # No citation field at all
            entries_to_process.append(entry)
        elif citation_val.strip() == "":
            # Empty citation field
            entries_to_process.append(entry)
        else:
            # Has non-empty citation
            entries_with_citation.append((entry_id, citation_val.strip()))

    log(f"   Entries with citation: {len(entries_with_citation)}")
    log(f"   Entries needing citation: {len(entries_to_process)}")

    # Show which entries are being skipped (have citations)
    if entries_with_citation and not include_filled:
        log(f"\n⏭️  Skipping entries with existing citations:")
        for entry_id, cit_val in entries_with_citation[:5]:
            display_val = cit_val[:20] + "..." if len(cit_val) > 20 else cit_val
            log(f"      {entry_id}: {display_val}")
        if len(entries_with_citation) > 5:
            log(f"      ... and {len(entries_with_citation) - 5} more")

    # If include_filled, add entries with existing citations to the process list
    if include_filled and entries_with_citation:
        log(
            f"\n🔄 Including {len(entries_with_citation)} entries with existing citations (--include-filled)"
        )
        for entry in bib_db.entries:
            entry_id = entry.get("ID", "unknown")
            citation_val = entry.get("citation", None)
            if citation_val is not None and citation_val.strip() != "":
                entries_to_process.append(entry)

    if not entries_to_process:
        log("\n✅ All entries already have citation values!")
        return

    # Interactive mode
    if interactive:
        output_path = Path(output_path).resolve() if output_path else input_path
        interactive_fill(input_path, output_path, entries_to_process, log)
        return

    if not entries_to_process:
        log("\n✅ All entries already have citation field!")
        return

    # Build URLs for entries without citation
    url_list: List[Tuple[str, str, str]] = []  # (entry_id, title, url)
    for entry in entries_to_process:
        entry_id = entry.get("ID", "unknown")
        title = entry.get("title", "")
        if title:
            url = build_scholar_url(title)
            url_list.append((entry_id, clean_title_for_search(title), url))
        else:
            log(f"   ⚠️  No title for entry: {entry_id}")

    # Display entries and URLs
    log(f"\n📋 Entries to process ({len(url_list)}):")
    log("-" * 70)
    for i, (entry_id, title, url) in enumerate(url_list, 1):
        # Truncate title for display
        display_title = title[:50] + "..." if len(title) > 50 else title
        log(f"  [{i:3d}] {entry_id}")
        log(f"        {display_title}")
        if not open_browser:
            log(f"        {url}")
    log("-" * 70)

    # Save URL list to file for reference
    repo_dir = get_repo_dir()
    output_dir = Path(log_dir) if log_dir else repo_dir
    output_dir.mkdir(parents=True, exist_ok=True)
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

    # Open URLs in browser if requested
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
                time.sleep(0.3)  # Small delay to avoid overwhelming browser

            if batch_num < total_batches - 1:
                log(f"\n   ⏸️  Opened {end_idx} of {len(url_list)} URLs.")
                try:
                    input("   Press Enter to open next batch (Ctrl+C to stop)...")
                except KeyboardInterrupt:
                    log("\n   Stopped by user.")
                    break

        log(f"\n✅ Opened {min(end_idx, len(url_list))} URLs in browser")

    # Build patches for empty citation fields
    patches: Dict[str, Dict[str, str]] = {}
    for entry in entries_to_process:
        entry_id = entry.get("ID", "unknown")
        patches[entry_id] = {"citation": ""}

    # Dry-run summary
    if dry_run:
        log("\n🧪 Dry-run: Would add empty 'citation' field to these entries:")
        for entry_id in list(patches.keys())[:10]:  # Show first 10
            log(f"   {entry_id}")
        if len(patches) > 10:
            log(f"   ... and {len(patches) - 10} more")
        log("\n💡 To write changes, run with --output <file.bib>")
        return

    # --- PASS 2: Write output with injected fields ---
    output_path = Path(output_path).resolve()
    log(f"\n✍️  Writing output: {output_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    with open(output_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line)

            # Check if this line starts an entry
            match = re.search(r"@\w+\s*\{\s*([^,]+),", line)
            if match:
                current_id = match.group(1).strip()
                if current_id in patches:
                    new_data = patches[current_id]
                    for key, val in new_data.items():
                        f.write(f"  {key:<12} = {{{val}}},\n")
                    del patches[current_id]

    log(f"✅ Done! Added empty 'citation' field to {len(entries_to_process)} entries.")
    log(f"   Output saved to: {output_path}")
    log("\n💡 Now fill in the citation counts from Google Scholar results!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate Google Scholar URLs and manage citation fields in BibTeX files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python citationimporter.py refs.bib                    # Preview mode
  python citationimporter.py refs.bib --open             # Open URLs in browser
  python citationimporter.py refs.bib --open --batch-size 10
  python citationimporter.py refs.bib --interactive      # Interactive fill mode
  python citationimporter.py refs.bib -i --include-filled  # Include all entries
  python citationimporter.py refs.bib --output refs.bib  # Add empty citation fields
  python citationimporter.py refs.bib --open --output refs.bib  # Full workflow
        """,
    )
    parser.add_argument("input", type=str, help="Path to the input BibTeX (.bib) file")
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Path to save output file with citation fields (omit for dry-run)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open Google Scholar URLs in browser (batch mode)",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Interactive mode: open URLs one by one and prompt for citation count",
    )
    parser.add_argument(
        "--include-filled",
        action="store_true",
        help="Include entries that already have non-empty citation values (default: skip them)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="Number of URLs to open per batch (default: 5)",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default="",
        help="Directory to write logs. Default: repo directory.",
    )
    args = parser.parse_args()

    # Interactive mode implies output to the same file
    if args.interactive and not args.output:
        args.output = args.input

    dry_run = not bool(args.output) and not args.interactive
    log_dir = Path(args.log_dir) if args.log_dir else None

    with Logger("citationimporter", input_file=args.input, log_dir=log_dir) as logger:
        main(
            args.input,
            args.output or args.input,
            open_browser=args.open,
            interactive=args.interactive,
            include_filled=args.include_filled,
            batch_size=args.batch_size,
            dry_run=dry_run,
            log_dir=log_dir,
            log=logger.log,
        )
