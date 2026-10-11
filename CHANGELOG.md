# Changelog

This file lists notable changes to BibCC. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/). The version number lives only in [`src/bibcc/__init__.py`](src/bibcc/__init__.py).

## [0.3.1] - 2026-10-11

### Changed

- **Contributing**: The code conventions now live in `CONTRIBUTING.md`, which also says that user-facing text follows the Google developer documentation style guide. `CLAUDE.md` is no longer part of the repository.

## [0.3.0] - 2026-10-11

### Added

- **`add --fallback LEVEL`**: Builds the entry from the metadata that located the paper (CrossRef, Semantic Scholar, OpenReview, or arXiv) when its official BibTeX can't be downloaded. `none` (the default) keeps official BibTeX only. `missing` covers papers that have no official BibTeX to download (AAAI, ACM, Elsevier, unknown sources, and proceedings that aren't out yet), which otherwise get an empty entry. `all` also covers papers whose site can't be reached (network errors, rate limits, and bot protection), which otherwise fail. These entries are formatted like official ones, and the venue library's name and fields replace the metadata's. A `% BibCC: not the official BibTeX` comment before each entry says where the entry came from and where to get the official BibTeX.
- **`upgrade`**: Replaces entries built from metadata once their official BibTeX (or interim CVF Open Access or OpenReview BibTeX) can be downloaded, and removes their comment. `--report-only` lists these entries too.
- **`add` report**: `.bibcc/OUTPUT.add.txt` lists each paper's outcome (`official`, `interim`, `metadata`, `empty`, `failed`, or `duplicate`), key, title, source, and where to get its BibTeX. The end of the log lists the papers left for you to add by hand, with their URLs and the `--fallback` level that would have covered them.

### Changed

- **Branches**: `main` now holds only releases, so installing without a tag (`uv tool install git+https://github.com/3hiuwoo/BibCC`) gets the latest release, and the README on GitHub describes it. Development moves to the `dev` branch; to install it, add `@dev`.
- The README, the other docs, and the help pages follow the Google developer documentation style, with uppercase placeholders such as `INPUT` and `FILE.bib`.
- The `add` documentation says up front that many papers have no downloadable official BibTeX, and why.

## [0.2.0] - 2026-10-11

This is the first packaged version. BibCC becomes an installable `bibcc` command and gains commands to fetch, upgrade, and format entries. It also edits files minimally and verifiably.

### Added

- **Packaging and releases**: BibCC uses `pyproject.toml` and `uv`. To install a release, run `uv tool install git+https://github.com/3hiuwoo/BibCC@vX.Y.Z`. To install the development version, leave out the tag. `bibcc --version` prints the version. Releases are `vX.Y.Z` tags. Before it builds the wheel and creates the GitHub release, a GitHub Actions workflow checks each tag against the version and this changelog. Publishing to PyPI is ready to turn on. On every push and pull request, CI runs the lint, the tests on Python 3.10 to 3.14, and a wheel build. `CONTRIBUTING.md` describes the branches, versioning, and the release checklist.
- **License**: BibCC is released under the MIT License.
- **Venue library**: A YAML venue library replaces the Python templates. Journals match by name, alias, or ISSN. Proceedings match by name or alias, and by year.
- **User and project venue libraries**: BibCC ships no venue library; each user builds their own. The user library is `$BIBCC_VENUES` or, if that isn't set, `$XDG_CONFIG_HOME/bibcc/venues.yaml` (`~/.config/bibcc/venues.yaml`). A project library is the nearest `.bibcc-venues.yaml` in the directory of the `.bib` file or in a parent directory. Commands read both libraries, merged. Where both define a field of a venue, the project library's value wins. `complete --update-venues` writes to the user library unless you pass `--scope project`, and every command names the library file it reads or writes. `--venues FILE` uses one file instead of both. `check --check-venues` checks the user library and the project library separately.
- **`venues` command**: `where` shows the libraries that apply to a file, their sizes, the fields that the project library overrides, and which library is written. `init` creates an empty user library or project library. `import` merges a library file, a URL, or a shared library by name into the user library or project library. Where values differ, `import` keeps yours unless you pass `--overwrite`. `examples` lists the shared libraries.
- **Shared venue libraries**: `examples/venues/` holds shared libraries, starting with the MIAA lab's `miaa` library (30 journals, and 75 proceedings from 2016 to 2026). It isn't bundled; to use it, run `bibcc venues import miaa`. `examples/venues/README.md` explains how to contribute a library.
- **Interim booktitles**: A proceedings record can list the booktitles that CVF Open Access (`cvf`) and OpenReview (`openreview`) use before the proceedings are out (`interim:` in the library). Entries that cite such a name match the record but get only `venue` and `month`. BibCC reports these entries so that `upgrade` can replace them. The `miaa` library links the CVF names of CVPR, ICCV, WACV, and their workshops, and the OpenReview names of ICLR, ICML, and NeurIPS. It also has CVPR, WACV, ICLR, and ICML 2026.
- **`complete`**: The command has the following additions:
  - A new `--in-place` option. When you pass neither `--output` nor `--in-place`, `complete` does a dry run and writes a diff (`.complete.diff`).
  - The fill-in file for unknown venues (`.missing_venues.yaml`) is pre-filled from other entries of the same venue, from the previous edition of a conference, and from guesses based on the venue name. On every run, `complete` merges the file instead of overwriting it, so what you fill in is kept.
  - `--update-venues` merges the filled-in file into the library and completes the bibliography in one step.
  - Conflicts with the library are reported in every mode, including dry runs, together with interim booktitles.
  - `--online` (off by default) queries CrossRef about every entry with a DOI. It pre-fills the fill-in file (`# from CrossRef`), compares entries and their library records with CrossRef (`.venue_check.txt`), and suggests corrections to library records, commented out, at the end of the fill-in file. Fields are still added only from the library.
