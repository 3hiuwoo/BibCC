# Changelog

Notable changes to BibCC. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/). The version number lives in [`src/bibcc/__init__.py`](src/bibcc/__init__.py) only.

## [0.2.0] - Unreleased

The first packaged version. BibCC becomes an installable `bibcc` command, gains commands to fetch, upgrade, and format entries, and edits files minimally and verifiably.

### Added

- **Packaging**: `pyproject.toml` and `uv`; install with `uv tool install --editable .` to get `bibcc` on your PATH. `bibcc --version` prints the version.
- **Venue library**: `src/bibcc/data/venues.yaml` replaces the Python templates. Journals match by name, alias, or ISSN; proceedings by name or alias and year. Use `--venues FILE` or `BIBCC_VENUES` to use another library.
- **`complete`**:
  - `--in-place`, and a dry-run diff (`.complete.diff`) when neither `--output` nor `--in-place` is given.
  - The fill-in file for unknown venues (`.missing_venues.yaml`) is pre-filled from other entries of the same venue, from the previous edition of a conference, and from venue-name guesses.
  - `--update-venues` merges the filled-in file into the library and completes in one step.
- **`add`**: fetch papers by DOI, arXiv ID or URL, or title (CrossRef, arXiv, Semantic Scholar, OpenReview) into a staging `.bib`. It prefers the published version of arXiv papers, skips duplicates of `--against` files, formats entries like the rest of the bibliography, fills venue fields (from the previous edition of a conference that is not in the library yet), and suggests a `METHOD_AUTHOR_VENUEYEAR` key.
- **`upgrade`**: replace arXiv preprints with their published versions, keeping citation keys, matching titles, and custom fields.
- **`format`**: reformat whole files (aligned fields, braced values, month macros, `--` page ranges), with `--check` for CI, optional field and entry sorting, and a verification pass before writing.
- **`check --check-fields`**: unknown field names with a suggested correction (`volumn` → `volume`), malformed values (years, page ranges, DOIs, months, ISSNs, URLs, empty values), and duplicate papers or keys, also across `--against` files.
- **`scholar titles`**: falls back to a CrossRef title search when Semantic Scholar finds nothing. Semantic Scholar requests use `S2_API_KEY` and retry with backoff when rate limited.
- **Help pages**: every command and subcommand has a description, examples, its output files, its exit status, and its environment variables in `-h`.
- **Tests and lint**: a `pytest` suite with canned API responses (no network access) and `ruff` lint.

### Changed

- **Minimal, verified edits**: `complete`, `check --title-apply`/`--title-interactive`, and `scholar cite` only insert or replace the fields they target, and `upgrade` only replaces the entries it upgrades. Everything else in the file, including comments, field order, and line endings, stays byte for byte. Each result is parsed again and checked before writing; if the check fails, nothing is written.
- **Output location**: reports go to a `.bibcc/` folder next to the input file, and logs to `.bibcc/logs/`, instead of the BibCC checkout.
- **Months** are written as BibTeX macros (`month = jun`) by `complete`, `add`, and `format`.
- **`check`** checks for a missing `month` by default (pass `--fields ""` to skip). `--protection-min-length` applies to acronyms and words with digits too, and its default is now 2, so terms such as `AI` and `3D` are reported.
- **Renamed options**: `--check-templates` is now `--check-venues`, and `--update-templates` is now `--update-venues`. The old names still work.
- **Citation key check**: venue keywords match whole words only, and abbreviations are looked up case-insensitively.
- **Title case**: the word after `--` and `---` (LaTeX dashes) is capitalized like a subtitle.
- **`check --title-style`** accepts only known styles (currently `apa`) instead of silently falling back to `apa`.
- **`librarian`** reads UTF-16 listings without a byte-order mark and UTF-8 listings with one, as well as quoted titles in `.bib` files.
- **`compose`** skips its own output file and `.bibcc/` folders, so the output can live inside the input folder.

### Fixed

- **`scholar titles`** no longer queries DBLP, whose API now answers with a bot challenge. Before, every entry without a DOI logged a DBLP error, and titles Semantic Scholar could not find were reported as failed lookups that `--retry-errors` retried forever.
- **Multi-line titles** are shown on one line in the `check --title-case` table and report and in the `scholar titles` report, which is read back by `--retry-errors`.
- **`check --check-fields`** says where a duplicate citation key is already used.
- **`check --quote`** prints a summary when no term needs protection.
- **arXiv IDs**: old-style IDs (`hep-th/9901001`) are recognized in `eprint` and free-text fields.
- **Proceedings registered as journals** in CrossRef become `@inproceedings` entries in `add` and `upgrade`.
- **Brace handling**: braces are ignored when matching venue abbreviations in citation keys.
- **`add` and `upgrade`** no longer crash on an entry with no non-empty fields.

### Removed

- The Python template modules (`templates.py`, `yaml2templates.py`), replaced by the YAML venue library.
- The unused `citer.py` and `titleretriever.py` modules, whose features live in `scholar`.

## Before 0.2.0

Unversioned scripts run with `python bibcc.py`: `check` (missing fields, title case, term protection, citation keys, template fields), `complete` with Python templates, `librarian`, `scholar`, and `compose`.

[0.2.0]: https://github.com/3hiuwoo/BibCC/compare/7632476...HEAD
