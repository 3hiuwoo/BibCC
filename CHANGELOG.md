# Changelog

This file lists notable changes to BibCC. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/). The version number lives only in [`src/bibcc/__init__.py`](src/bibcc/__init__.py).

## [0.9.0] - Unreleased

### Added

- **BibCC Workbench, a browser version**: The static page in `web/` runs `format`, `complete`, and the offline checks on a `.bib` file that you paste, through Pyodide, and you copy or download the result. It shows each command's output, a diff from what you pasted, and the reports that BibCC writes. It can load the `miaa` profile, and when a command changes the venue library, terms, or config, the page shows the new file. Commands that go online point you to the terminal. `scripts/build_web_bundle.py` builds the Python bundle that the page loads.

### Changed

- **The `miaa` venue library gains NeurIPS 2019 and 2020 and the books of its LNCS proceedings**: It now has 79 proceedings, with records for NeurIPS 2019 and 2020 and their schemas, and the volume and part of 41 books in the `books` tables of ECCV 2016 to 2026, MICCAI 2024, ICIC 2024, and ICANN 2021. Those three records gain their `series`, ICLR 2024 and 2026 gain their `editor`, and the `publisher` of ACL and IJCAI moves into their family records.

### Fixed

- **`check official` compares names in either form**: An `author` or `editor` written `First Last` in the entry and `Last, First` in the official BibTeX no longer counts as `differs`. A name whose parts differ, such as a different last name, still does.
- **`check official` no longer proposes a book's ISBN for a proceedings in several books**: For a proceedings whose record has a `books` table, or whose checked chapters belong to more than one book, the ISBN of a chapter is its book's, so the venue summary no longer reports it as `library_lacks` or `library_differs`.
- **A paper missing from an older year's proceedings isn't `wait`**: When the NeurIPS or ICLR proceedings of a year before last don't list a paper, the reason is "not found in the proceedings", and `next` is `by hand`, because those proceedings are complete. This year's and last year's are still `wait`.
- **PMLR papers are found by their own page**: When an entry's `url` is its PMLR paper page, `check official` reads the BibTeX there, so a paper whose `year` is the publication year rather than the conference's, such as CoLLAs 2024 in PMLR volume 274, is no longer looked up in the wrong volume.
- **An OpenReview paper that isn't found names the entry's forum page**: When the OpenReview search finds no accepted paper, the `url` column of `official_unchecked.txt` gives the entry's own OpenReview `url`, where you can get the BibTeX, instead of staying empty.
- **`check editions` groups the venues without a schema regardless of case**: Spellings that differ only in case, such as "Psychological Review" and "Psychological review", count as one venue, as the venue library matches them.
- **The `--learn` summary of `check official` counts schemas and book fields apart**: It says, for example, "Wrote 0 venue schemas and 2 book fields", instead of adding both into one count of venue schemas.

## [0.8.0] - 2026-10-16

### Added

