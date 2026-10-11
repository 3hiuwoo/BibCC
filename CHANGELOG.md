# Changelog

Notable changes to BibCC. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/). The version number lives in [`src/bibcc/__init__.py`](src/bibcc/__init__.py) only.

## [0.3.0] - Unreleased

## [0.2.0] - 2026-10-11

The first packaged version. BibCC becomes an installable `bibcc` command, gains commands to fetch, upgrade, and format entries, and edits files minimally and verifiably.

### Added

- **Packaging and releases**: `pyproject.toml` and `uv`. Install a release with `uv tool install git+https://github.com/3hiuwoo/BibCC@vX.Y.Z`, or the development version without the tag. `bibcc --version` prints the version. Releases are `vX.Y.Z` tags, which a GitHub Actions workflow checks against the version and this changelog before it builds the wheel and creates the GitHub release. Publishing to PyPI is ready to switch on. CI runs the lint, the tests on Python 3.10 to 3.14, and a wheel build on every push and pull request. Branches, versioning, and the release checklist are in `CONTRIBUTING.md`.
- **License**: BibCC is released under the MIT License.
- **Venue library**: a YAML venue library replaces the Python templates. Journals match by name, alias, or ISSN; proceedings by name or alias and year.
- **User and project venue libraries**: BibCC ships no venue library; each user builds their own. The user library is `$BIBCC_VENUES`, else `$XDG_CONFIG_HOME/bibcc/venues.yaml` (`~/.config/bibcc/venues.yaml`). A project library is the nearest `.bibcc-venues.yaml` in the folder of the `.bib` file or a parent folder. Commands read both, merged, and where both define a field of a venue the project's value wins. `complete --update-venues` writes to the user library unless `--scope project` is given, and every command names the library file it reads or writes. `--venues FILE` uses one file instead of both. `check --check-venues` checks the user and project libraries, each on its own.
- **`venues`** command: `where` shows the libraries that apply to a file, their sizes, the fields the project overrides, and which library is written. `init` creates an empty user or project library. `import` merges a library file, a URL, or a shared library by name into the user or project library, keeping your values where they differ unless `--overwrite` is given. `examples` lists the shared libraries.
- **Shared venue libraries** in `examples/venues/`, starting with the MIAA lab's `miaa` (30 journals, 75 proceedings from 2016 to 2026). It is not bundled; import it with `bibcc venues import miaa`. `examples/venues/README.md` explains how to contribute one.
- **Interim booktitles**: a proceedings record can list the booktitles CVF Open Access (`cvf`) and OpenReview (`openreview`) use before the proceedings are out (`interim:` in the library). Entries citing such a name match the record but only get `venue` and `month`, and are reported so `upgrade` can replace them. The `miaa` library links the CVF names of CVPR, ICCV, WACV, and their workshops, and the OpenReview names of ICLR, ICML, and NeurIPS, and has CVPR, WACV, ICLR, and ICML 2026.
- **`complete`**:
  - `--in-place`, and a dry-run diff (`.complete.diff`) when neither `--output` nor `--in-place` is given.
  - The fill-in file for unknown venues (`.missing_venues.yaml`) is pre-filled from other entries of the same venue, from the previous edition of a conference, and from venue-name guesses. It is merged, not overwritten, on every run, so what you filled in is kept.
  - `--update-venues` merges the filled-in file into the library and completes in one step.
  - Conflicts with the library are reported in every mode, dry run included, together with interim booktitles.
  - `--online` (off by default) asks CrossRef about every entry with a DOI: it pre-fills the fill-in file (`# from CrossRef`), compares entries and their library records with CrossRef (`.venue_check.txt`), and suggests corrections to library records, commented out, at the end of the fill-in file. Fields are still only added from the library.
