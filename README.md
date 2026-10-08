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

BibCC provides five commands through a single entry point — `bibcc`:

| Command | Description |
| --- | --- |
| `check` | Quality checks: missing fields, title case, term protection, citation keys |
| `complete` | Auto-fill missing BibTeX fields from the venue library |
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

**Venue library completeness** — check the venue library for missing fields:

```bash
bibcc check --check-venues
bibcc check --check-venues --journal-fields publisher,issn --proceedings-fields venue,month,isbn
```

**Combine checks** in one run:

```bash
bibcc check input.bib --fields month --title-case --quote --check-keys
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
| `--check-venues` | Check the venue library for missing fields (`--check-templates` still works) |
| `--venues FILE` | Venue library to check (default: `$BIBCC_VENUES` or the bundled library) |
| `--journal-fields FIELDS` | Fields to check in journal records (default: `publisher,issn`) |
| `--proceedings-fields FIELDS` | Fields to check in proceedings records (default: `venue,publisher,month`) |

</details>

---

### `complete` — Auto-fill Missing Fields

Fill missing BibTeX fields (publisher, ISSN, venue, month, …) from the venue library (see [Venue Library](#venue-library)). Existing fields are never overwritten: differences are reported as conflicts.

```bash
bibcc complete input.bib                    # preview (dry-run)
bibcc complete input.bib --output out.bib   # write completed output
```

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
| `--log-dir DIR` | Directory for logs and reports (default: `.bibcc/` next to the input) |
| `--venues FILE` | Venue library to use (default: `$BIBCC_VENUES` or the bundled library) |
| `--update-venues` | Merge the filled-in `*.missing_venues.yaml` into the library before completing (`--update-templates` still works) |

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
| `check` | `.missing_fields.txt`, `.title_case.txt`, `.smart_protection.txt`, `.citation_keys.txt` | `.bibcc/logs/*.checker.log` |
| `complete` | `.missing_venues.yaml`, `.missing_venues.txt`, `.conflicts.txt`, `.incomplete_entries.txt` | `.bibcc/logs/*.completer.log` |
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

The modified `.bib` file is not guaranteed to be well formatted. Use:

- [**BibTeX Tidy**](https://flamingtempura.github.io/bibtex-tidy/) for final formatting
- VS Code's LaTeX Workshop extension for better alignment

## 📋 TODO

- `complete` & venue library:
  - [x] ~~Unified venue management workflow.~~ Done — YAML venue library + `--update-venues` flag.
  - [x] ~~Aliases, ISSN matching, and previous-edition pre-fill.~~ Done.
  - [x] ~~Auto-guess fields from journal/conference names (publisher, issn, month).~~ Done — `# auto-guessed` markers in YAML.
  - [x] ~~Pre-fill YAML from existing bibliographies in the same venue.~~ Done — fields collected from bib entries.
- `check`:
  - [x] ~~Citation key legibility check.~~ Done — `--check-keys`.
  - [x] ~~Venue library missing fields check.~~ Done — `--check-venues`.
  - [x] ~~Robust term protection (skip numbers, filter author names).~~ Done — `--quote` with smart filtering.
  - [x] ~~Robust title case (hyphenated words, configurable style).~~ Done — `--title-case` with APA handling.
  - [x] ~~Interactive title case application.~~ Done — `--title-interactive`.
  - [x] ~~Modular sub-checker architecture.~~ Done — `checkers/` package.
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