- **Config files**: A user config (`$BIBCC_CONFIG`, or else `~/.config/bibcc/config.yaml`) and a project config (`.bibcc.yaml`, the nearest one above the `.bib` file) hold your settings, in the same two scopes as the venue library. Where both set a key, the project's value wins, and a command-line option wins over both. Each command reads its own section; `format` reads `format:`, which takes every style option of `format`. An invalid value stops the command for the files that the config applies to, and a key, section, or `field_order` field name that BibCC doesn't know is reported in the log.
- **`bibcc config`**: Manages the config files. `where` shows the files that apply to a path and each setting with where it comes from, `init` writes a config that lists every setting commented out, `import` merges a config file, URL, or shared config into the user or project config (keeping your values unless you pass `--overwrite`, and changing only the lines of the settings that it adds or updates, so your comments stay), and `examples` lists the shared configs in `examples/config/`, starting with the MIAA lab's `miaa`.
- **A place for unlisted fields in the field order**: In `format --field-order`, a `*` marks where the fields that the order doesn't list go, in source order, so `title,author,*,citation` keeps `citation` last whatever fields an entry has. In a config file, `field_order` takes `first` and `last` lists, with the other fields between them.
- **`format --config FILE` and `--no-config`**: Use one config file instead of the user and project configs, or read none.
- **`check venues --apply`**: Moves the values that every published edition of a conference shares, such as the `publisher` and `issn` of CVPR, into the conference's family record, and removes them from the editions. It creates the family record when it's missing, with the provider table's acronym when the table knows the conference. An edition keeps a value that differs only in braces or case, so no edition's fields change. `check venues --scope user` or `--scope project` checks, and with `--apply` rewrites, only that library.
- **`bibcc venues providers`**: Prints the provider table that applies to a path: for each conference, where its official BibTeX comes from, where it comes from before the proceedings are out, and whether the row is built in or set by a family record of your venue libraries. `--format json` prints it for scripts.
- **Protected terms in two scopes**: A user terms file (`$BIBCC_TERMS`, or else `~/.config/bibcc/terms.txt`) and a project terms file (`.bibcc-terms.txt`, the nearest one above the `.bib` file) hold the terms that `check quote` keeps in braces, such as `CLIP`, `LoRA`, and `CIP-Net`. `check quote` reads both, and `--apply` braces their terms, as it does the `--terms` and `--vocab-file` terms.
- **`bibcc config profile`**: Imports a lab profile, the shared config, venue library, and terms file of one name, such as `miaa`, into your user files or, with `--scope project`, into the project's files. It skips a kind that has no shared file of that name, and `--dry-run` previews the changes.
- **`bibcc terms`**: Manages the terms files. `where` shows the files that apply to a path, `list` prints every term with its scope, `add` adds terms, `import` adds the terms of a file, URL, or shared list, and `examples` lists the shared lists in `examples/terms/`, starting with the MIAA lab's `miaa`. `add` and `import` write to the user file, the project file (`--scope project`), or the file that `--terms FILE` names, as `venues import --venues FILE` and `config import --config FILE` do.
- **Schemas of venues without a record go into `missing_venues.yaml`**: When `check official --learn` or `check editions --learn` learns a schema for a journal or an edition that the venue library has no record of, it writes the record, with its schema (`entry_fields` and `learned_from`), into `.bibcc/INPUT/missing_venues.yaml`, instead of dropping the schema. The record's fields come pre-filled from the official BibTeX, or from the entries, and a record that an earlier `complete` run proposed there gets the schema added. One `complete --update-venues` then adds the record and its schema.
- **Per-book fields for proceedings in several books**: A proceedings record can list the `volume` and `part` of each of its books under `books`, keyed by the book's ISBN as it appears in its chapters' DOIs, for the LNCS volumes of ECCV and MICCAI, whose Springer chapter exports lack both. `complete` fills them in by DOI, and `check official` no longer reports them as `local_only`. When the entries of a book agree on a value that the table lacks, `check official` reports it (`books_lack` in `official_venues.txt`), and `--learn` writes it.
- **`export_lacks` in the `check official` venue summary**: A field that every checked entry of a venue and year has (at least two entries), and that no official BibTeX has, gets one row for the venue in `official_venues.txt`, the reverse of `entries_lack`.
- **Publisher default schemas in `check editions`**: For a venue without a schema, `check editions` reports the fields of its publisher's default schema that an entry lacks (`default_missing`). The default holds the fields that most of the library's schemas of the same publisher and kind share; the publisher comes from the venue record, the entry, the venue name, or the DOI prefix. A default is a labeled guess: it never replaces a venue's own schema, `--learn` never writes it, and `--strict` doesn't count it.

### Changed