- **`add`**: add papers by DOI, arXiv ID or URL, paper page URL, or title into a staging `.bib`. The paper is located through CrossRef, arXiv, Semantic Scholar, and OpenReview (preferring the published version of arXiv papers), and the entry is its **official BibTeX**: IEEE Xplore (CVPR, ICCV, WACV, IEEE journals), Springer (ECCV, Springer and Nature journals), PMLR (ICML, CoLLAs, ...), the NeurIPS and ICLR proceedings, OpenReview (ICLR up to 2023), ACL Anthology, IJCAI, or arXiv. Papers whose proceedings are not out yet get interim CVF Open Access or OpenReview BibTeX. When no official BibTeX can be downloaded (AAAI, ACM, Elsevier), an empty entry is written with a comment giving the title, DOI, and where to get the BibTeX. Entries are formatted like the rest of the bibliography, completed from the venue library (differences are reported, never overwritten), checked for duplicates against `--against` files and the staging file, and get a suggested `METHOD_AUTHOR_VENUEYEAR` key. Venues missing from the library are proposed in `.missing_venues.yaml`.
- **`upgrade`**: replace preprints, and interim CVF Open Access or OpenReview entries, with the official BibTeX of their published version, keeping citation keys, matching titles, and custom fields. A preprint whose published version has no downloadable BibTeX is kept, and the report says where to get it. Interim booktitles the upgrade links to their proceedings are proposed in `.missing_venues.yaml`.
- **`upgrade --report-only PATH...`**: list the entries of any number of files and directories that now have a published version, with the venue and the URL of the official BibTeX, without downloading or changing anything (`.published.txt`).
- **`format`**: reformat whole files (aligned fields, braced values with one pair of braces, commas after every field but the last, including missing ones, month macros, `--` page ranges), with `--check` for CI, optional field and entry sorting, and a verification pass before writing.
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
- **Citation keys**: `Computer Vision and Pattern Recognition` booktitles (including CVF's 2025 name) abbreviate to `CVPR`, not `PR`.
- **`format`** keeps entries without fields (such as the empty entries `add` writes) instead of refusing the file.
- **Title case**:
  - Text glued to a braced group is left alone: `{G}aussian` and `{LoRA}s` no longer become `{G}Aussian` and `{LoRA}S`.
  - Words with a capital after the first letter (`PODNet`, `COntinual`) keep their casing instead of becoming `Podnet`.
  - Minor words joining a hyphenated compound stay lowercase (`Out-of-Distribution`, `Plug-and-Play`), except as its last part (`Plug-In`).
- **`complete` conflicts** ignore whitespace, LaTeX accents (`\"{a}` vs `ä`), and the hyphens in ISBNs and ISSNs, so only real differences are reported.
- **New fields stay aligned**: when `complete`, `check --title-apply`, or `scholar cite` add a field whose name is longer than an entry's aligned `=` column, that entry's column is widened instead of leaving the new field out of line.
- **`librarian rename`** no longer picks one of several entries that share a title (a conference paper and its journal version); such PDFs are listed as ambiguous and left for you to rename.
- **Citation key years** accept the event year: a year named in the venue (`Computer Vision -- ECCV 2024`, published 2025), `@inproceedings` published the year after the event, and preprints keyed by the venue that accepted them (`..._AAAI2026` for a 2025 arXiv paper).
- **`miaa` venue library**: the AAAI 2021 record had the venue and `series` of ICML 2018 (Stockholm, Proceedings of Machine Learning Research), copied when the record was written; its venue is now `Online` and the series is gone.

### Removed

- The Python template modules (`templates.py`, `yaml2templates.py`), replaced by the YAML venue library.
- The unused `citer.py` and `titleretriever.py` modules, whose features live in `scholar`.

## Before 0.2.0

Unversioned scripts run with `python bibcc.py`: `check` (missing fields, title case, term protection, citation keys, template fields), `complete` with Python templates, `librarian`, `scholar`, and `compose`.

[0.3.0]: https://github.com/3hiuwoo/BibCC/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/3hiuwoo/BibCC/compare/7632476...v0.2.0