- **`add`**: Adds papers by DOI, arXiv ID or URL, paper page URL, or title to a staging `.bib` file. BibCC locates the paper through CrossRef, arXiv, Semantic Scholar, and OpenReview, preferring the published version of arXiv papers. The entry is the paper's official BibTeX from IEEE Xplore (CVPR, ICCV, WACV, and IEEE journals), Springer (ECCV, and Springer and Nature journals), PMLR (ICML, CoLLAs, and others), the NeurIPS and ICLR proceedings, OpenReview (ICLR up to 2023), ACL Anthology, IJCAI, or arXiv. Papers whose proceedings aren't out yet get interim CVF Open Access or OpenReview BibTeX. When no official BibTeX can be downloaded (AAAI, ACM, and Elsevier), `add` writes an empty entry with a comment that gives the title, the DOI, and where to get the BibTeX. Entries are formatted like the rest of the bibliography and completed from the venue library; differences are reported, never overwritten. `add` checks entries for duplicates against `--against` files and the staging file, and suggests a `METHOD_AUTHOR_VENUEYEAR` key for each. Venues missing from the library are proposed in `.missing_venues.yaml`.
- **`upgrade`**: Replaces preprints, and interim CVF Open Access or OpenReview entries, with the official BibTeX of their published version, keeping citation keys, matching titles, and custom fields. A preprint whose published version has no downloadable BibTeX is kept, and the report says where to get the BibTeX. Interim booktitles that the upgrade links to their proceedings are proposed in `.missing_venues.yaml`.
- **`upgrade --report-only PATH...`**: Lists the entries of any number of files and directories that now have a published version, with the venue and the URL of the official BibTeX, without downloading or changing anything (`.published.txt`).
- **`format`**: Reformats whole files: aligned fields, braced values with one pair of braces, commas after every field but the last (including missing ones), month macros, and `--` page ranges. It also has `--check` for CI, optional field and entry sorting, and a verification pass before writing.
- **`check --check-fields`**: Reports unknown field names with a suggested correction (for example, `volume` for `volumn`), malformed values (years, page ranges, DOIs, months, ISSNs, URLs, and empty values), and duplicate papers or keys, also across `--against` files.
- **`scholar titles`**: Falls back to a CrossRef title search when Semantic Scholar finds nothing. Semantic Scholar requests use `S2_API_KEY`, and they retry with backoff when rate limited.
- **Help pages**: The `-h` help of every command and subcommand has a description, examples, the output files, the exit status, and the environment variables.
- **Tests and lint**: A `pytest` suite with canned API responses (no network access), and `ruff` lint.

### Changed