- **`check quote --interactive` remembers kept compounds in a terms file**: A compound that you keep whole goes to the user terms file, or with `--scope project` to the project terms file, instead of `.bibcc/INPUT/vocab.txt`, so it stays whole in every file of the project and your coauthors can share it. `check quote` still reads `.bibcc/INPUT/vocab.txt`.
- **A record named by its interim booktitle gets no family fields**: A proceedings record still named by its CVF Open Access or OpenReview booktitle describes proceedings that aren't out yet, so `complete` no longer gives its entries the published fields of the family record, such as an IEEE `publisher`.
- **`format` yes-or-no options have a `--no-` form**: `--no-sort-fields`, `--no-keep-quotes`, `--no-drop-empty`, and so on turn off a setting that a config file turns on, and `--align` turns alignment back on after a config's `align: false`. `--no-align` works as before.
- **`config where` lists every file that applies**: After the settings, it lists the venue libraries, the terms files, and the provider table that apply to the path, each with its scope and size.
- **A first run points to a shared profile**: When you have no venue library file yet, `complete`, `add`, and `upgrade` say how to copy a shared profile's config, venue library, and terms into your user files with `bibcc config profile NAME`, or only its venues with `bibcc venues import NAME`. `config where`, `venues where`, and `terms where` give the same hint when no file of their kind exists. A library file that exists but is empty still gets the earlier hint.
- **New project files go next to the others**: When a command creates a project file, such as `venues import --scope project` or `check quote --interactive --scope project`, it puts the file next to the project's existing BibCC files instead of in the current directory, so a command that you run from a subdirectory doesn't start a second project. `init --scope project` still writes to the current directory.
- **The `miaa` venue library has a schema for every family**: It gains three journals (Artificial Intelligence Review, IEEE Robotics and Automation Letters, and Nature Machine Intelligence) and eleven family records, among them IJCAI, ACL, MICCAI, Interspeech, ICIP, and the ICCV workshops. Every family record and 22 of its 33 journals now have a venue schema. The schemas of AAAI, ACM MM, and four Elsevier journals come from the entries alone, because their publishers block BibTeX downloads; NeurIPS 2017 and 2018 and ICML 2018 and 2019 have schemas of their own.

### Fixed

- **`check official` and `complete --online` compare family fields**: The library comparison of `check official` (`library_lacks` and `library_differs`) and the CrossRef check of `complete --online` now use a record's fields together with those of its family record, so a `publisher` that the family supplies is no longer reported as missing. When the differing value comes from the family record, the detail says so. An entry field that the family record supplies doesn't count as `local_only` either.
- **`check official` no longer proposes a month for a journal record**: Each issue of a journal has its own month, so `library_lacks` and `library_differs` leave out a journal's `month`.
- **Learning from an older year keeps a newer schema**: `check official --learn` no longer replaces a family or journal schema that was learned from a later year, so checking files one at a time gives the same schemas in any order. The older year gets its own schema on its edition record when its fields differ. When a later year replaces a family schema, the old schema moves to the edition records of the years that it was learned from.
- **A book chapter doesn't count toward a schema**: Schema learning and the `check editions` list of venues without a schema leave out books and chapters (`@book`, `@inbook`, `@incollection`), so a chapter's book no longer becomes a conference family record.
- **IJCAI editions form one family**: A trailing edition tag with a two-digit year, such as `{IJCAI-24}` in IJCAI's booktitle, no longer keeps the editions apart, so `check venues`, `check editions`, and schema learning treat IJCAI as one conference, and the provider table recognizes its name.

## [0.7.1] - 2026-10-15

### Fixed

- **CI accepts the provider table in the wheel**: The build check that keeps venue libraries out of the wheel no longer fails on `bibcc/data/families.yaml`, the provider table that 0.7.0 ships. It now also fails when the wheel lacks that file.

## [0.7.0] - 2026-10-15

### Added

