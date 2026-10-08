# 📚 BibTeX Check & Complete (BibCC)

A CLI toolkit to auto-complete missing BibTeX fields, check formatting quality, manage a reusable venue library, and align your PDF library with your bibliography.

> 👋 Thanks for attention!
>
> This is originally a small tool optimized for my own bibliography collecting workflow. And I am happy to see there are few stars on the project. I will start working on BibCC again ASAP to make it more universal, versatile and robust. Hope it can help anyone with the same demands as me.

## 🚀 Quick Start

BibCC is a Python package managed with [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/3hiuwoo/BibCC.git && cd BibCC
uv sync                       # create .venv with dependencies
uv run bibcc --help           # run from the checkout

uv tool install --editable .  # optional: put `bibcc` on your PATH
bibcc --help
```

The editable install keeps `bibcc` pointing at your checkout, so venue library updates and code changes apply immediately.

Run the tests with `uv run pytest`.

## 🧩 Commands

BibCC provides eight commands through a single entry point — `bibcc`:

| Command | Description |
| --- | --- |
| `check` | Quality checks: missing fields, title case, term protection, citation keys, field typos and duplicates |
| `complete` | Auto-fill missing BibTeX fields from the venue library |
| `add` | Fetch new papers by DOI, arXiv ID, or title into a staging `.bib` |
| `upgrade` | Replace arXiv preprints with their published versions, keeping keys |
| `format` | Reformat `.bib` files consistently: aligned fields, braced values, month macros, `--` page ranges |
| `librarian` | Align PDF library with `.bib`: missing / extra / rename |
| `scholar` | Citation counts and title verification via external APIs |
| `compose` | Merge per-folder `.bib` files into a single bibliography |

Run `bibcc <command> -h` for command-specific help.

---

### `check` — Quality Checks

Run one or more quality checks on a `.bib` file. All checks are independent and can be combined in a single invocation.

**Missing fields** — detect entries lacking required fields:

```bash
bibcc check input.bib --fields month
bibcc check input.bib --fields month,publisher --entry-types inproceedings,article
```

**Title case** — suggest APA-style title case corrections:

```bash
bibcc check input.bib --title-case
bibcc check input.bib --title-case --title-apply          # apply changes in-place
bibcc check input.bib --title-case --title-interactive    # review each suggestion
```

**Smart term protection** — suggest `{braces}` for technical terms, acronyms, and proper nouns:

```bash
bibcc check input.bib --quote
bibcc check input.bib --quote --quote-terms Gaussian,BERT
bibcc check input.bib --quote --quote-vocab-file my_terms.txt
```

**Citation key legibility** — check that keys follow `METHOD_AUTHOR_VENUEYEAR`:

```bash
bibcc check input.bib --check-keys
```

**Field names, values, and duplicates** — find mistakes BibTeX ignores silently:

```bash
bibcc check input.bib --check-fields
bibcc check input.bib --check-fields --against bib/          # also look for duplicates in other files
bibcc check input.bib --check-fields --known-fields code,pdf  # accept extra field names
```

- **Unknown fields**: names that are not standard BibTeX/biblatex fields or commonly exported ones (`abstract`, `keywords`, `numpages`, …). These are usually typos, which BibTeX drops without a warning. A likely correction is suggested: `'volumn' → did you mean 'volume'?`.
- **Values**: empty values, years that are not four digits, single-hyphen page ranges (`12-15` → `12--15`), DOIs written as URLs or malformed, months that are not macros (`{June}` → `jun`), malformed ISSNs, and URLs without `http(s)://`.
- **Duplicates**: the same paper (same DOI, arXiv ID, or title) or the same citation key twice, in the file or in the `--against` files. Conference and journal versions sometimes share a title, so check before deleting.

`bibcc format` fixes page ranges and months automatically. The other issues are only reported.

**Venue library completeness** — check the venue library for missing fields:

```bash
bibcc check --check-venues
bibcc check --check-venues --journal-fields publisher,issn --proceedings-fields venue,month,isbn
```

**Combine checks** in one run:

```bash
bibcc check input.bib --fields month --title-case --quote --check-keys --check-fields
```

<details>
<summary>All <code>check</code> options</summary>

| Option | Description |
| --- | --- |
| `--fields FIELDS` | Comma-separated required fields (default: `month`) |
| `--entry-types TYPES` | Comma-separated entry types to check (default: `inproceedings,article,proceedings,conference`) |
| `--title-case` | Check title case (APA style) |
| `--title-apply` | Apply title case changes in-place (implies `--title-case`) |
| `--title-interactive` | Interactive review per suggestion (implies `--title-case`) |
| `--title-style STYLE` | Title case style (default: `apa`) |
| `--extra-stopwords WORDS` | Additional stopwords to keep lowercase |
| `--quote` | Run smart term protection |
| `--quote-terms TERMS` | Extra terms to protect |
| `--quote-vocab-file FILE` | Newline-delimited vocabulary file |
| `--quote-no-default` | Disable built-in technical vocabulary |
| `--protection-min-length N` | Minimum word length for acronym detection (default: `3`) |
| `--check-keys` | Check citation key legibility |
| `--check-fields` | Check field names, field values, and duplicates |
| `--known-fields FIELDS` | Extra field names to accept with `--check-fields` |
| `--against PATH` | With `--check-fields`, also look for duplicates in this `.bib` file or directory; repeatable |
| `--check-venues` | Check the venue library for missing fields (`--check-templates` still works) |
| `--venues FILE` | Venue library to check (default: `$BIBCC_VENUES` or the bundled library) |
| `--journal-fields FIELDS` | Fields to check in journal records (default: `publisher,issn`) |
| `--proceedings-fields FIELDS` | Fields to check in proceedings records (default: `venue,publisher,month`) |

</details>

---

### `complete` — Auto-fill Missing Fields

Fill missing BibTeX fields (publisher, ISSN, venue, month, …) from the venue library (see [Venue Library](#venue-library)). Existing fields are never overwritten: differences are reported as conflicts.

```bash
bibcc complete input.bib                    # preview as a diff (dry-run)
bibcc complete input.bib --output out.bib   # write completed output
bibcc complete input.bib --in-place         # write back to input.bib
```

Edits are **minimal and verified**: new fields are inserted before each entry's closing brace, using the entry's own indentation and `=` alignment, and nothing else in the file changes (comments, field order, LaTeX, line endings). Months are written as macros (`month = jun`), matching what `add` and `format` produce. Before writing, the result is re-parsed and checked to contain the same entries with only the intended fields changed. If that check fails, nothing is written. The same safe editing is used by `check --title-apply`/`--title-interactive` and `scholar cite`.

When venues are missing from the library, a `.bibcc/<input>.missing_venues.yaml` file is generated. Fields are pre-filled from existing entries in the same journal/conference, from the **previous edition** of the same conference (e.g. CVPR 2025 → CVPR 2026: publisher, ISSN, month), and from venue-name guesses, so you only fill in what couldn't be inferred.

**Workflow** — generate YAML, update the library, and complete:

```bash
# 1. Run to generate the YAML (pre-filled where possible)
bibcc complete input.bib

# 2. Fill in remaining fields in .bibcc/input.bib.missing_venues.yaml

# 3. Merge into the library and complete in one step
bibcc complete input.bib --output out.bib --update-venues
```

<details>
<summary>All <code>complete</code> options</summary>

| Option | Description |
| --- | --- |
| `--output FILE` | Path to save the enhanced `.bib` file (omit for dry-run) |
| `--in-place` | Write the completed entries back to the input file |
| `--log-dir DIR` | Directory for logs and reports (default: `.bibcc/` next to the input) |
| `--venues FILE` | Venue library to use (default: `$BIBCC_VENUES` or the bundled library) |
| `--update-venues` | Merge the filled-in `*.missing_venues.yaml` into the library before completing (`--update-templates` still works) |

</details>

---

### `add` — Add New Papers

Fetch papers by DOI, arXiv ID/URL, or title and append them to a staging file (`added.bib` by default). Review the entries there, then move them into your topic files.

```bash
bibcc add 10.1109/TPAMI.2024.3429383 2501.13198 --against bib/
bibcc add "SD-LoRA: Scalable Decoupled Low-Rank Adaptation for Class Incremental Learning" --against bib/
bibcc add --from new_papers.txt --against bib/ --output added.bib   # one identifier per line
bibcc add 2501.13198 --dry-run                                        # print only
```

For each paper, `add`:

1. **Fetches metadata.** DOIs come from CrossRef, arXiv IDs from the arXiv API, and titles are matched through Semantic Scholar, then OpenReview, CrossRef, and arXiv. A title only counts as found when it matches exactly (ignoring case and punctuation).
2. **Prefers the published version.** For an arXiv paper it looks for a published version: the DOI linked from arXiv or known to Semantic Scholar, an accepted OpenReview paper (ICLR, NeurIPS, ICML, …; "Submitted to" and withdrawn papers are ignored), the DBLP key Semantic Scholar reports (e.g. `conf/iclr/...25` → ICLR 2025), or a CrossRef record with the same title. Conference booktitles come from the venue library. Pass `--preprint` to keep the arXiv entry.
3. **Skips duplicates.** Papers already in the `--against` files or directories (same DOI, arXiv ID, or title), or already in the staging file, are reported and skipped. A published paper whose preprint is already in your bibliography is flagged too.
4. **Formats the entry like the rest of the bibliography.** Title Case (APA), braces around acronyms and technical terms (`{SD-LoRA}`), `--` page ranges, month macros (`month = jun`), escaped `&`/`%`/`_`, and aligned `=`.
5. **Fills venue fields from the venue library.** Library values replace fetched ones (e.g. `publisher = {IEEE}` instead of CrossRef's long name). Unknown venues are listed; run `bibcc complete added.bib` to get the fill-in YAML.
6. **Suggests a key** `METHOD_AUTHOR_VENUEYEAR`. METHOD is the title's `Name:` prefix, or else its first two content words, so check it.

DBLP is not queried directly because its API is behind a bot challenge. Semantic Scholar allows few requests without a key; set `S2_API_KEY` for higher limits. Requests that hit a rate limit are retried with backoff.

<details>
<summary>All <code>add</code> options</summary>

| Option | Description |
| --- | --- |
| `IDENTIFIER ...` | DOIs, arXiv IDs or URLs, or quoted titles |
| `--from FILE` | Text file with one identifier per line (`#` starts a comment) |
| `--against PATH` | `.bib` file or directory (recursive) to check for duplicates; repeatable |
| `--output FILE` | Staging file new entries are appended to (default: `added.bib`) |
| `--venues FILE` | Venue library to use (default: `$BIBCC_VENUES` or the bundled library) |
| `--preprint` | Keep arXiv papers as preprints |
| `--keep-title` | Do not title-case fetched titles (term protection still applies) |
| `--dry-run` | Print the entries without writing |
| `--delay SECONDS` | Wait between papers to respect API limits (default: `1`) |
| `--log-dir DIR` | Directory for the log (default: `.bibcc/logs/` next to the output) |

</details>

---

### `upgrade` — Preprints to Published Versions

Find arXiv preprints in a `.bib` file that have since been published, and replace them with the published entry.

```bash
bibcc upgrade input.bib                        # dry run: report + diff in .bibcc/
bibcc upgrade input.bib --in-place             # write back to input.bib
bibcc upgrade input.bib --ids KeyA,KeyB --output out.bib
```

Preprints are `@misc`/`@unpublished` entries and entries whose journal is arXiv or CoRR. The published version is looked up the same way as in `add`. The replacement:

- **keeps the citation key**, so `\cite` commands keep working (a note suggests the conventional key, e.g. `..._ICML2026`);
- keeps your title when it matches the published one, so hand-made braces survive;
- keeps custom fields such as `citation`, and drops arXiv-only fields (`eprint`, `archiveprefix`, `primaryclass`, the arXiv `url`);
- fills venue fields from the venue library;
- is a whole-entry replacement checked like other edits: the rest of the file, including comments above the entry, stays byte for byte.

Preprints without a published version are listed as unchanged, with the arXiv comment when it says the paper was accepted (e.g. "Accepted at AAAI 2026") but is not indexed yet. Lookups that hit a rate limit are listed as failed; run again later or set `S2_API_KEY`.

<details>
<summary>All <code>upgrade</code> options</summary>

| Option | Description |
| --- | --- |
| `--output FILE` | Write the upgraded file here (omit for dry-run) |
| `--in-place` | Write back to the input file |
| `--ids KEYS` | Comma-separated citation keys to upgrade (default: all preprints) |
| `--venues FILE` | Venue library to use (default: `$BIBCC_VENUES` or the bundled library) |
| `--delay SECONDS` | Wait between entries to respect API limits (default: `1`) |
| `--log-dir DIR` | Directory for reports and logs (default: `.bibcc/` next to the input) |

</details>

---

### `format` — Consistent Formatting

Reformat whole `.bib` files, like BibTeX Tidy. Unlike the other commands, which only touch the fields they change, `format` rewrites the layout of every entry.

```bash
bibcc format bib/                     # dry run: one diff per changed file in .bibcc/
bibcc format bib/ --in-place          # write the changes
bibcc format refs.bib --output out.bib
bibcc format bib/ --check             # write nothing; exit 1 if a file is not formatted (CI)
```

`PATH` can be `.bib` files or directories, which are searched recursively (`.bibcc/` folders are skipped). The default style:

```bibtex
@inproceedings{GKEAL_Zhuang_CVPR2023,
  title     = {{GKEAL}: {Gaussian} Kernel Embedded Analytic Learning ...},
  author    = {Zhuang, Huiping and Weng, Zhenyu and ...},
  year      = {2023},
  month     = jun,
  booktitle = {2023 {IEEE/CVF} Conference on Computer Vision and Pattern Recognition ({CVPR})}
}
```

- lowercase entry types and field names, two-space indent, `=` aligned to the longest field name;
- `"..."` values and bare numbers become `{...}`; values joined with `#` and macros such as `@string` names stay as they are;
- months become macros (`{June}`, `"6"`, `Jun.` → `jun`);
- page ranges use a double hyphen (`12-15`, `12 – 15` → `12--15`; lists such as `S1-S9, 20-22` are handled part by part);
- one blank line between entries and a single newline at the end of the file;
- field order is kept unless `--sort-fields` is given;
- values are otherwise copied exactly, including line breaks inside them;
- `%` comments and `@string`/`@comment`/`@preamble` blocks are kept. With `--sort-entries`, a comment directly above an entry moves with it, and `@string`/`@preamble` blocks stay at the top.

Every result is checked before anything is written: the file is parsed again and must contain the same entries, types, fields, and values (up to the conversions above), and formatting it a second time must change nothing. Files that fail the check, cannot be parsed, or have duplicate keys are reported and skipped.

<details>
<summary>All <code>format</code> options</summary>

| Option | Description |
| --- | --- |
| `PATH ...` | `.bib` files or directories (recursive) |
| `--in-place` | Write the formatted text back to each file |
| `-o`, `--output FILE` | Write the formatted file here (single input file only) |
| `--check` | Write nothing; exit 1 if any file would change |
| `--sort-fields` | Reorder fields by `--field-order`; other fields follow in source order |
| `--field-order LIST` | Comma-separated order for `--sort-fields` (default: the order `add` uses) |
| `--sort-entries` | Sort entries by citation key (case-insensitive) |
| `--keep-quotes` | Keep `"..."` values and bare numbers |
| `--keep-months` | Do not turn months into macros |
| `--keep-pages` | Do not turn page ranges into `--` ranges |
| `--no-align` | Write `name = value` without aligning `=` |
| `--indent N` | Field indent: number of spaces or `tab` (default: `2`) |
| `--blank-lines N` | Blank lines between entries (default: `1`) |
| `--trailing-comma` | Put a comma after the last field |
| `--drop-empty` | Remove fields with empty values (`{}` or `""`) |
| `--log-dir DIR` | Directory for diffs and logs (default: `.bibcc/` next to each input) |

</details>

---

### `librarian` — PDF Library Alignment

Align your PDF library with your bibliography. Three subcommands:

```bash
# Find bib entries whose PDFs are missing from your library
bibcc librarian missing input.bib papers.txt

# Find library PDFs not referenced in bib
bibcc librarian extra input.bib papers.txt

# Rename PDFs to citation-key names via title matching
bibcc librarian rename input.bib ~/Downloads/papers --dry-run   # preview
bibcc librarian rename input.bib ~/Downloads/papers             # apply
```

**Rename workflow**: Export PDFs from Zotero (or similar) with full titles in the filename (e.g., `Author 等 - 2025 - Full Paper Title.pdf`). The tool extracts titles from filenames, normalises them, and matches against bib entries for exact renaming — no manual ordering required.

---

### `scholar` — Citations & Title Verification

Two subcommands for web-based bibliography management.

**`cite`** — Google Scholar citation URLs and interactive citation fill:

```bash
bibcc scholar cite input.bib                         # dry-run: show URLs
bibcc scholar cite input.bib -i                      # interactive: fill counts
bibcc scholar cite input.bib --open --batch-size 10  # batch open in browser
bibcc scholar cite input.bib -i --include-filled     # re-check filled entries
```

**`titles`** — Verify paper titles against CrossRef, DBLP, Semantic Scholar, arXiv:

```bash
bibcc scholar titles input.bib
bibcc scholar titles input.bib --retry-errors report.txt  # retry failures
bibcc scholar titles input.bib --ids ID1,ID2              # specific entries
```

<details>
<summary>All <code>scholar</code> options</summary>

**cite:**

| Option | Description |
| --- | --- |
| `--interactive`, `-i` | Interactive citation fill (recommended) |
| `--open` | Batch open URLs in browser |
| `--batch-size N` | URLs per batch (default: `5`) |
| `--include-filled` | Include entries that already have citation values |
| `--output`, `-o FILE` | Output file (omit for dry-run) |

**titles:**

| Option | Description |
| --- | --- |
| `--delay`, `-d SECS` | API request delay (default: `0.5`) |
| `--quiet`, `-q` | Suppress progress output |
| `--retry-errors REPORT` | Re-check only error entries from a previous report |
| `--ids IDS` | Comma-separated entry IDs to check |

</details>

---

### `compose` — Merge `.bib` Files

Combine `.bib` files from a folder tree into a single bibliography:

```bash
bibcc compose compose ./my-bibs combined.bib
bibcc compose compose ./my-bibs combined.bib --no-dup-warning
```

Source path markers (`% === source: path/file.bib ===`) are inserted between files. All original comments are preserved. Duplicate entry IDs are warned by default.

---

## 📂 Output Files

Reports are written to a `.bibcc/` folder next to the input `.bib` file, and logs to `.bibcc/logs/`. For example, checking `bib/refs.bib` writes `bib/.bibcc/refs.bib.title_case.txt`. `complete` and `scholar cite` accept `--log-dir` to choose another folder. Add `.bibcc/` to the `.gitignore` of your bibliography project to keep these files out of version control.

| Command | Report Files | Log Files |
| --- | --- | --- |
| `check` | `.missing_fields.txt`, `.title_case.txt`, `.smart_protection.txt`, `.citation_keys.txt`, `.field_issues.txt` | `.bibcc/logs/*.checker.log` |
| `complete` | `.complete.diff` (dry-run preview), `.missing_venues.yaml`, `.missing_venues.txt`, `.conflicts.txt`, `.incomplete_entries.txt` | `.bibcc/logs/*.completer.log` |
| `add` | (entries appended to the staging `.bib`) | `.bibcc/logs/*.adder.log` |
| `upgrade` | `.upgrade.txt`, `.upgrade.diff` (dry-run preview) | `.bibcc/logs/*.upgrader.log` |
| `format` | `.format.diff` (dry-run preview) | `.bibcc/logs/*.formatter.log` |
| `scholar cite` | `.scholar_urls.txt` | `.bibcc/logs/*.scholar.cite.log` |
| `scholar titles` | `.title_report.txt` | `.bibcc/logs/*.scholar.titles.log` |
| `librarian` | `.missing_pdfs.txt`, `.extra_pdfs.txt`, `.rename_report.txt` | `.bibcc/logs/*.librarian.log` |
| `compose` | (composed `.bib` file) | `.bibcc/logs/*.composer.log` |

## 🗂️ Venue Library <a id="venue-library"></a>

The venue library powers `complete`. It is a YAML file, [`src/bibcc/data/venues.yaml`](src/bibcc/data/venues.yaml), with two lists:

```yaml
journals:                       # year-agnostic
  - name: Pattern Recognition
    aliases: [Pattern Recognit.]  # optional other spellings
    fields:
      publisher: Elsevier
      issn: 0031-3203
proceedings:                    # one record per publication year
  - name: Computer Vision -- ECCV 2024
    year: '2025'                # publication year, not the edition
    fields:
      venue: Milan, Italy
      series: Lecture Notes in Computer Science
```

Matching ignores braces, case, `\&` vs `&`, and extra spaces:

- **Journals** match by name, any alias, or ISSN.
- **Proceedings** match by name or alias **and** the entry's `year`.
- If several records match one entry, nothing is added and the entry is reported as ambiguous.

To use a library somewhere else (for example one kept with your paper), pass `--venues FILE` or set `BIBCC_VENUES`. See [`missing_venues.example.yaml`](missing_venues.example.yaml) for the format of the generated file.

### Adding New Venues

```bash
# 1. Run complete to generate YAML for unknown venues
bibcc complete input.bib

# 2. Edit .bibcc/input.bib.missing_venues.yaml — most fields are pre-filled

# 3. Merge into the library and complete in one step
bibcc complete input.bib --output out.bib --update-venues
```

Entries missing year or venue (e.g., arXiv preprints, misc entries) are reported in `*.incomplete_entries.txt` and skipped.

## 🔗 Additional Resources

Apart from `bibcc format`, BibCC keeps your existing formatting and only adds or replaces the fields it targets. Other formatters:

- [**BibTeX Tidy**](https://flamingtempura.github.io/bibtex-tidy/)
- VS Code's LaTeX Workshop extension

## 📋 TODO

- `complete` & venue library:
  - [x] ~~Unified venue management workflow.~~ Done — YAML venue library + `--update-venues` flag.
  - [x] ~~Aliases, ISSN matching, and previous-edition pre-fill.~~ Done.
  - [x] ~~Minimal, verified edits that keep the rest of the file untouched.~~ Done — `bibcc/bibedit.py`.
  - [x] ~~Auto-guess fields from journal/conference names (publisher, issn, month).~~ Done — `# auto-guessed` markers in YAML.
  - [x] ~~Pre-fill YAML from existing bibliographies in the same venue.~~ Done — fields collected from bib entries.
- `check`:
  - [x] ~~Citation key legibility check.~~ Done — `--check-keys`.
  - [x] ~~Field name typos, malformed values, and duplicate papers.~~ Done — `--check-fields`.
  - [x] ~~Venue library missing fields check.~~ Done — `--check-venues`.
  - [x] ~~Robust term protection (skip numbers, filter author names).~~ Done — `--quote` with smart filtering.
  - [x] ~~Robust title case (hyphenated words, configurable style).~~ Done — `--title-case` with APA handling.
  - [x] ~~Interactive title case application.~~ Done — `--title-interactive`.
  - [x] ~~Modular sub-checker architecture.~~ Done — `checkers/` package.
- `add`:
  - [x] ~~Add papers by DOI, arXiv ID, or title with duplicate checks.~~ Done — `bibcc add`.
  - [x] ~~Replace preprints with published versions.~~ Done — `bibcc upgrade`.
- `format`:
  - [x] ~~Whole-file formatting (alignment, braces, month macros, sorting).~~ Done — `bibcc format`.
- `librarian`:
  - [x] ~~Unified PDF library alignment (missing/extra/rename).~~ Done.
- `scholar`:
  - [x] ~~Unified citation + title tool.~~ Done — `cite` and `titles` subcommands.
- `compose`:
  - [x] ~~Folder-based .bib composition with comment preservation.~~ Done.
- CLI & output:
  - [x] ~~Unified CLI entry point.~~ Done — `bibcc`.
  - [x] ~~Consistent output formatting and logging.~~ Done — shared format constants and report writer.
  - [x] ~~Package the repo as an installable command-line tool.~~ Done — `pyproject.toml` + `uv`.