- **Minimal, verified edits**: `complete`, `check --title-apply`, `check --title-interactive`, and `scholar cite` only insert or replace the fields they target, and `upgrade` only replaces the entries it upgrades. Everything else in the file, including comments, field order, and line endings, stays byte for byte the same. Each result is parsed again and checked before writing. If the check fails, nothing is written.
- **Output location**: Reports go to a `.bibcc/` directory next to the input file, and logs go to `.bibcc/logs/`, instead of the BibCC checkout.
- **Months**: `complete`, `add`, and `format` write months as BibTeX macros (`month = jun`).
- **`check`**: Checks for a missing `month` by default. To skip this check, pass `--fields ""`. `--protection-min-length` applies to acronyms and words with digits too, and its default is now `2`, so terms such as `AI` and `3D` are reported.
- **Renamed options**: `--check-templates` is now `--check-venues`, and `--update-templates` is now `--update-venues`. The old names still work.
- **Citation key check**: Venue keywords match whole words only, and abbreviations are looked up case-insensitively.
- **Title case**: The word after `--` and `---` (LaTeX dashes) is capitalized like a subtitle.
- **`check --title-style`**: Accepts only known styles (currently `apa`) instead of silently falling back to `apa`.
- **`librarian`**: Reads UTF-16 listings without a byte-order mark, UTF-8 listings with one, and quoted titles in `.bib` files.
- **`compose`**: Skips its own output file and `.bibcc/` directories, so the output can live inside the input directory.

### Fixed

- **`scholar titles`**: No longer queries DBLP, whose API now answers with a bot challenge. Previously, every entry without a DOI logged a DBLP error, and titles that Semantic Scholar couldn't find were reported as failed lookups that `--retry-errors` retried forever.
- **Multi-line titles**: Appear on one line in the `check --title-case` table and report, and in the `scholar titles` report, which `--retry-errors` reads back.
- **`check --check-fields`**: Says where a duplicate citation key is already used.
- **`check --quote`**: Prints a summary when no term needs protection.
- **arXiv IDs**: Old-style IDs (`hep-th/9901001`) are recognized in `eprint` and free-text fields.
- **Proceedings registered as journals**: When CrossRef registers proceedings as a journal, `add` and `upgrade` make `@inproceedings` entries.
- **Brace handling**: Braces are ignored when matching venue abbreviations in citation keys.
- **`add` and `upgrade`**: No longer crash on an entry with no non-empty fields.
- **Citation keys**: `Computer Vision and Pattern Recognition` booktitles (including CVF's 2025 name) abbreviate to `CVPR`, not `PR`.
- **`format`**: Keeps entries without fields (such as the empty entries that `add` writes) instead of refusing the file.
- **Title case**: The following cases are fixed:
  - Text attached to a braced group is left alone: `{G}aussian` and `{LoRA}s` no longer become `{G}Aussian` and `{LoRA}S`.
  - Words with a capital after the first letter (`PODNet`, `COntinual`) keep their casing instead of becoming `Podnet`.
  - Minor words that join a hyphenated compound stay lowercase (`Out-of-Distribution`, `Plug-and-Play`), except as its last part (`Plug-In`).
- **`complete` conflicts**: Ignore whitespace, LaTeX accents (`\"{a}` versus `ä`), and the hyphens in ISBNs and ISSNs, so only real differences are reported.
- **New fields stay aligned**: When `complete`, `check --title-apply`, or `scholar cite` adds a field whose name is longer than an entry's aligned `=` column, that entry's column is widened instead of leaving the new field out of line.
- **`librarian rename`**: No longer picks one of several entries that share a title (such as a conference paper and its journal version). It lists such PDFs as ambiguous and leaves them for you to rename.
- **Citation key years**: Accept the event year in these cases: a year named in the venue (`Computer Vision -- ECCV 2024`, published 2025), `@inproceedings` entries published the year after the event, and preprints keyed by the venue that accepted them (`..._AAAI2026` for a 2025 arXiv paper).
- **`miaa` venue library**: The AAAI 2021 record had the venue and `series` of ICML 2018 (Stockholm, Proceedings of Machine Learning Research), copied when the record was written. Its venue is now `Online`, and the series is removed.

### Removed

- The Python template modules (`templates.py` and `yaml2templates.py`), replaced by the YAML venue library.
- The unused `citer.py` and `titleretriever.py` modules, whose features live in `scholar`.

## Before 0.2.0

Before version 0.2.0, BibCC was a set of unversioned scripts that you ran with `python bibcc.py`: `check` (missing fields, title case, term protection, citation keys, and template fields), `complete` with Python templates, `librarian`, `scholar`, and `compose`.

[0.3.1]: https://github.com/3hiuwoo/BibCC/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/3hiuwoo/BibCC/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/3hiuwoo/BibCC/compare/7632476...v0.2.0