- **`bibcc surface`**: Prints a JSON document describing the command surface: every command and subcommand with its options, the report files BibCC writes, and the status and `next` words its reports use. Tools and agent skills that track BibCC read it to detect when a release changes a command or an option, instead of scraping the help pages. `--format text` prints a short human-readable listing. It also lists the `issue_type` words of the check reports.
- **Family records in the venue library**: A new `families` list describes a conference across its editions. Its `fields` apply to every edition (an edition's own value wins), so a value such as ICML's `publisher` lives in one place; `complete`, `add`, and `upgrade` use them, the fill-in YAML shows them commented out as `# from family NAME`, and `check venues` lists the families, doesn't report their fields as missing, and suggests moving a value that every edition shares into a family record. Every command that relates editions (the previous-edition pre-fill, `check venues`, and `check editions`) now groups them by family record, or else by their name without the year and ordinal. `venues import` merges family records too.
- **Venue schemas**: A journal, family, or proceedings record can carry `entry_fields`, the per-paper fields (such as `pages`, `doi`, and `url`) that the official BibTeX of every paper of the venue has, and `learned_from`, which says where they come from. `check official --learn` learns them from the BibTeX it downloads, and `official_venues.txt` reports a venue without a schema (`schema_lacks`) or with a different one (`schema_differs`). `--scope project` writes them to the project library.
- **`check missing` skips fields a venue never exports**: When the venue library has a schema for an entry's venue, `check missing` doesn't report a per-paper field that the schema leaves out, such as the `doi` of a NeurIPS paper, and lists the entry instead.
- **Provider facts in a table and in family records**: Where each conference's official BibTeX comes from (which conferences PMLR publishes, which ones use CVF Open Access before IEEE Xplore, the year ICLR's proceedings start, the DOI prefixes, and the blocked publishers) now lives in a data table that ships with BibCC, `src/bibcc/data/families.yaml`, instead of in code. A family record with the same acronym overrides its keys (`provider`, `site`, `interim`, `interim_since`, `pattern`, `workshop_of`, `acronym_aliases`, `blocked_by`, and `manual_url`), and one with a new acronym adds a conference, so a new PMLR conference needs no code change.
- **A disk cache of official BibTeX**: `add`, `upgrade`, and `check official` keep each paper's downloaded BibTeX for 30 days in `$BIBCC_CACHE`, or else `$XDG_CACHE_HOME/bibcc` (`~/.cache/bibcc`), so a later run on the same paper doesn't download it again. `BIBCC_CACHE=off` turns the cache off, and `check official --refresh` downloads everything again.

### Changed

- **`check editions` checks entries against their venue's schema**: The check now reports the fields of the venue's schema that an entry lacks, with the issue type `missing`, instead of comparing the entry with the other entries of its venue. A journal article not yet in an issue isn't expected to have a `volume`, `number`, or `pages`. For a venue without a schema, the check still compares the entries of the venue, in the input and the `--against` files, but only proposes a schema from them (`schema_lacks` in the new `edition_schemas.txt` report); `--learn` writes the proposals into the venue library and checks the entries against them. With `--strict`, every `missing` finding counts, and proposals don't.

### Removed

- **The `same_year` and `other_years` findings of `check editions`**: A schema in the venue library replaces them; to get one, run `check official --learn`, or `check editions --learn` for the venues whose BibTeX BibCC can't download.
- **The built-in `series` requirement of `check venues`**: The check no longer requires a `series` in ECCV and LNCS proceedings records by a rule in code. To give every ECCV edition its series, put `series` in an ECCV family record; to require it in every proceedings record, pass it in `--proceedings-fields`.

## [0.6.0] - 2026-10-14

### Added

- **`complete --resolve library`**: Overwrites entry fields that differ from the venue library with the library's values, for example after you fix a wrong value in a library record. `--fields FIELDS` narrows the fields the command may add or overwrite, and `--ids KEYS` narrows the entries; the reports still cover the whole file, and the conflicts left out of scope are listed as unchanged. Without `--resolve`, `complete` still never overwrites, and its conflict log points to the new option.
- **`complete --update-venues-only`**: Merges the filled-in `missing_venues.yaml` into the library and stops, without completing the `.bib` file, so that you can review the merged records first.
- **`check venues` compares the editions of a conference**: A new cross-edition section reports fields that one edition of a venue defines and another lacks, with the shared value as a suggestion when every edition that has the field agrees. Pointing `--venues` at a `missing_venues.yaml` fill-in file checks only the records you're about to merge. Editions are grouped by their name without the year and ordinal, so ICML (`Proceedings of the 41st International Conference on Machine Learning`), ECCV (`Computer Vision -- ECCV 2024`, published in 2025), and ICLR (`The Eleventh International Conference on Learning Representations`) editions are compared too. A record still named by its interim booktitle is only checked for its event fields.
- **`check editions`**: A new check compares each entry with the other entries of its venue, in every edition, and reports the fields the entry lacks and the others have. A `same_year` finding means that most entries of the same year have the field; an `other_years` finding means that most other years have it, which can also mean that the venue changed its BibTeX. `--against PATH` adds the entries of other files to the comparison. The check ignores the fields every compared entry has (`title`, `author`, `year`, `booktitle`, `journal`), BibCC's own `citation` field, and exporter bookkeeping; `--ignore-fields` and `--include-fields` change that list. With `--strict`, only `same_year` findings count. The report is `.bibcc/INPUT/edition_fields.txt`.
- **`check official`**: A new check downloads the official BibTeX of each entry again, the same way `add` does, and compares it with the entry field by field: `upstream_only` (the official BibTeX has a field that the entry lacks), `differs`, `local_only`, and `type`. `--apply FIELDS` adds the official values of the named fields to the entries that lack them, and `--apply all` adds every `upstream_only` field; it never changes an existing value. A venue summary lists the fields that most entries of a venue lack, and compares the venue library records with the official values. For AAAI, ACM, and Elsevier papers, `--local PATH` takes BibTeX that you downloaded yourself, and `--offline` downloads nothing. The check skips preprints, interim entries, and entries built from metadata. The reports are `official_fields.txt`, `official_venues.txt`, and `official_unchecked.txt`.
- **`complete` says where pre-filled values come from**: In `missing_venues.yaml`, a value collected from your entries now names those entries in its comment (`# from bib (KEY, …)`), and the log lists the entries behind each pre-filled field of a missing venue.
- **`complete` and `add` name the entries behind each missing venue**: Each record in `missing_venues.yaml` gets an `# entries: KEY, …` comment, the `complete` log lists the entries under the venue, and `missing_venues.txt` gains an `entries` column.
- **`complete` names the library behind each patch**: With a user library and a project library, the log says, for every entry it patches, whether the venue record comes from the user library, the project library, or both.
- **`check quote` finds over-braced compounds**: A hyphenated or slashed compound braced as a whole when only some parts need braces is reported with the split form, so `{CLIP-Based}` gets the suggestion `{CLIP}-Based`. Compounds whose parts all need braces, such as `{SD-LoRA}`, `{R-CNN}`, and `{GPT-4}`, stay whole, and so do compounds that you list with `--terms` or `--vocab-file`. `check quote --apply` splits the reported compounds, and no longer needs terms to run.
- **`check quote --interactive`, and a vocabulary file the check always reads**: `--interactive` shows each over-braced compound one at a time, and you split it, skip it, edit the suggestion, or keep it whole. Keeping a compound whole also adds it to `.bibcc/INPUT/vocab.txt`, a per-input vocabulary file that `check quote` now always reads on top of `--terms` and `--vocab-file`, so a method name such as `CIP-Net`, whose parts don't all need braces, stays in one brace group for good. You can also write that file yourself, one term per line.
- **`check fields` finds interim fields**: A new `interim_field` finding reports fields that only an interim or preprint version of a paper has, left in an entry whose BibTeX now comes from somewhere else: a CVF Open Access `url` in IEEE Xplore BibTeX, an OpenReview `url` in proceedings BibTeX, and arXiv URLs, `eprint`, `archiveprefix`, `primaryclass`, and notes in a published entry. `check fields --apply` removes them, together with the fields that have empty values, and then reports what's left.
- **Venues without a month**: A venue library record can now say `month: none`, for a conference held across two months or a journal without monthly issues. Such a record never adds a month, `check missing` doesn't report its entries for a missing month (it lists them instead, and gains `--venues FILE`), `check editions` doesn't compare their month, and `complete` reports an entry's month as a conflict, which `--resolve library` removes together with its `day`. The `miaa` library uses it for WACV 2025, ICCV 2019, NeurIPS 2022, CoLLAs 2024, ECCV 2024, ACM MM 2024, The Web Conference 2025, ICLR 2018, and TMLR, and gains the month of ICLR 2025.
- **Conference papers exported as `@article`**: `add`, `upgrade`, and `check official` turn AAAI's `@article` BibTeX, whose `journal` names conference proceedings, into `@inproceedings` with that name as the `booktitle`, and report the change. `complete` does the same for BibTeX that you paste into an entry, and `check fields` reports such entries with the new `conference_article` finding.

### Changed

- **`check` runs one check for each subcommand**: Each check is now a subcommand (`missing`, `title`, `quote`, `keys`, `fields`, `editions`, `official`, and `venues`), and a run does only the check that you name, so you no longer pass `--fields ''` to skip the missing-month check. The options lose their prefixes: `--title-case --title-apply` becomes `check title --apply`, `--quote-terms` becomes `check quote --terms`, `--quote-vocab-file` becomes `--vocab-file`, `--quote-no-default` becomes `--no-default`, `--protection-min-length` becomes `--min-length`, `--title-style` becomes `--style`, `--check-keys` becomes `check keys`, `--check-fields` becomes `check fields`, and `--check-venues` (or its old name, `--check-templates`) becomes `check venues`. To run several checks, run `check` once for each.
- **Fewer false conflicts for LaTeX letters**: `complete` compares `Wo\l czyk` and `Wo{\l}czyk`, and `Kuci{\'n}ski` and `Kuci\'{n}ski`, as the same value.
- **`add` and `upgrade` keep every official field**: The entries keep every field of the official BibTeX, including `abstract`, `keywords`, `pdf`, `file`, and fields with empty values, which `add` used to drop. When the venue library has a value for an empty official field, `add` fills it in. To remove empty fields, run `bibcc check fields --apply` or `bibcc format --drop-empty`.
- **Months that span two months are dropped**: When official BibTeX gives a period across two months, such as PMLR's `29 Jul--01 Aug` for CoLLAs 2024, `add` and `upgrade` leave out the `month` and `day`, don't add the library's month either, and report it for the entry. Other official months stay as exported, including the issue month of AAAI and the online date that Springer gives journal articles.
- **No guessed months**: The missing-venues YAML file no longer copies the month from the previous edition or guesses it from the conference name, because editions move and some run across two months. Its `month` line explains the rule instead, and journal records get an optional `month` line for `none`. With `--online`, CrossRef pre-fills the month only when the event starts and ends in the same month.
- **Issue months from CrossRef**: An `@article` entry built from CrossRef metadata takes the month of the printed issue, and gets no month when CrossRef knows only the online date. An `@inproceedings` entry gets its month from the venue library instead of the proceedings' publication date.
- **Journals named "Proceedings of"**: A CrossRef journal article in a journal such as the Proceedings of the National Academy of Sciences stays `@article`; only names that mention a conference, workshop, symposium, meeting, or congress become `@inproceedings`.
- **Incomplete entries, separated**: `complete` lists the proceedings and journal entries that lack a year or a venue as entries to fix, and only counts the `@misc` ones (such as arXiv preprints), which aren't expected to have a venue. `incomplete_entries.txt` gains an entry-type column.
- **`add.txt` renames a column**: The sixth column of the `add` report is now headed `url` instead of `get it`, matching the `published.txt` report and the documentation.

## [0.5.0] - 2026-10-12

### Fixed

- `add` no longer merges braces across a hyphen or slash when only part of the word needs protection: `{CIP}-Net` stays `{CIP}-Net` instead of becoming `{CIP-Net}`. A compound whose parts all need protection still gets one group (`{SD}-Lo{RA}` becomes `{SD-LoRA}`).

## [0.4.0] - 2026-10-11

### Added

- **`add` with BibTeX that you downloaded yourself**: A `.bib` file or a directory of `.bib` files is now an identifier. `add` treats each entry as official BibTeX: it formats the entry, completes it from the venue library, and checks it for duplicates, without any lookup. A `% source: URL` comment line before an entry names where it came from, and the URL appears in the report.
- **`add` fills in empty entries**: A paper that matches an empty entry of the staging file (same DOI, arXiv ID, title, or key) replaces that entry in place and keeps its key. Before, `add` skipped the paper as a duplicate. An empty entry in an `--against` file still counts as present.
- **`add --retry`**: Looks up again the empty entries of the staging file and the papers that failed in its last report. You don't need to give any identifiers.
- **`add` manifests**: `--from` accepts a `.csv` or `.tsv` file with an `identifier` column and optional `method`, `venue`, `year`, and `key` columns that set the parts of the key. The `venue` column also helps `add` find the official source of a paper whose metadata names no venue.
- **`add` totals**: The end of each run gives the number of entries in the staging file, with and without fields.
- **`check --strict`**: Exits with status 1 when a check finds something or the file has empty entries, so scripts and agents can rely on the exit status.
- **`check --quote-apply`**: Wraps the terms from `--quote-terms` and `--quote-vocab-file` in braces in the titles, as a verified edit, and then reports what else might need braces. The built-in vocabulary and the other suggestions are never applied.
- **`check --check-keys`**: Also checks that the AUTHOR part of each key is the first author's surname. Part of a compound surname and names without accents are accepted.
- **`check` and empty entries**: `check` lists the empty entries that it skips, because they have no fields to check.
- **`librarian missing` and `extra` with several files and a PDF directory**: Both take any number of `.bib` files and directories, followed by the library, which can now be a directory of PDFs as well as a listing file. `missing --skip-empty` leaves out empty entries.
- **What to do next**: The reports of `add` (`add.txt`), `upgrade` (`upgrade.txt`), and `upgrade --report-only` (`published.txt`) have a new last column, `next`, that says what to do about each paper: `by hand`, `retry`, `check`, `wait`, or `upgrade`. The end of an `add` run groups the papers left to do by this column, and counts the interim entries that `upgrade` replaces later.

### Changed

- **Report layout**: Reports about an input now go to a directory of their own, `.bibcc/NAME/` (for example, `.bibcc/refs.bib/title_case.txt` instead of `.bibcc/refs.bib.title_case.txt`), and logs go to `.bibcc/NAME/logs/TOOL.log`. `--log-dir DIR` takes the place of `.bibcc/`. The first run on an input moves its 0.3 files into the new layout; it never deletes them.
- **No nested `.bibcc` directories**: An input that is already inside a `.bibcc/` directory gets `reports/NAME/` next to it. Before, a scratch file in `.bibcc/` got a `.bibcc/.bibcc/` directory.
- **No stale reports**: A check or a dry run that finds nothing removes its old report, and `format --check` writes no files.
- The hint to merge a missing-venues file names `--scope project` when the input has a project venue library.
- `librarian missing` exits with status 1 when some PDFs are missing, and with status 2 when a `.bib` path or the library doesn't exist.

### Fixed

- Suggested keys keep accented surnames: `Zaj\k{a}c` gives `Zajac` instead of `Zaj`, and `{\v{S}}imon` gives `Simon` instead of an empty name.
- `add` reads the BibTeX of CVF Open Access pages that break lines with `<br>` (ICCV 2017 and other older pages).
- `add` recognizes legacy NeurIPS paper URLs (`papers.nips.cc` and `/paper/YEAR/hash/`) and reads them from `proceedings.neurips.cc`.
- OpenReview messages tell apart a paper that wasn't accepted, an accepted paper without a BibTeX export, and a request that was blocked or failed. When CrossRef doesn't find a title either, the error still includes the OpenReview message.
- `add` and `upgrade` find BibCC's comment above an empty entry or an entry built from metadata when other comment lines, such as `% TODO: switch to official bibtex`, come before it.
- Network requests are retried, with a short backoff, after dropped connections, timeouts, and SSL errors, not only after rate limits. Certificate failures aren't retried.

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

[0.9.0]: https://github.com/3hiuwoo/BibCC/compare/v0.8.0...dev
[0.8.0]: https://github.com/3hiuwoo/BibCC/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/3hiuwoo/BibCC/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/3hiuwoo/BibCC/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/3hiuwoo/BibCC/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/3hiuwoo/BibCC/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/3hiuwoo/BibCC/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/3hiuwoo/BibCC/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/3hiuwoo/BibCC/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/3hiuwoo/BibCC/compare/7632476...v0.2.0
