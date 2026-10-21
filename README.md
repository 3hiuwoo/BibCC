# BibTeX Check and Complete (BibCC)

BibCC is a command-line toolkit that fills in missing BibTeX fields, checks bibliography quality, manages a reusable venue library, and aligns your PDF library with your bibliography.

> Thanks for your interest in BibCC.
>
> BibCC started as a small tool for my own bibliography workflow, and I'm happy to see a few stars on the project. Version 0.2 reworks it into a more universal, versatile, and robust toolkit: an editable venue library, minimal verified edits, fetching new papers, upgrading preprints, and whole-file formatting. I hope it helps anyone with the same needs. Issues and suggestions are welcome.

## Quick start

BibCC requires Python 3.10 or later. Install it with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/3hiuwoo/BibCC          # the latest release
bibcc --help
```

The `main` branch always holds the latest release, and this README describes it. You can also install a specific release, or the development version from the `dev` branch:

```bash
uv tool install git+https://github.com/3hiuwoo/BibCC@v0.3.0   # a specific release (see Releases on GitHub)
uv tool install git+https://github.com/3hiuwoo/BibCC@dev      # the development version
```

If you installed without a tag, run `uv tool upgrade bibcc` to get the latest release. To move a pinned install to another release, run `uv tool install --force git+https://github.com/3hiuwoo/BibCC@vX.Y.Z`. To see what each version changed, see [`CHANGELOG.md`](CHANGELOG.md). To work on BibCC itself, see [Development](#development).

### Set up your files

BibCC reads three kinds of file that you keep: a config with your settings, a venue library that `complete` takes venue fields from (such as publisher, ISSN, location, and month), and a terms file of the words that `check quote` keeps in braces. Each kind has a user file in `~/.config/bibcc/` (or `$XDG_CONFIG_HOME/bibcc/`) for all your projects, and a project file that you commit with a bibliography. You don't need to configure anything for BibCC to find them, and it creates each file the first time a command writes to it.

Without these files, BibCC uses its built-in defaults:

| Kind | User file | Without it |
| --- | --- | --- |
| Config | `~/.config/bibcc/config.yaml` | Every setting has a built-in default. |
| Venue library | `~/.config/bibcc/venues.yaml` | No venues: BibCC doesn't ship a library, so `complete` has nothing to fill in. |
| Terms file | `~/.config/bibcc/terms.txt` | `check quote` uses only its built-in vocabulary of names. |

To start all three from a shared profile, such as the MIAA lab's `miaa`, run the following command. It copies the profile's files into your user files, and you edit your copies from then on:

```bash
bibcc config examples        # list the shared configs (a profile shares its name with one)
bibcc config profile miaa    # copy the config, venue library, and terms file into ~/.config/bibcc/
bibcc config where           # show every file that applies here, and the settings they give
```

To set up only one project instead, pass `--scope project`. For details, see [Config files](#config), [Venue library](#venue-library), and [Protected terms](#protected-terms).

To keep a user file somewhere else, for example in a synced directory, set `BIBCC_CONFIG`, `BIBCC_VENUES`, or `BIBCC_TERMS` to its path. Set the variable for every shell that runs BibCC, because a command run without it reads and writes the file in `~/.config/bibcc/` instead.

### Network access

`add` and `upgrade` locate papers through CrossRef, arXiv, OpenReview, and Semantic Scholar, and then download official BibTeX from publisher and proceedings sites: IEEE Xplore, Springer, PMLR, NeurIPS, ICLR, ACL Anthology, IJCAI, OpenReview, and arXiv. `scholar titles` and `complete --online` also go online. The other commands work offline.

## Commands

BibCC provides the following commands through a single entry point, `bibcc`:

| Command | Description |
| --- | --- |
| [`check`](#check) | Run quality checks: missing fields, title case, term protection, citation keys, field typos, and duplicates |
| [`complete`](#complete) | Fill in missing BibTeX fields from the venue library, and report conflicts |
| [`add`](#add) | Download the official BibTeX of new papers (by DOI, arXiv ID, paper URL, or title) into a staging `.bib` file |
| [`upgrade`](#upgrade) | Replace preprints and interim entries with the official BibTeX of their published versions, keeping the keys |
| [`format`](#format) | Reformat `.bib` files consistently: aligned fields, braced values, month macros, and `--` page ranges |
| [`librarian`](#librarian) | Compare a PDF library with `.bib` files: find missing and extra PDFs, and rename PDFs to citation keys |
| [`scholar`](#scholar) | Fill in citation counts and verify titles against online sources |
| [`compose`](#compose) | Merge the `.bib` files of a directory tree into a single bibliography |
| `venues` | Manage your user and project venue libraries: `where`, `init`, `import`, `examples`, and `providers` |
| [`terms`](#protected-terms) | Manage your user and project protected-terms files, which `check quote` reads: `where`, `list`, `add`, `import`, and `examples` |
| [`config`](#config) | Manage your user and project config files, which hold the `format` settings: `where`, `init`, `import`, `profile`, and `examples` |
| `surface` | Print the machine-readable command surface as JSON, for tools and skills that track BibCC |

For command-specific help, run `bibcc COMMAND -h`. To see the installed version, run `bibcc --version`.

### Typical workflow

```bash
# 1. Fetch new papers into added.bib, then move the entries into your topic files.
#    (Official BibTeX only; add --fallback all to build the rest from metadata.)
bibcc add 2501.13198 "Some Paper Title" --against bib/
# 2. Fill in venue fields from the library.
bibcc complete bib/topic.bib --in-place
# 3. Check titles, braces, keys, field typos, and duplicates, one check at a time.
bibcc check title bib/topic.bib
bibcc check quote bib/topic.bib
bibcc check keys bib/topic.bib
bibcc check fields bib/topic.bib --against bib/
bibcc check official bib/topic.bib --learn
bibcc check editions bib/topic.bib
# 4. Now and then, see which preprints have been published, and then replace them.
bibcc upgrade --report-only bib/
bibcc upgrade bib/topic.bib --in-place
# 5. Give all files a consistent layout.
bibcc format bib/ --in-place
# 6. Merge everything into one file for LaTeX.
bibcc compose compose bib/ references.bib
```

`complete`, `upgrade`, and `format` do a dry run unless you pass `--output` or `--in-place`. A dry run writes a diff to `.bibcc/` so that you can review the changes first. `add` only appends to its staging file and fills in its empty entries (`--dry-run` prints the entries instead), and `librarian rename` takes `--dry-run` to preview the renames.

Don't expect `add` to get official BibTeX for every paper. AAAI, ACM, and Elsevier block automated downloads, and IEEE Xplore and Springer sometimes rate-limit or bot-check requests. By default, those papers get an empty entry or are listed as failed, and the end of the run lists what's left to do by hand. To finish them, add BibTeX that you downloaded yourself (`bibcc add FILE.bib`) or look them up again later (`bibcc add --retry`). If you don't need official BibTeX, pass `--fallback all`. For details, see [Entries built from metadata](#fallback-entries-built-from-metadata).

---

### Check quality with `check` <a id="check"></a>

`check` runs one quality check on a `.bib` file. Each check is a subcommand, and a run does only the check that you name:

| Check | What it reports |
| --- | --- |
| `missing` | Entries that lack required fields (default: `month`) |
| `title` | Titles that aren't in Title Case |
| `quote` | Words that need `{braces}`, and compounds braced as a whole |
| `keys` | Keys that don't follow `METHOD_AUTHOR_VENUEYEAR` |
| `fields` | Unknown field names, malformed values, and duplicates |
| `editions` | Fields of the venue's schema that the entry lacks |
| `official` | Differences from the official BibTeX, downloaded again |
| `venues` | Venue library records with missing or inconsistent fields |

To see the options of a check, run `bibcc check CHECK -h`. To run several checks, run `check` once for each.

Empty entries (the placeholders that `add` writes for papers without official BibTeX) have no fields, so the checks skip them. `check` lists them at the start of each run.

#### Missing fields

Find entries that lack required fields. By default, `missing` checks `month`:

```bash
bibcc check missing input.bib
bibcc check missing input.bib --fields month,publisher --entry-types inproceedings,article
```

Some entries have no month on purpose: a conference held across two months, or a journal without monthly issues. When an entry's venue library record has `month: none`, `missing` doesn't report the entry's missing month, and lists it instead. For details, see [Months](#months).

Some venues never export a field: NeurIPS BibTeX has no `doi`, for example. When the venue library has a [schema](#venue-schemas) for an entry's venue, `missing` doesn't report a per-paper field that the schema leaves out, and lists the entry instead.

#### Title case

Suggest APA-style title case corrections:

```bash
bibcc check title input.bib
bibcc check title input.bib --apply          # apply the changes in place
bibcc check title input.bib --interactive    # review each suggestion
```

#### Term protection

Suggest `{braces}` for technical terms, acronyms, and proper nouns:

```bash
bibcc check quote input.bib
bibcc check quote input.bib --terms Gaussian,BERT
bibcc check quote input.bib --vocab-file my_terms.txt
bibcc check quote input.bib --apply --terms LoRA,CLIP    # brace these terms, then report the rest
bibcc check quote input.bib --interactive                # review each compound split
bibcc check quote input.bib --interactive --scope project   # and share the compounds you keep
```

Besides `--terms` and `--vocab-file`, `quote` always reads your [protected terms](#protected-terms): the user terms file and the project's `.bibcc-terms.txt`.

`quote` also reports hyphenated or slashed compounds that are braced as a whole when only some parts need braces. `{CLIP-Based}` should be `{CLIP}-Based`, so that styles can still lowercase "Based". A compound stays whole in the following cases:

- Every part needs braces, as in method names such as `{SD-LoRA}`, `{R-CNN}`, and `{GPT-4}`.
- No part needs braces, as in `{Navier-Stokes}`.
- The compound itself is in the vocabulary. A listed part doesn't keep the compound whole: `{CLIP-Based}` still becomes `{CLIP}-Based` when the vocabulary lists `CLIP`. To keep a method name such as `{CIP-Net}` or `{Transformer-XL}` whole, add the compound to your terms (`bibcc terms add CIP-Net`), or list it with `--terms` or `--vocab-file`.

`--apply` wraps your terms (the terms files, `--terms`, and `--vocab-file`) in braces wherever they appear in a title with the same case, splits the over-braced compounds, and then reports what else might need braces. It changes only the title values, and never applies the built-in vocabulary or the other suggestions, because those need review.

To review each over-braced compound one at a time, pass `--interactive`: split it, skip it, edit the suggestion, or keep it whole. Keeping a compound whole also adds it to the user terms file, or with `--scope project` to the project's `.bibcc-terms.txt`, so a method name such as `CIP-Net` stays in one brace group for good, in every file. `quote` still reads `.bibcc/INPUT/vocab.txt`, where earlier releases kept these compounds.

#### Citation keys

Check that keys follow the `METHOD_AUTHOR_VENUEYEAR` convention, and that the AUTHOR, VENUE, and YEAR parts match the entry:

```bash
bibcc check keys input.bib
```

AUTHOR must be the first author's surname, or part of a compound surname (`Ven` or `vandeVen` for `van de Ven`), with accents removed (`Zajac` for `Zaj\k{a}c`).

The year in a key is the year of the event. It can differ from the entry's `year` in these cases:

- The venue name includes the event year (`Computer Vision -- ECCV 2024`, published in 2025).
- An `@inproceedings` entry was published the year after the event.
- A preprint is keyed by the venue that accepted it (`..._AAAI2026` for a 2025 arXiv paper).

#### Field names, values, and duplicates

Find mistakes that BibTeX ignores silently:

```bash
bibcc check fields input.bib
bibcc check fields input.bib --against bib/          # also look for duplicates in other files
bibcc check fields input.bib --known-fields code,pdf  # accept extra field names
bibcc check fields input.bib --apply                 # remove interim and empty fields, then report the rest
```

`fields` reports the following:

- **Unknown fields**: names that aren't standard BibTeX or biblatex fields or commonly exported ones (such as `abstract`, `keywords`, and `numpages`). These are usually typos, which BibTeX drops without a warning. `check` suggests a likely correction: `'volumn' → did you mean 'volume'?`.
- **Values**: empty values, years that aren't four digits, single-hyphen page ranges (`12-15` → `12--15`), DOIs that are malformed or written as URLs, months that aren't macros (`{June}` → `jun`), malformed ISSNs, and URLs without `http://` or `https://`.
- **Interim fields** (`interim_field`): fields that only an interim or preprint version of a paper has, left in an entry whose BibTeX now comes from somewhere else. The check looks for CVF Open Access, OpenReview, and arXiv URLs, the arXiv fields (`eprint`, `archiveprefix`, and `primaryclass`), and arXiv notes. For example, IEEE Xplore BibTeX for a CVPR paper has no `url`, so a CVF Open Access `url` in it is left over from the CVF entry. A CVF URL is expected only in an entry with the CVF booktitle, and an OpenReview URL only with an OpenReview booktitle (ICLR before 2024 included) or in a journal published there, such as TMLR. arXiv fields are expected only in preprint entries (`@misc`, or a journal such as `arXiv preprint` or `CoRR`).
- **Conference articles** (`conference_article`): `@article` entries whose `journal` names conference proceedings, as in the BibTeX that AAAI exports (`Proceedings of the AAAI Conference on Artificial Intelligence`). Journals such as `Proceedings of the IEEE` name no event, so they aren't reported. To make these entries `@inproceedings`, with the name as their `booktitle`, run `bibcc complete`.
- **Duplicates**: the same paper (same DOI, arXiv ID, or title) or the same citation key twice, in the file or in the `--against` files. Conference and journal versions sometimes share a title, so check before you delete one.

`bibcc format` fixes page ranges and months automatically. To remove the interim fields and the fields with empty values, pass `--apply`: the check removes them and then reports what's left. `check` only reports the other issues.

#### Fields of the venue's schema <a id="check-editions"></a>

The official BibTeX of a venue has the same per-paper fields for every paper: PMLR gives every ICML paper `pages`, `pdf`, and `url`, for example. The venue library keeps these fields as the venue's [schema](#venue-schemas) (`entry_fields`). `editions` checks each entry against its venue's schema, and reports the fields that the entry lacks:

```bash
bibcc check editions input.bib
bibcc check editions input.bib --against bib/                  # propose schemas from the entries in bib/ too
bibcc check editions input.bib --against bib/ --learn          # write the proposals, and check against them
bibcc check editions input.bib --include-fields urldate         # also compare a field ignored by default
```

The report, `.bibcc/INPUT/edition_fields.txt`, gives each finding one of these issue types:

| Issue type | Meaning |
| --- | --- |
| `missing` | The entry lacks a field of its venue's schema. The evidence column names the schema (a journal, a family of conference editions, or one edition) and where it was learned from. |
| `default_missing` | The entry's venue has no schema, and the entry lacks a field of its publisher's default schema. The evidence column names the default and the venues it comes from. |

A journal article not yet in an issue (no `volume`) isn't expected to have a `volume`, `number`, or `pages`.

A publisher's *default schema* is the list of fields that most of the library's schemas of the same publisher and kind (journal or proceedings) share, such as the `doi`, `pages`, and `volume` of Elsevier journals. It needs the schemas of at least two venues. The check finds an entry's publisher from its venue record, the entry's own `publisher` field, the venue name, or the DOI prefix. A default is a guess for a venue that has no schema yet: it never replaces a venue's own schema, `--learn` never writes it, and `--strict` doesn't count it.

The best schemas come from official BibTeX: run `bibcc check official input.bib --learn` (see [Differences from the official BibTeX](#differences-from-the-official-bibtex)). For a venue without a schema, such as an AAAI or ACM venue whose BibTeX BibCC can't download, `editions` compares the entries of the venue, in the input file and in the `--against` files, and proposes the fields that most of them share. The proposals go to `.bibcc/INPUT/edition_schemas.txt` (issue type `schema_lacks`), with the entries that lack a proposed field. The check never reports an entry from that comparison alone, because the entries can share a lost field. To write the proposals into the venue library and check the entries against them in the same run, pass `--learn` (with `--scope project` for the project library). A proposal needs at least three entries of a journal, or of one conference year. A proposal for a journal or an edition that the library has no record of goes into `.bibcc/INPUT/missing_venues.yaml`, with the record (see [Schemas of venues without a record](#schemas-of-venues-without-a-record)).

The check ignores the following fields:

- Fields that every compared entry has: `title`, `author`, `year`, `booktitle`, and `journal`.
- BibCC's own `citation` field, which `bibcc scholar cite` writes.
- Exporter and reference-manager bookkeeping: `annote`, `bibsource`, `biburl`, `copyright`, `mendeley-groups`, `timestamp`, and `urldate`.

A schema also leaves out the fields that the venue library supplies, such as `publisher` and a conference's `month`: `bibcc complete` adds those, and `bibcc check venues` checks them. To ignore more fields, pass `--ignore-fields`. To compare one of the ignored fields anyway, pass `--include-fields`. The check also leaves out entries with an interim (CVF or OpenReview) booktitle, entries built from metadata, and empty entries, because they lack fields by design. With `--strict`, only `missing` findings count; `default_missing` findings and proposals don't.

#### Differences from the official BibTeX

Entries drift from their official BibTeX: someone deletes a field by hand, or the entry came from Google Scholar or a colleague. `official` downloads the official BibTeX of each entry again, the same way `add` does, and compares it with the entry field by field:

```bash
bibcc check official input.bib
bibcc check official input.bib --apply day,series        # add the official values of these fields
bibcc check official input.bib --apply all               # add every field that only the official BibTeX has
bibcc check official input.bib --local exports/          # use BibTeX that you downloaded yourself
bibcc check official input.bib --local exports/ --offline  # download nothing
```

The check needs network access. The report, `.bibcc/INPUT/official_fields.txt`, gives each finding one of these issue types:

| Issue type | Meaning |
| --- | --- |
| `upstream_only` | The official BibTeX has a field that the entry lacks. |
| `differs` | Both have the field, with different values. Braces, case, whitespace, accents, month spellings, and the form of a name (`First Last` or `Last, First`) don't count. |
| `local_only` | The entry has a field that the official BibTeX lacks, other than `citation` and the fields that the venue library supplies. |
| `type` | The entry types differ. |

`.bibcc/INPUT/official_venues.txt` summarizes the findings for each venue and year, with one of these issue types:

| Issue type | Meaning |
| --- | --- |
| `entries_lack` | The official BibTeX has a field that some checked entries lack. |
| `export_lacks` | Every checked entry (at least two) has a field that no official BibTeX has. The field comes from elsewhere, such as the book that the proceedings appeared in. |
| `library_lacks` | The venue library record lacks a value that the official BibTeX of every checked entry agrees on. |
| `library_differs` | The venue library record has a different value. |
| `books_lack` | The entries of one book of a proceedings agree on a `volume` or `part` that the record's `books` table lacks (see [Proceedings in several books](#proceedings-in-several-books)). |
| `schema_lacks` | The venue library has no [schema](#venue-schemas) for the venue. |
| `schema_differs` | The venue's schema differs from the fields that the downloaded BibTeX has. |

To write the schemas and the book fields into the venue library, pass `--learn` (with `--scope project` for the project library); `check editions` then checks every entry of the venue against the schemas.

<a id="schemas-of-venues-without-a-record"></a>**Schemas of venues without a record.** A journal schema belongs to the journal's record, and a schema for one edition belongs to the edition's record. When the library has no such record, `--learn` writes the record, with its schema (`entry_fields` and `learned_from`), into `.bibcc/INPUT/missing_venues.yaml`. The record's fields come pre-filled from the official BibTeX (`# from official BibTeX`), or from the entries for `check editions` (`# from bib`). A record that an earlier `complete` run already proposed there gets the schema added. After you fill in the rest, one `bibcc complete INPUT --in-place --update-venues` adds the record and its schema.

```bash
bibcc check official input.bib --learn                   # learn the venue schemas from the official BibTeX
bibcc check official input.bib --refresh                 # download everything again instead of reading the cache
```

BibCC keeps each paper's downloaded BibTeX for 30 days in a cache, so a second run of `add`, `upgrade`, or `check official` on the same paper reads it from there. To download everything again, pass `--refresh`. The cache directory is `$BIBCC_CACHE`, or else `$XDG_CACHE_HOME/bibcc` (`~/.cache/bibcc`); to turn the cache off, set `BIBCC_CACHE=off`.

To add official values, pass `--apply` with the fields to add, or `all` for every `upstream_only` field. `--apply` only adds fields that an entry lacks; it never changes an existing value.

For AAAI, ACM, and Elsevier papers, which BibCC can't download, get the official BibTeX yourself, save it in a directory, and pass the directory with `--local`. An entry matches a local entry by citation key, file name, DOI, or title. With `--offline`, the check compares only the entries that match the local files.

The check skips preprints, interim (CVF or OpenReview) entries, and entries built from metadata, because `bibcc upgrade` replaces them. `.bibcc/INPUT/official_unchecked.txt` lists the entries that the check couldn't compare, with a [`next`](#next-steps) value. For a `by hand` entry, save its BibTeX in the `--local` directory and run the check again. A `mismatch` entry has official BibTeX with a different title, so its DOI or the matched paper is probably wrong. With `--strict`, `local_only` findings don't count.

#### Venue library completeness

Check the venue library for records with missing fields:

```bash
bibcc check venues
bibcc check venues --journal-fields publisher,issn --proceedings-fields venue,month,isbn
bibcc check venues --scope project --apply    # move shared values into family records
```

Besides the required-field check, `venues` compares the editions of each conference with one another, and reports fields that one edition defines and another lacks. When every edition that has a field agrees on its value, the report suggests that value for the editions that lack it, or suggests moving it into a [family record](#venue-families) when every published edition has the same value. Editions are grouped by their family record, or else by their name without the year and ordinal. The check also lists the family records, with their editions and whether they have a schema. A record still named by its interim (CVF or OpenReview) booktitle describes proceedings that aren't out yet, so only its event fields (`venue` and `month`) count as missing.

To move those shared values, pass `--apply`. For each conference, the check creates the family record if it's missing (with the acronym of the [provider table](#venue-families) when the table knows the conference), adds the shared values to it, and removes them from the editions. An edition keeps a value that differs only in braces or case, and a record still named by its interim booktitle keeps its values, because it gets no family fields. So no edition's fields change. `--apply` saves each library that the check reads; to check and rewrite only one, pass `--scope user` or `--scope project`.

To check only the records you're about to merge, point `--venues` at the fill-in file instead of a whole library:

```bash
bibcc check venues --venues .bibcc/input.bib/missing_venues.yaml
```

#### Use `check` in scripts

By default, `check` exits with status 0 whenever the check runs. To exit with status 1 when the check finds something or the file has empty entries, pass `--strict` (every check except `venues` accepts it):

```bash
bibcc check keys input.bib --strict && bibcc check fields input.bib --strict
```

<details>
<summary>All <code>check</code> options</summary>

| Check | Option | Description |
| --- | --- | --- |
| All except `venues` | `--strict` | Exit with status 1 if the check finds something or the file has empty entries |
| `missing` | `--fields FIELDS` | Comma-separated required fields (default: `month`) |
| `missing` | `--entry-types TYPES` | Comma-separated entry types to check (default: `inproceedings,article,proceedings,conference`) |
| `missing` | `--venues FILE` | Use this venue library file instead of the user and project libraries, to find the venues without a month |
| `title` | `--apply` | Apply the title case changes in place |
| `title` | `--interactive` | Review each suggestion interactively, and write the accepted ones |
| `title` | `--style STYLE` | Title case style (default: `apa`) |
| `title` | `--extra-stopwords WORDS` | Additional stopwords to keep lowercase |
| `quote` | `--apply` | Wrap your terms (the terms files, `--terms`, and `--vocab-file`) in braces in the titles, split over-braced compounds, then report the rest |
| `quote` | `--interactive` | Review each over-braced compound: split, skip, edit, or keep whole and remember it in the terms file |
| `quote` | `--scope SCOPE` | Terms file that `--interactive` adds the compounds you keep to: `user` (default) or `project` |
| `quote` | `--terms TERMS` | Extra terms to protect |
| `quote` | `--vocab-file FILE` | Vocabulary file with one term per line; blank lines and `#` comments are ignored (the terms files and `.bibcc/INPUT/vocab.txt` are always read) |
| `quote` | `--no-default` | Turn off the built-in vocabulary of names |
| `quote` | `--min-length N` | Minimum length for mixed-case, acronym, and number-bearing terms (default: `2`) |
| `fields` | `--apply` | Remove the interim fields and the empty fields from the input file, then report the rest |
| `fields` | `--known-fields FIELDS` | Extra field names to accept |
| `fields` | `--against PATH` | Also look for duplicates in this `.bib` file or directory; repeatable |
| `editions` | `--against PATH` | Also compare with the entries in this `.bib` file or directory when proposing schemas; repeatable |
| `editions` | `--ignore-fields FIELDS` | Fields to ignore, in addition to the default ones |
| `editions` | `--include-fields FIELDS` | Fields to compare even though the check ignores them by default (for example, `urldate`) |
| `editions` | `--learn` | Write the proposed schemas into the venue library, and check the entries against them; a schema without its record goes into `missing_venues.yaml` |
| `editions` | `--scope SCOPE` | With `--learn`, the library to write to: `user` (default) or `project` |
| `editions` | `--venues FILE` | Use this venue library file instead of the user and project libraries |
| `official` | `--apply FIELDS` | Add the official values of these fields to the entries that lack them (`all`: every `upstream_only` field) |
| `official` | `--ids KEYS` | Check only these citation keys |
| `official` | `--local PATH` | A `.bib` file or directory of official BibTeX that you got yourself; repeatable |
| `official` | `--offline` | Download nothing; compare only the entries that match the `--local` files |
| `official` | `--ignore-fields FIELDS` | Fields not to compare |
| `official` | `--delay SECONDS` | Seconds to wait between downloads (default: `1`) |
| `official` | `--refresh` | Download every official BibTeX again instead of reading the cache |
| `official` | `--learn` | Write the venue schemas of the official BibTeX and the book fields into the venue library; a schema without its record goes into `missing_venues.yaml` |
| `official` | `--scope SCOPE` | With `--learn`, the library to write to: `user` (default) or `project` |
| `official` | `--venues FILE` | Use this venue library file instead of the user and project libraries |
| `venues` | `PATH` | Look for the project library from this file or directory (default: the current directory) |
| `venues` | `--venues FILE` | Check only this venue library file (a `missing_venues.yaml` fill-in file works too) |
| `venues` | `--journal-fields FIELDS` | Fields to check in journal records (default: `publisher,issn`) |
| `venues` | `--proceedings-fields FIELDS` | Fields to check in proceedings records (default: `venue,publisher,month`) |
| `venues` | `--scope SCOPE` | Check only this library: `user` or `project` (default: both) |
| `venues` | `--apply` | Move the values that every edition of a conference shares into its family record, and save each library that the check reads |

</details>

---

### Fill in missing fields with `complete` <a id="complete"></a>

`complete` fills in missing BibTeX fields, such as publisher, ISSN, venue, and month, from the [venue library](#venue-library). The library is the only source of added fields. By default, `complete` never overwrites an existing field: it reports differences as conflicts in every mode, including dry runs, and saves them to `.bibcc/INPUT/conflicts.txt`.

```bash
bibcc complete input.bib                    # preview the changes as a diff (dry run)
bibcc complete input.bib --output out.bib   # write the completed file to out.bib
bibcc complete input.bib --in-place         # write back to input.bib
```

Edits are minimal and verified:

- `complete` inserts new fields before each entry's closing brace, using the entry's own indentation and `=` alignment. Nothing else in the file changes: comments, field order, LaTeX, and line endings stay as they are.
- There's one exception: when a new field name is longer than an entry's aligned `=` column, `complete` widens that entry's column so that its fields stay aligned.
- Months are written as macros (`month = jun`), which matches what `add` and `format` produce.
- Before writing, `complete` parses the result again and checks that it contains the same entries, with only the intended fields changed. If that check fails, nothing is written.

`check title --apply`, `check title --interactive`, `check quote --apply`, `check quote --interactive`, and `scholar cite` use the same safe editing.

**Resolve conflicts.** When you fix a wrong value in a library record, the entries that already got the old value show up as conflicts on the next run. To overwrite them with the corrected library values, pass `--resolve library`. To limit what the command may add or overwrite, narrow it with `--fields` (only these fields) and `--ids` (only these entries); the reports still cover the whole file, and the conflicts that stay out of scope are listed as left unchanged. Run without `--output` or `--in-place` first to review the overwrites as a diff.

```bash
# After fixing the publisher of a venue in the library, update the entries it patched before.
bibcc complete input.bib --resolve library --fields publisher              # preview
bibcc complete input.bib --in-place --resolve library --fields publisher   # write
```

**Conference papers exported as `@article`.** AAAI exports its papers as `@article`, with the proceedings name as the `journal`. `complete` changes such entries to `@inproceedings`, renames `journal` to `booktitle`, and lists them in the log. It keeps every other field, including the month that the export gives. `--ids` limits the change to the entries you name.

**Venues without a month.** A library record with `month: none` never adds a month. When an entry of that venue has a month, `complete` reports it as a conflict, and `--resolve library` removes the entry's `month` and `day`. For details, see [Months](#months).

**Interim booktitles.** Some entries cite a conference by its CVF Open Access or OpenReview booktitle, for example `Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)` for a paper that's now in IEEE Xplore. Such an entry matches the library record of the published proceedings, but only gets the fields that describe the event (`venue` and `month`). `complete` lists it as an interim entry so that `bibcc upgrade` can replace it with the official BibTeX.

**Missing venues.** When venues are missing from the library, `complete` generates a `.bibcc/INPUT/missing_venues.yaml` file. It pre-fills fields from these sources, so you only fill in what it couldn't infer:

- Existing entries in the same journal or conference (marked `# from bib (KEY)`: the comment names the entries each value comes from, and the log lists them too).
- The previous edition of the same conference (for example, CVPR 2025 → CVPR 2026: publisher, ISSN, series, and address). The month isn't copied, because an edition can move to another month or run across two.
- Guesses of the publisher from the venue name.

Each record's `# entries:` comment names the entries that cite the venue; the log and `missing_venues.txt` list them too.

`complete` merges this file on every run instead of overwriting it: what you filled in is kept, new venues are appended, and venues that the library now covers are dropped.

**Online check (`--online`, off by default).** `complete` asks CrossRef about every entry with a DOI, and does the following:

- Pre-fills more of the missing-venues YAML file (marked `# from CrossRef`: publisher, ISSN, ISBN, location, and month). CrossRef gives the month only when the event starts and ends in the same month.
- Compares each entry, and its library record, with CrossRef (venue name, year, volume, number, pages, DOI, publisher, ISSN, ISBN, location, and month), and writes the differences to `.bibcc/INPUT/venue_check.txt`. The report says whether the entry, the library, or both differ. Entries without a DOI are listed as not checked.
- When every checked paper of a venue agrees on a value that differs from the library, suggests a correction, commented out, at the end of the YAML file.

Fields still come only from the library: CrossRef values reach your entries only after you review and merge them.

#### Workflow

To generate the YAML file, update the library, and complete the entries, do the following:

```bash
# 1. Generate the YAML file (pre-filled where possible).
bibcc complete input.bib

# 2. Fill in the remaining fields in .bibcc/input.bib/missing_venues.yaml.

# Optional: check only the filled-in records before you merge them.
bibcc check venues --venues .bibcc/input.bib/missing_venues.yaml

# 3. Merge the file into your user library and complete the entries in one step...
bibcc complete input.bib --output out.bib --update-venues
#    ...or merge it into the project's .bibcc-venues.yaml instead.
bibcc complete input.bib --output out.bib --update-venues --scope project
#    ...or only update the library, and complete the entries later.
bibcc complete input.bib --update-venues-only

# Optional: let CrossRef pre-fill the YAML file and check the entries and the library.
bibcc complete input.bib --online
```

The log names the library file that `--update-venues` and `--update-venues-only` write to.

<details>
<summary>All <code>complete</code> options</summary>

| Option | Description |
| --- | --- |
| `--output FILE` | Path to save the completed `.bib` file to (omit for a dry run) |
| `--in-place` | Write the completed entries back to the input file |
| `--log-dir DIR` | Directory for logs and reports (default: `.bibcc/` next to the input) |
| `--venues FILE` | Use only this venue library file (default: the user library merged with the project's `.bibcc-venues.yaml`) |
| `--update-venues` | Merge the filled-in `*.missing_venues.yaml` file into the library before completing (`--update-templates` still works) |
| `--update-venues-only` | Merge the filled-in `*.missing_venues.yaml` file into the library, and stop without completing the `.bib` file |
| `--resolve MODE` | `keep` (default) reports fields that differ from the library; `library` overwrites them with the library's values |
| `--fields FIELDS` | Fields the command may add or overwrite (default: every field of the venue record); the reports still cover all fields |
| `--ids KEYS` | Citation keys to complete (default: all entries); the reports still cover the whole file |
| `--scope user\|project` | Library that `--update-venues` and `--update-venues-only` write to: `user` (default) or `project` (the nearest `.bibcc-venues.yaml`) |
| `--online` | Also query CrossRef: pre-fill the YAML file, and check entries with a DOI and their library records (report only) |
| `--delay SECONDS` | With `--online`, seconds to wait between CrossRef requests (default: `1`) |

</details>

---

### Add new papers with `add` <a id="add"></a>

`add` downloads the official BibTeX of papers that you identify by DOI, arXiv ID or URL, paper page URL, or title, and appends it to a staging file (`added.bib` by default). Review the entries there, and then move them into your topic files. Not every paper has official BibTeX that can be downloaded; `--fallback` builds those entries from metadata instead. For details, see [When there's no official BibTeX](#when-there-is-no-official-bibtex).

```bash
bibcc add 10.1109/TPAMI.2024.3429383 2501.13198 --against bib/
bibcc add "SD-LoRA: Scalable Decoupled Low-Rank Adaptation for Class Incremental Learning" --against bib/
bibcc add https://proceedings.mlr.press/v235/abad-rocamora24a.html   # a paper page
bibcc add --from new_papers.txt --against bib/ --output added.bib   # one identifier per line
bibcc add --from papers.csv --against bib/ --output added.bib       # a manifest that sets the keys
bibcc add downloads/ --output added.bib                             # BibTeX that you downloaded yourself
bibcc add --retry --output added.bib                                # look up empty entries and failures again
bibcc add --from new_papers.txt --fallback all                      # metadata when there's no official BibTeX
bibcc add 2501.13198 --dry-run                                        # print only
```

For each paper, `add` does the following:

1. **Locates the paper.** DOIs come from CrossRef, arXiv IDs from the arXiv API, and titles are matched through Semantic Scholar, then OpenReview, CrossRef, and arXiv. A title only counts as found when it matches exactly (ignoring case and punctuation). Paper page URLs (IEEE Xplore, CVF Open Access, PMLR, NeurIPS, ICLR, ACL Anthology, and IJCAI) go straight to that page's BibTeX.
1. **Prefers the published version.** For an arXiv paper, `add` looks for a published version: the DOI linked from arXiv or known to Semantic Scholar, an accepted OpenReview paper (such as ICLR, NeurIPS, or ICML; "Submitted to" and withdrawn papers are ignored), the DBLP key that Semantic Scholar reports (for example, `conf/iclr/...25` → ICLR 2025), or a CrossRef record with the same title. To keep the arXiv entry, pass `--preprint`.
1. **Skips duplicates.** `add` reports and skips papers that are already in the `--against` files or directories (same DOI, arXiv ID, or title) or in the staging file. An empty entry in an `--against` file counts as present. A paper that matches an empty entry of the staging file fills that entry in place instead, as described in [Fill in empty entries](#fill-in-empty-entries). `add` also flags a published paper whose preprint is already in your bibliography.
1. **Downloads the official BibTeX** from the publisher or proceedings site, as listed in [Where the official BibTeX comes from](#official-sources). The metadata APIs only locate the paper; the entry itself is what the publisher offers. This step often fails for some papers. For what happens then, see [When there's no official BibTeX](#when-there-is-no-official-bibtex).
1. **Keeps the official values**, including the month and day that a journal export gives (Springer gives the date the paper went online). Two exceptions are reported for each entry:
   - A month that gives a period across two months, such as PMLR's `29 Jul--01 Aug`, is dropped, with its `day`, and the library's month isn't added either. For details, see [Months](#months).
   - Conference proceedings exported as `@article` (AAAI) become `@inproceedings`, with the `journal` value as the `booktitle`.
1. **Formats the entry like the rest of the bibliography**: APA title case, braces around acronyms and technical terms (`{SD-LoRA}`), `--` page ranges, month macros (`month = jun`), escaped `&`, `%`, and `_`, and aligned `=`. It keeps every field of the official BibTeX, including `abstract`, `keywords`, and empty fields.
1. **Completes venue fields from the venue library**, like `complete`: it adds the fields that the official BibTeX lacks (such as `venue` and `issn`), and reports different values instead of overwriting them. It proposes venues that are missing from the library in `.bibcc/OUTPUT/missing_venues.yaml`, pre-filled from the official BibTeX, the previous edition, and CrossRef.
1. **Suggests a key** of the form `METHOD_AUTHOR_VENUEYEAR`. METHOD is the title's `Name:` prefix, or else its first two content words, so check it. AUTHOR is the first author's surname in ASCII (`Zaj\k{a}c` becomes `Zajac`). To set the parts of the key yourself, use a [manifest](#manifests).

#### Where the official BibTeX comes from <a id="official-sources"></a>

`add` uses the first source in the following table that matches the paper:

| Paper | Official BibTeX |
| --- | --- |
| CVPR, ICCV, WACV, and their workshops; IEEE journals (DOI `10.1109`) | IEEE Xplore citation export |
| ECCV; Springer and Nature journals (DOI `10.1007`, `10.1038`) | Springer citation export |
| ICML, CoLLAs, and other PMLR venues | PMLR paper page |
| NeurIPS | NeurIPS proceedings (`proceedings.neurips.cc`) |
| ICLR from 2024 | ICLR proceedings (`proceedings.iclr.cc`) |
| ICLR up to 2023 | OpenReview (its only proceedings) |
| ACL Anthology venues (DOI `10.18653`), IJCAI (DOI `10.24963`) | ACL Anthology, IJCAI |
| arXiv preprints | `arxiv.org/bibtex/ARXIV_ID` |
| AAAI, ACM, Elsevier (DOI `10.1609`, `10.1145`, `10.1016`) | None: they block automated downloads |

**Interim BibTeX.** Papers whose proceedings aren't out yet get the BibTeX of the site that they appear on first: CVF Open Access for CVPR, ICCV, and WACV papers that aren't in IEEE Xplore yet, and OpenReview for NeurIPS, ICLR, and ICML papers that aren't in the proceedings yet. A note says so, and `bibcc upgrade` replaces these entries once the proceedings are out.

#### When there's no official BibTeX <a id="when-there-is-no-official-bibtex"></a>

Expect this for a fair share of the papers in a typical survey. There are two cases:

- **None to download**: AAAI, ACM, and Elsevier block automated downloads, ECCV papers aren't on SpringerLink for a while, and some publishers have no known BibTeX export.
- **Site unreachable**: IEEE Xplore, Springer, CrossRef, and Semantic Scholar rate-limit requests, bot-check them, or time out now and then. Retrying later usually works.

What `add` does in each case depends on `--fallback`:

| `--fallback` | None to download | Site unreachable |
| --- | --- | --- |
| `none` (default) | Empty entry to fill in by hand | Nothing written; listed as failed (exit status 1) |
| `missing` | Entry built from metadata | Nothing written; listed as failed (exit status 1) |
| `all` | Entry built from metadata | Entry built from metadata |

A paper that can't be located at all (an unknown DOI, or no exact title match) is always listed as failed, because there's no metadata to build an entry from.

**Empty entries.** With `--fallback none`, `add` writes an empty entry under the suggested key, with a comment that says what it is and where to get the BibTeX by hand:

```bibtex
% BibCC: no official BibTeX could be downloaded; paste it into the entry below, keeping the key.
%   title:  Learning Visual Abstract Reasoning through Dual-Stream Networks
%   venue:  Proceedings of the AAAI Conference on Artificial Intelligence (2024)
%   doi:    10.1609/aaai.v38i15.29641
%   reason: AAAI blocks automated BibTeX downloads
%   get it: https://doi.org/10.1609/aaai.v38i15.29641
@inproceedings{LearningVisual_Zhao_AAAI2024,
}
```

**Unreachable sites.** When a site can't be reached (because of a network error, a rate limit, or bot protection) and `--fallback` isn't `all`, `add` writes nothing for that paper and lists it as failed. To add it, run `add` again later.

#### Entries built from metadata <a id="fallback-entries-built-from-metadata"></a>

With `--fallback missing` or `--fallback all`, `add` builds the entry from the record that it located the paper by. For DOIs, that's CrossRef (title, authors, journal or booktitle, year, month, volume, number, pages, publisher, and DOI); otherwise it's Semantic Scholar, OpenReview, or arXiv. The entry is formatted like an official one and completed from the venue library. The library is trusted over the metadata, so its venue name and fields replace the metadata's, and the log lists each replacement. A comment above the entry marks it:

```bibtex
% BibCC: not the official BibTeX; it was built from metadata. `bibcc upgrade` replaces it once the official BibTeX can be downloaded.
%   source: CrossRef
%   reason: AAAI blocks automated BibTeX downloads
%   get it: https://doi.org/10.1609/aaai.v39i1.29641
@inproceedings{LearningVisual_Zhao_AAAI2024,
  title     = {Learning Visual Abstract Reasoning through Dual-Stream Networks},
  ...
}
```

When you move the entry into a topic file, keep the comment. [`upgrade`](#upgrade) uses it to find these entries, and once their official BibTeX can be downloaded, it replaces them and removes the comment. Metadata is less reliable than the publisher's BibTeX (author name spellings, missing pages, and odd capitalization), so review these entries.

#### Add BibTeX that you downloaded yourself <a id="local-bibtex"></a>

When a publisher blocks automated downloads, you can get the BibTeX in a browser. To add it, pass the `.bib` file, or a directory of `.bib` files, as an identifier:

```bash
bibcc add downloads/aaai_30001.bib downloads/acm/ --against bib/ --output added.bib
```

`add` treats each entry with fields as official BibTeX: it formats the entry, completes it from the venue library, suggests a key, and checks it for duplicates, without any lookup. To record where an entry came from, put a `% source: URL` line in the comment just before it. The URL appears in the report:

```bibtex
% source: https://ojs.aaai.org/index.php/AAAI/article/view/30001
@inproceedings{zhou2025continual,
  ...
}
```

#### Fill in empty entries <a id="fill-in-empty-entries"></a>

When a paper matches an empty entry of the staging file (same DOI, arXiv ID, title, or key), `add` replaces the empty entry and its comment with the new entry, in place, and keeps the key. The rest of the file doesn't change, and `add` verifies that before it writes. This works for papers that you look up again and for [BibTeX that you downloaded yourself](#local-bibtex).

To look up again every paper that has no entry yet, pass `--retry`. `add` retries the empty entries of the staging file and the papers that failed in its last report, `.bibcc/OUTPUT/add.txt`:

```bash
bibcc add --retry --output added.bib
```

At the end of each run, `add` prints the number of entries in the staging file, with and without fields, for example `added.bib: 42 entries (39 with fields, 3 empty)`.

#### Set the keys with a manifest <a id="manifests"></a>

To set the keys yourself, pass `--from` with a `.csv` or `.tsv` file. The `identifier` column is required, and the other columns are optional:

| Column | Description |
| --- | --- |
| `identifier` | Anything that `add` accepts as an identifier, including a `.bib` file |
| `method` | The METHOD part of the key, instead of the guess from the title |
| `venue` | The VENUE part of the key (for example, `CVPR` or `NeurIPS`). It also helps `add` find the official source of a paper whose metadata names no venue. |
| `year` | The YEAR part of the key: the year of the event |
| `key` | The whole key; it overrides the other columns |

Empty cells fall back to the suggested parts. A key that's already in use is an error, except that an empty entry keeps its own key when it's filled in.

```csv
identifier,method,venue,year,key
2501.13198,SD-LoRA,ICLR,2025,
10.1609/aaai.v39i1.30001,,,,CLE_Zhou_AAAI2025
```

#### What's left to do <a id="next-steps"></a>

The end of each run lists the papers that still need you: empty entries to fill in, and failed papers. Each item has the paper's title, the URL to get the BibTeX from, and the `--fallback` level that would have built the entry. After you get the missing BibTeX, add it as described in [Add BibTeX that you downloaded yourself](#local-bibtex), or run `add --retry` later.

The list is grouped by what to do next. The same word is in the `next` column of the reports of `add` and `upgrade`, so that a script or an agent can sort the papers without reading the details. The following table describes each value.

| `next` | Meaning | What to do |
| --- | --- | --- |
| `by hand` | The official BibTeX exists, but BibCC can't download it (AAAI, ACM, and Elsevier, for example) | Get it from the URL, and add it with `bibcc add FILE.bib` |
| `retry` | A site couldn't be reached, or a rate limit was hit | Run `bibcc add --retry` (or `bibcc upgrade`) later |
| `check` | No source has the paper, or the paper can't be added as given | Check the identifier, or try the paper's DOI or exact title |
| `wait` | There's no official BibTeX yet: the proceedings aren't out, or the entry uses interim CVF or OpenReview BibTeX | Run `bibcc add --retry` or `bibcc upgrade` once the proceedings are out |
| `upgrade` | `upgrade --report-only` found official BibTeX that can be downloaded now | Run `bibcc upgrade FILE.bib --in-place` |

`.bibcc/OUTPUT/add.txt` has one row per paper, with these tab-separated columns: identifier, outcome (`official`, `interim`, `metadata`, `empty`, `failed`, or `duplicate`), key, title, detail, `url`, and `next` (empty when nothing is left to do). A script or an agent can pick up the rows to work on.

#### Rate limits

`add` doesn't query DBLP directly, because its API is behind a bot challenge. Semantic Scholar allows few requests without a key; for higher limits, set `S2_API_KEY`. Requests that hit a rate limit are retried with backoff. The large listing pages (CVF, PMLR, NeurIPS, and ICLR) are fetched once per run, and each paper's official BibTeX is kept for 30 days in a disk cache (`$BIBCC_CACHE`, or else `~/.cache/bibcc`; `BIBCC_CACHE=off` turns it off), so a later run doesn't download it again.

<details>
<summary>All <code>add</code> options</summary>

| Option | Description |
| --- | --- |
| `IDENTIFIER ...` | DOIs, arXiv IDs or URLs, paper page URLs, quoted titles, or `.bib` files and directories of official BibTeX |
| `--from FILE` | Text file with one identifier per line (`#` starts a comment), or a `.csv` or `.tsv` [manifest](#manifests) |
| `--retry` | Also look up the empty entries of the staging file and the papers that failed in its last report |
| `--against PATH` | `.bib` file or directory (searched recursively) to check for duplicates; repeatable |
| `--output FILE` | Staging file that new entries are appended to, and whose empty entries are filled in (default: `added.bib`) |
| `--venues FILE` | Use only this venue library file (default: the user library merged with the project's `.bibcc-venues.yaml`) |
| `--preprint` | Keep arXiv papers as preprints (arXiv's BibTeX) |
| `--keep-title` | Don't title-case official titles (term protection still applies) |
| `--fallback LEVEL` | Build entries from metadata when official BibTeX is unavailable: `none` (default), `missing`, or `all` (see [When there's no official BibTeX](#when-there-is-no-official-bibtex)) |
| `--dry-run` | Print the entries without writing the staging file or the missing-venues YAML file |
| `--delay SECONDS` | Seconds to wait between papers, to respect API limits (default: `1`) |
| `--log-dir DIR` | Directory for the log, the report, and the missing-venues YAML file (default: `.bibcc/` next to the output) |

</details>

---

### Upgrade preprints to published versions with `upgrade` <a id="upgrade"></a>

`upgrade` finds preprints and interim entries in a `.bib` file that have since been published, and replaces them with the official BibTeX of the published version.

```bash
bibcc upgrade input.bib                        # dry run: report and diff in .bibcc/
bibcc upgrade input.bib --in-place             # write back to input.bib
bibcc upgrade input.bib --ids KeyA,KeyB --output out.bib
bibcc upgrade --report-only bib/ extra.bib     # only list what has been published
```

Three kinds of entries are candidates:

- **Preprints**: `@misc` and `@unpublished` entries, and entries whose journal is arXiv or CoRR. `upgrade` looks up the published version the same way that `add` does.
- **Interim entries**: conference papers cited with a CVF Open Access booktitle (CVPR, ICCV, or WACV) or an OpenReview one (NeurIPS, ICLR from 2024, or ICML). `upgrade` recognizes them by the venue library's interim names or by an `openreview.net` or `thecvf.com` URL. They're replaced once the paper is in IEEE Xplore, the NeurIPS or ICLR proceedings, or PMLR.
- **Metadata entries**: entries that `add --fallback` built from metadata, recognized by the `% BibCC: not the official BibTeX` comment above them. They're replaced, and the comment is removed, once their official BibTeX (or interim CVF or OpenReview BibTeX) can be downloaded. Those that still have none are listed as unchanged, with the reason and where to get the BibTeX by hand.

`upgrade` only replaces an entry with downloaded official BibTeX. For the sources, see [Where the official BibTeX comes from](#official-sources). The replacement does the following:

- Keeps the citation key, so that `\cite` commands keep working. A note suggests the conventional key, for example `..._ICML2026`.
- Keeps your title when it matches the published one, so that hand-made braces survive.
- Keeps custom fields such as `citation`, and drops preprint and interim fields (`eprint`, `archiveprefix`, `primaryclass`, and the arXiv, OpenReview, or CVF `url`). If the official BibTeX has no `url`, the entry gets none. To find such fields added back later, run `bibcc check fields`.
- Completes venue fields from the venue library, and proposes missing venues in `.bibcc/INPUT/missing_venues.yaml`. When an interim booktitle is replaced by a proceedings name that the library doesn't link to it yet, the YAML file proposes the link, so that `complete` recognizes the interim name next time.
- Is a whole-entry replacement, checked like other edits: the rest of the file, including comments above the entry, stays byte for byte. The only exception is the comment that marks a metadata entry, which is removed.

`upgrade` keeps a preprint whose published version has no downloadable BibTeX (AAAI, ACM, and Elsevier papers, and ECCV papers that aren't on SpringerLink yet), and the report gives the venue and where to get the BibTeX by hand. Preprints without a published version are listed as unchanged. If the arXiv comment says that the paper was accepted (for example, "Accepted at AAAI 2026") but it isn't indexed yet, the report includes that comment. Lookups that hit a rate limit are listed as failed; run `upgrade` again later or set `S2_API_KEY`. The tab-separated columns of `.bibcc/INPUT/upgrade.txt` are entry ID, status (`upgraded`, `unchanged`, or `failed`), detail, and `next` (see [What's left to do](#next-steps)).

**Report only.** `--report-only` checks any number of `.bib` files and directories (searched recursively) and writes `.bibcc/PATH/published.txt`. The report lists every candidate that now has a published version, with its venue, the official BibTeX source, and its URL (or why there's none). It downloads no BibTeX and changes nothing. Its last column, `next`, is `upgrade` for an entry that `upgrade` can replace now, and `by hand`, `wait`, or `retry` otherwise.

<details>
<summary>All <code>upgrade</code> options</summary>

| Option | Description |
| --- | --- |
| `PATH ...` | The `.bib` file to upgrade (with `--report-only`: any number of files and directories) |
| `--output FILE` | Write the upgraded file here (omit for a dry run) |
| `--in-place` | Write back to the input file |
| `--report-only` | Only report entries that have a published version, and where their official BibTeX is |
| `--ids KEYS` | Comma-separated citation keys to upgrade (default: all candidates) |
| `--venues FILE` | Use only this venue library file (default: the user library merged with the project's `.bibcc-venues.yaml`) |
| `--delay SECONDS` | Seconds to wait between entries, to respect API limits (default: `1`) |
| `--log-dir DIR` | Directory for reports and logs (default: `.bibcc/` next to the input) |

</details>

---

### Format files with `format` <a id="format"></a>

`format` reformats whole `.bib` files, like BibTeX Tidy. Unlike the other commands, which only touch the fields that they change, `format` rewrites the layout of every entry.

```bash
bibcc format bib/                     # dry run: one diff per changed file in .bibcc/
bibcc format bib/ --in-place          # write the changes
bibcc format refs.bib --output out.bib
bibcc format bib/ --check             # write nothing; exit 1 if a file isn't formatted (CI)
```

`PATH` can be `.bib` files or directories, which are searched recursively (`.bibcc/` directories are skipped). Here's the default style:

```bibtex
@inproceedings{GKEAL_Zhuang_CVPR2023,
  title     = {{GKEAL}: {Gaussian} Kernel Embedded Analytic Learning ...},
  author    = {Zhuang, Huiping and Weng, Zhenyu and ...},
  year      = {2023},
  month     = jun,
  booktitle = {2023 {IEEE/CVF} Conference on Computer Vision and Pattern Recognition ({CVPR})}
}
```

In detail, `format` does the following:

- Lowercases entry types and field names, indents fields by two spaces, and aligns `=` to the longest field name.
- Turns `"..."` values and bare numbers into `{...}`. Values joined with `#`, and macros such as `@string` names, stay as they are.
- Keeps one pair of braces around values wrapped in extra braces (`{{Whole Title}}` → `{Whole Title}`). It leaves `author` and `editor` alone, because `{{...}}` there keeps a corporate name such as `{{World Health Organization}}` together.
- Ends every field but the last with a comma, and adds missing commas.
- Turns months into macros (`{June}`, `"6"`, `Jun.` → `jun`).
- Writes page ranges with a double hyphen (`12-15`, `12 – 15` → `12--15`). It handles lists such as `S1-S9, 20-22` part by part.
- Puts one blank line between entries, and a single newline at the end of the file.
- Keeps the field order, unless you pass `--sort-fields`. With `--sort-fields`, the fields that `--field-order` lists come first, and every other field follows in source order. A `*` in the order marks where those other fields go, so `--field-order 'title,author,year,*,citation'` keeps `citation` last whatever fields an entry has.
- Otherwise copies values exactly, including line breaks inside them.
- Keeps `%` comments and `@string`, `@comment`, and `@preamble` blocks. With `--sort-entries`, a comment directly above an entry moves with it, and `@string` and `@preamble` blocks stay at the top.

`format` checks every result before writing anything: it parses the file again, which must contain the same entries, types, fields, and values (up to the preceding conversions), and formatting the file a second time must change nothing. `format` reports and skips files that fail the check, can't be parsed, or have duplicate keys.

Every style option can also come from the `format:` section of a config file, so that a project formats the same way for everyone without a long command line. `format` reads the user config and the nearest `.bibcc.yaml` above each `.bib` file. The options that you pass win over both, and each yes-or-no option has a `--no-` form that turns off a value from a config file (`--no-sort-fields`). For details, see [Config files](#config).

<details>
<summary>All <code>format</code> options</summary>

| Option | Description |
| --- | --- |
| `PATH ...` | `.bib` files or directories (searched recursively) |
| `--in-place` | Write the formatted text back to each file |
| `-o`, `--output FILE` | Write the formatted file here (single input file only) |
| `--check` | Write nothing; exit 1 if any file would change |
| `--sort-fields` | Reorder fields by `--field-order`; other fields follow in source order |
| `--field-order LIST` | Comma-separated order for `--sort-fields`; a `*` marks where the other fields go (default: the order that `add` uses, with the other fields last) |
| `--sort-entries` | Sort entries by citation key (case-insensitive) |
| `--keep-quotes` | Keep `"..."` values and bare numbers |
| `--keep-outer-braces` | Keep values wrapped in extra braces (`{{...}}`) |
| `--keep-months` | Don't turn months into macros |
| `--keep-pages` | Don't turn page ranges into `--` ranges |
| `--no-align` | Write `name = value` without aligning `=` (`--align` turns alignment back on) |
| `--indent N` | Field indent: a number of spaces, or `tab` (default: `2`) |
| `--blank-lines N` | Blank lines between entries (default: `1`) |
| `--trailing-comma` | Put a comma after the last field |
| `--drop-empty` | Remove fields with empty values (`{}` or `""`) |
| `--no-sort-fields`, `--no-keep-quotes`, and so on | Turn off a yes-or-no setting that a config file turns on |
| `--config FILE` | Use only this config file, instead of the user config and the project's `.bibcc.yaml` |
| `--no-config` | Read no config file |
| `--log-dir DIR` | Directory for diffs and logs (default: `.bibcc/` next to each input) |

</details>

---

### Align a PDF library with `librarian` <a id="librarian"></a>

`librarian` aligns your PDF library with your bibliography. It has three subcommands:

```bash
# Find .bib entries whose PDFs are missing from your library.
bibcc librarian missing input.bib ~/papers
bibcc librarian missing bib/ extra.bib ~/papers --skip-empty

# Find library PDFs that the .bib files don't reference.
bibcc librarian extra bib/ ~/papers

# Rename PDFs to citation-key names by matching titles.
bibcc librarian rename input.bib ~/Downloads/papers --dry-run   # preview
bibcc librarian rename input.bib ~/Downloads/papers             # apply
```

**Library.** `missing` and `extra` expect PDFs named after citation keys (`ISPC_Wang_CVPR2024.pdf`). They take any number of `.bib` files and directories (searched recursively for `.bib` files, skipping hidden directories such as `.bibcc/`), followed by the library as the last argument. A key that's in several files counts once. The library is a directory of PDFs (searched recursively) or a listing file. The listing file is any text file with one PDF name per line, for example the output of `ls ~/papers > papers.txt`. Lines can contain other text (such as the dates and sizes from a Windows `dir` listing), and `librarian` reads both UTF-8 and UTF-16 files.

**Scripts.** `missing` exits with status 1 when some PDFs are missing, and 0 when every entry has its PDF. To leave out empty entries, whose BibTeX you haven't added yet, pass `--skip-empty`. The reports go next to the first `.bib` path.

**Renaming.** Export PDFs from Zotero or a similar reference manager with full titles in the filenames (for example, `Author 等 - 2025 - Full Paper Title.pdf`). `librarian rename` takes the text after the last ` - ` as the title, normalizes it (ignoring case, braces, and punctuation), and renames the PDF to `CITATION_KEY.pdf` when exactly that title is in the `.bib` file. When several entries share the title (for example, a conference paper and its journal version), `librarian` lists the PDF as ambiguous, with the candidate keys, and doesn't rename it. Files are renamed in place, and existing files are never overwritten. The order of the files doesn't matter.

<details>
<summary>All <code>librarian</code> options</summary>

| Subcommand | Arguments | Report |
| --- | --- | --- |
| `missing` | `BIB [BIB ...] LIBRARY [--skip-empty]` | `missing_pdfs.txt` |
| `extra` | `BIB [BIB ...] LIBRARY` | `extra_pdfs.txt` |
| `rename` | `BIB_FILE PDF_FOLDER [--dry-run]` | `rename_report.txt` |

</details>

---

### Count citations and verify titles with `scholar` <a id="scholar"></a>

`scholar` has two subcommands that work with online sources.

#### Citation counts

`scholar cite` builds Google Scholar citation URLs and helps you fill in citation counts interactively:

```bash
bibcc scholar cite input.bib                         # dry run: show the URLs
bibcc scholar cite input.bib -i                      # interactive: fill in the counts
bibcc scholar cite input.bib --open --batch-size 10  # open the URLs in your browser in batches
bibcc scholar cite input.bib -i --include-filled     # check filled-in entries again
```

`cite` writes Google Scholar search URLs to `.scholar_urls.txt`. In interactive mode, it opens each paper's Google Scholar search in your browser (you can skip an entry or quit at any time), asks for the citation count, and stores it in a `citation` field. Unless you pass `--output`, it writes the counts back to the input file. Only the `citation` fields change.

#### Title verification

`scholar titles` verifies paper titles against CrossRef, arXiv, and Semantic Scholar:

```bash
bibcc scholar titles input.bib
bibcc scholar titles input.bib --retry-errors bib/.bibcc/input.bib/title_report.txt  # retry failures
bibcc scholar titles input.bib --ids ID1,ID2                                         # specific entries
```

`titles` looks up each title in this order:

1. Entries with a DOI are checked against CrossRef only.
1. Entries with an arXiv ID are checked against arXiv.
1. Otherwise, or when the arXiv title matches, Semantic Scholar is searched by title.
1. If nothing has matched, a CrossRef title search is the last resort.

A title only counts as found when it matches exactly (ignoring case and punctuation). The report, `.title_report.txt`, lists titles whose capitalization differs from the published one, lookups that failed (because of network errors or rate limits), and titles that no source knows. To check only the failed lookups again, pass that report to `--retry-errors`; the report is updated in place. Semantic Scholar allows few requests without a key, so for larger files, set `S2_API_KEY`. `titles` doesn't query DBLP, because its API is behind a bot challenge.

<details>
<summary>All <code>scholar</code> options</summary>

Options for `cite`:

| Option | Description |
| --- | --- |
| `--interactive`, `-i` | Fill in citation counts interactively (recommended) |
| `--open` | Open the URLs in your browser in batches |
| `--batch-size N` | URLs per batch (default: `5`) |
| `--include-filled` | Include entries that already have citation counts |
| `--output`, `-o FILE` | Output file (omit for a dry run) |
| `--log-dir DIR` | Directory for reports and logs (default: `.bibcc/` next to the input) |

Options for `titles`:

| Option | Description |
| --- | --- |
| `--delay`, `-d SECS` | Seconds to wait between API requests (default: `0.5`) |
| `--quiet`, `-q` | Don't print progress |
| `--retry-errors REPORT` | Check only the failed lookups of a previous report again |
| `--ids IDS` | Comma-separated entry IDs to check |

</details>

---

### Merge `.bib` files with `compose` <a id="compose"></a>

`compose` combines the `.bib` files of a directory tree into a single bibliography:

```bash
bibcc compose compose ./my-bibs combined.bib
bibcc compose compose ./my-bibs combined.bib --no-dup-warning
```

`compose` inserts source path markers (`% === source: path/file.bib ===`) between files and keeps all original comments. By default, it warns about duplicate entry IDs; to turn off the warning, pass `--no-dup-warning`. It skips the output file and anything under `.bibcc/`, so the output can live inside the input directory.

---

## Output files

BibCC writes the reports about each input to a directory of its own, `.bibcc/NAME/`, next to the input, and the logs to `.bibcc/NAME/logs/`. `NAME` is the input's file or directory name. For example, checking `bib/refs.bib` writes `bib/.bibcc/refs.bib/title_case.txt` and `bib/.bibcc/refs.bib/logs/checker.log`. To delete everything that BibCC wrote about one file, delete its directory.

The layout follows these rules:

- **Choose another directory.** To use `DIR` instead of `.bibcc/`, pass `--log-dir DIR` to `complete`, `add`, `upgrade`, `format`, or `scholar cite`. The files go to `DIR/NAME/`.
- **No nesting.** An input that is already inside a `.bibcc/` directory (for example, a scratch file in `.bibcc/work/`) gets `reports/NAME/` next to it, not another `.bibcc/`.
- **No stale reports.** A check or a dry run that finds nothing removes its old report, so every report that's left describes the last run.
- **No input file.** `check venues` writes its log to `.bibcc/logs/` in the current directory.
- **Upgrading from 0.3.** BibCC 0.3 wrote flat files such as `.bibcc/refs.bib.title_case.txt`. The first run on an input moves its old files into `.bibcc/refs.bib/` and logs what it moved. It never deletes them, so a filled-in missing-venues YAML file is kept.

To keep these files out of version control, add `.bibcc/` to the `.gitignore` file of your bibliography project. The project venue library, `.bibcc-venues.yaml`, lives outside that directory so that you can commit it.

The following table lists the files that each command writes to `.bibcc/NAME/`:

| Command | Report files | Log file |
| --- | --- | --- |
| `check` | `missing_fields.txt`, `title_case.txt`, `smart_protection.txt`, `citation_keys.txt`, `field_issues.txt`, `edition_fields.txt`, `edition_schemas.txt`, `official_fields.txt`, `official_venues.txt`, `official_unchecked.txt`, `missing_venues.yaml` (`editions` and `official` with `--learn`) | `logs/checker.log` |
| `complete` | `complete.diff` (dry-run preview), `missing_venues.yaml`, `missing_venues.txt`, `conflicts.txt`, `incomplete_entries.txt`, `venue_check.txt` (`--online`) | `logs/completer.log` |
| `add` | The staging `.bib` file itself (entries appended or filled in), `add.txt`, `missing_venues.yaml` | `logs/adder.log` |
| `upgrade` | `upgrade.txt`, `upgrade.diff` (dry-run preview), `missing_venues.yaml`, `published.txt` (`--report-only`, next to the first `PATH`) | `logs/upgrader.log` |
| `format` | `format.diff` (dry-run preview, one for each changed file) | `logs/formatter.log` |
| `scholar cite` | `scholar_urls.txt` | `logs/scholar.cite.log` |
| `scholar titles` | `title_report.txt` | `logs/scholar.titles.log` |
| `librarian` | `missing_pdfs.txt`, `extra_pdfs.txt`, `rename_report.txt` | `logs/librarian.log` |
| `compose` | The composed `.bib` file | `logs/composer.log` |

## Venue library <a id="venue-library"></a>

The venue library powers `complete`, and completes the entries that `add` and `upgrade` create. BibCC doesn't ship one: every user builds their own, either from scratch or from a shared library.

### User and project libraries

There are two scopes of venue library:

| Scope | File | Holds |
| --- | --- | --- |
| `user` | `$BIBCC_VENUES` if it's set, or else `$XDG_CONFIG_HOME/bibcc/venues.yaml` (`~/.config/bibcc/venues.yaml`) | Venues for all your projects |
| `project` | `.bibcc-venues.yaml`: the nearest one in the directory of the `.bib` file or a parent directory | Venues for one project; commit it with the bibliography so that your coauthors share it |

**Reading.** Commands read both libraries, merged. A venue that's in only one of them is used as is. A venue that's in both gets the fields of both, and where both define a field, the project's value wins. `bibcc venues where` lists the fields that the project overrides. When `complete` patches entries, its log names the library each entry's venue record comes from.

**Writing.** Commands write to one library only, and say which file they write:

- `complete --update-venues`, `complete --update-venues-only`, and `venues import` write to the user library, unless you pass `--scope project`.
- For `complete`, `--scope project` needs an existing `.bibcc-venues.yaml`. To create one in your project root, run `bibcc venues init --scope project`. `venues import --scope project` creates the file in the current directory if there's none.
- `--venues FILE` uses that one file instead of both libraries, for reading and writing.

```bash
bibcc venues where bib/refs.bib            # the libraries that apply, their sizes, and the overrides
bibcc venues init --scope project          # start a project library in the current directory
bibcc venues import miaa --scope project   # fill it from a shared library
```

### Shared libraries

[`examples/venues/`](examples/venues/) holds libraries that labs and people built for their own fields, such as the MIAA lab's [`miaa`](examples/venues/miaa.yaml): machine learning and computer vision journals and proceedings from 2016 to 2026, with CVF and OpenReview interim booktitles linked. They're a head start, not a standard.

```bash
bibcc venues examples                  # list them
bibcc venues import miaa --dry-run     # preview what one would add to your user library
bibcc venues import miaa               # merge it into your user library
bibcc venues import ~/lab.yaml         # a file or an https:// URL works too
```

`import` only adds: it adds records that you don't have, and fields, aliases, and interim booktitles that your records lack. Where a field differs, `import` keeps your value and lists the difference, unless you pass `--overwrite`. To share your library or improve one, see [Contributing a library](examples/venues/README.md#contributing-a-library).

### Library format

A library is a YAML file with two lists of records, `journals` and `proceedings`, and an optional third, `families` (see [Venue families](#venue-families)):

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
  - name: 2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)
    year: '2025'
    interim:                    # booktitles used before the proceedings were out
      cvf:
        - Proceedings of the Computer Vision and Pattern Recognition Conference (CVPR)
        - Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)
    fields:
      venue: Nashville, TN, USA
      publisher: IEEE
```

Matching ignores braces, case, the difference between `\&` and `&`, and extra spaces:

- **Journals** match by name, any alias, or ISSN.
- **Proceedings** match by name or alias and by the entry's `year`, or else by an interim booktitle: the name that CVF Open Access (`cvf`) or OpenReview (`openreview`) gives the same proceedings. An entry matched through an interim name only gets `venue` and `month`, and is reported so that `bibcc upgrade` can replace it. Until a conference's proceedings are out, its record is named by the interim booktitle. Merging a proposal from `add` or `upgrade` renames the record to the published name and keeps the old one under `interim`.
- **Several matches**: if several records match one entry, nothing is added, and the entry is reported as ambiguous.

<a id="proceedings-in-several-books"></a>**Proceedings in several books.** Some proceedings appear as several books, such as the LNCS volumes of ECCV and MICCAI, and each book has its own `volume` and `part`. Springer's chapter exports leave both out, so the record lists them under `books`, keyed by the book's ISBN as it appears in its chapters' DOIs (`10.1007/978-3-031-72649-1_13` belongs to book `978-3-031-72649-1`):

```yaml
proceedings:
  - name: Computer Vision -- ECCV 2024
    year: '2025'
    fields:
      venue: Milan, Italy
    books:
      978-3-031-72649-1: {volume: '15059', part: XXVI}
```

`complete` gives an entry whose DOI names one of the books that book's fields, over the record's own, and `check official` doesn't report them as `local_only`. You don't write the table by hand: when the entries of a book agree on a `volume` or `part` that the official BibTeX lacks, `bibcc check official FILE --learn` writes it.

### Venue families <a id="venue-families"></a>

A conference has one proceedings record for each year. A `families` record describes the conference across its editions, so that the fields every edition shares live in one place:

```yaml
families:
  - name: International Conference on Machine Learning
    acronym: ICML
    fields:                     # every edition gets these; an edition's own value wins
      publisher: PMLR
      series: Proceedings of Machine Learning Research
    entry_fields: [pages, pdf, url]
    learned_from: official BibTeX of 6 entries (2025), 2025-07-01
```

An edition belongs to the family whose name or alias it shares once years, ordinals, and a leading "Proceedings of the" are removed, or whose acronym it carries. `complete`, `add`, and `upgrade` give each edition the family's fields under its own, the fill-in YAML shows them commented out as `# from family NAME`, and `check venues` doesn't report them as missing. Every command that relates editions groups them by family record, or else by their name without the year and ordinal.

A family record can also say where the official BibTeX of the conference comes from. BibCC ships a table of these facts for the conferences it knows (which ones PMLR publishes, which ones use CVF Open Access before IEEE Xplore, and so on); a family record with the same acronym overrides the keys it sets, and one with a new acronym adds a conference. For example, a new PMLR conference needs only this record:

```yaml
families:
  - name: Conference on Parsimony and Learning
    acronym: CPAL
    provider: pmlr
```

To see the table that applies, with the rows your family records change, run `bibcc venues providers` (`--format json` for scripts). The keys are `provider` (`xplore`, `springer`, `proceedings`, `pmlr`, `acl`, `ijcai`, `openreview`, or `blocked`), `site` (the proceedings site, for `proceedings`), `interim` (`cvf` or `openreview`), `interim_since` (the first year that the interim BibTeX isn't the official one), `pattern` (a regular expression that names the conference in a booktitle), `workshop_of`, `acronym_aliases`, `blocked_by`, and `manual_url`. For the built-in table, see [`src/bibcc/data/families.yaml`](src/bibcc/data/families.yaml).

### Venue schemas <a id="venue-schemas"></a>

A venue's *schema* is the list of per-paper fields that the official BibTeX of every paper of the venue has, such as `pages`, `doi`, and `url`. It's the `entry_fields` key of a journal record, a family record, or a proceedings record (for the one year that a venue's export differs from its family's). A schema leaves out the fields that every entry has, the fields that the venue library supplies, and exporter bookkeeping. `learned_from` says where the schema comes from.

You don't write schemas by hand. Two checks learn them:

- `bibcc check official FILE --learn` learns them from the official BibTeX that it downloads, the reliable source.
- `bibcc check editions FILE --learn` learns them from the entries of each venue, for the venues whose BibTeX BibCC can't download.

With a schema, `check editions` reports the fields an entry lacks, and `check missing` doesn't ask for a field that the venue never exports. For proceedings, the latest year's fields become the family's schema, and a year whose fields differ gets its own schema on its proceedings record. A schema learned from a later year stays: a run that sees only older years gives those years their own schemas instead, so the order in which you check your files doesn't matter.

A schema for a journal or an edition that has no record in the library goes into the fill-in file `.bibcc/INPUT/missing_venues.yaml`, with the record; merging the record with `complete --update-venues` adds the schema too. For a venue without a schema, `check editions` uses its publisher's default schema as a labeled guess (`default_missing`), which BibCC computes from the library's schemas and never writes.

### Months <a id="months"></a>

The month of an entry comes from the official BibTeX first, as exported, even when it isn't the event month (AAAI's BibTeX gives the month of its issue). When the official BibTeX has no month, the following rules apply:

- **Proceedings**: the month of the event, from the library record, but only when the whole event falls in that month. For an event held across two months, such as NeurIPS 2022 (November 28 to December 9), set `month: none`. For an event held in several places, use the dates of the main venue.
- **Journals**: the month of the issue that the paper appears in, not the date it went online. A journal record has no month, because each issue has its own. For a journal without monthly issues, such as TMLR, set `month: none`.

A record with `month: none` never adds a month, `check missing` doesn't ask for one, and `check editions` doesn't expect one. An official month that gives a period across two months, such as `29 Jul--01 Aug`, is dropped and reported by `add` and `upgrade`.

Whenever `bibcc` saves a library, it rewrites the library in this sorted form. Comments other than the header aren't kept. For the format of the generated fill-in file, see [`missing_venues.example.yaml`](missing_venues.example.yaml).

### Add new venues

To add the venues that a `.bib` file needs, do the following:

```bash
# 1. Generate a YAML file for unknown venues (add and upgrade write one too).
bibcc complete input.bib            # --online also pre-fills from CrossRef

# 2. Edit .bibcc/input.bib/missing_venues.yaml. Most fields are pre-filled.
#    To check only these records before merging, run
#    `bibcc check venues --venues .bibcc/input.bib/missing_venues.yaml`.

# 3. Merge the file into your user library (or --scope project) and complete in one step.
bibcc complete input.bib --output out.bib --update-venues
#    Or only update the library, and complete the entries later.
bibcc complete input.bib --update-venues-only
```

`complete` skips entries without a year or a venue. The log lists the proceedings and journal entries among them as entries to fix, and only counts the `@misc` ones (such as arXiv preprints), which aren't expected to have a venue. Both are reported, with their entry type, in `.bibcc/INPUT/incomplete_entries.txt`.

## Protected terms <a id="protected-terms"></a>

`check quote` keeps your protected terms in `{braces}`: acronyms such as `CLIP`, mixed-case names such as `LoRA`, and method names such as `CIP-Net`. Like the venue library, terms live in two scopes:

| Scope | File | Holds |
| --- | --- | --- |
| `user` | `$BIBCC_TERMS` if it's set, or else `$XDG_CONFIG_HOME/bibcc/terms.txt` (`~/.config/bibcc/terms.txt`) | Terms for all your projects |
| `project` | `.bibcc-terms.txt`: the nearest one in the directory of the `.bib` file or a parent directory | Terms for one project; commit it with the bibliography so that your coauthors share it |

A terms file has one term per line, with the case that titles use; blank lines and `#` comments are ignored. `check quote` reads both files on top of its built-in vocabulary of names, and `--apply` braces their terms. To list a hyphenated method name, list the whole compound (`CIP-Net`), because a listed part doesn't keep a compound whole.

To manage terms files, use `bibcc terms`. Commands write to the user file, unless you pass `--scope project`; a project file that doesn't exist yet goes next to the project venue library, or else into the current directory.

```bash
bibcc terms where bib/refs.bib              # the files that apply, and how many terms each has
bibcc terms list                            # every term, with the scope of its file
bibcc terms add CIP-Net Transformer-XL      # keep two method names whole in every project
bibcc terms add SD-LoRA --scope project     # share a term with your coauthors
bibcc terms examples                        # list the shared terms files
bibcc terms import miaa                     # add the MIAA lab's terms to your user file
```

[`examples/terms/`](examples/terms/) holds shared terms files, such as the MIAA lab's [`miaa`](examples/terms/miaa.txt). `import` adds only the terms that your file lacks, ignoring case. To share a terms file, see [Contributing a terms file](examples/terms/README.md#contributing-a-terms-file).

## Config files <a id="config"></a>

A config file holds your settings, so that you don't repeat options on every run and everyone on a project gets the same result. Like the venue library, a config has two scopes:

| Scope | File | Holds |
| --- | --- | --- |
| `user` | `$BIBCC_CONFIG` if it's set, or else `$XDG_CONFIG_HOME/bibcc/config.yaml` (`~/.config/bibcc/config.yaml`) | Settings for all your projects |
| `project` | `.bibcc.yaml`: the nearest one in the directory of the `.bib` file or a parent directory | Settings for one project; commit it with the bibliography |

A command reads both files. Where both set a key, the project's value wins, and an option that you pass on the command line wins over both. Each command reads its own section of the file. This release reads the `format:` section, which `bibcc format` uses:

```yaml
format:
  sort_fields: true
  field_order:
    first: [title, author, year, month, booktitle, journal, publisher, pages, doi, url]
    last: [citation]
  indent: 2
```

The `field_order` puts the `first` fields at the top and the `last` fields at the bottom. Every field that it doesn't list goes between them, in source order, so a field that you've never seen before keeps its place instead of breaking the order. The `format:` section takes the following keys:

| Key | Default | Description |
| --- | --- | --- |
| `sort_fields` | `false` | Reorder fields by `field_order` |
| `field_order` | The order that `add` uses | `first` and `last` lists, or one list in which `"*"` marks where the other fields go |
| `sort_entries` | `false` | Sort entries by citation key |
| `keep_quotes` | `false` | Keep `"..."` values and bare numbers |
| `keep_outer_braces` | `false` | Keep values wrapped in extra braces (`{{...}}`) |
| `keep_months` | `false` | Don't turn months into macros |
| `keep_pages` | `false` | Don't turn page ranges into `--` ranges |
| `align` | `true` | Align `=` to the longest field name |
| `indent` | `2` | A number of spaces, or `tab` |
| `blank_lines` | `1` | Blank lines between entries |
| `trailing_comma` | `false` | Put a comma after the last field |
| `drop_empty` | `false` | Remove fields with empty values |

BibCC checks every file it reads. An invalid value, such as `indent: wide`, stops the command for the files that the config applies to. A key that this release doesn't know, a section that it doesn't read, and a field name in `field_order` that isn't a known BibTeX field (`volumn`) are reported in the log, and the rest of the file still applies.

To manage config files, use `bibcc config`:

```bash
bibcc config where bib/refs.bib           # every file that applies, and each setting with where it comes from
bibcc config init --scope project         # a .bibcc.yaml that lists every setting, commented out
bibcc config examples                     # list the shared configs
bibcc config import miaa --scope project  # merge a shared config into the project's .bibcc.yaml
bibcc config profile miaa --scope project # import the shared config, venue library, and terms file named miaa
```

`where` is the one place to see what BibCC reads for a path. After the settings, it lists the venue libraries, the terms files, and the provider table that apply, each with its scope and size.

[`examples/config/`](examples/config/) holds shared configs, such as the MIAA lab's [`miaa`](examples/config/miaa.yaml), which sets the title-first field order of the lab's surveys with `citation` last. `import` adds the settings that your file lacks. Where a setting differs, it keeps your value and lists the difference, unless you pass `--overwrite`. `import` changes only the lines of the settings that it adds or updates, so your comments stay. A setting that `config init` wrote commented out takes the place of its commented line. To share a config, see [Contributing a config](examples/config/README.md#contributing-a-config).

### Set up a project from a lab profile <a id="config-profile"></a>

A lab profile is the config, venue library, and terms file that share one name in `examples/`, such as `miaa`. To give a survey all three, run the following in its directory:

```bash
bibcc config profile miaa --scope project
```

`profile` runs `config import`, `venues import`, and `terms import` for that name, each into the project file of its kind (or, without `--scope project`, into your user files). It skips a kind that has no shared file of that name. To preview the changes, pass `--dry-run`.

The imports copy the profile: later changes to your files stay in your files. To send your changes back to a profile that you maintain, import your files into its files from a BibCC checkout. Each `import` takes a target file (`--config FILE`, `--venues FILE`, or `--terms FILE`) instead of a scope, and `--overwrite` lets your values win where they differ:

```bash
bibcc config import ~/.config/bibcc/config.yaml --config examples/config/miaa.yaml --overwrite
bibcc venues import ~/.config/bibcc/venues.yaml --venues examples/venues/miaa.yaml --overwrite
bibcc terms import ~/.config/bibcc/terms.txt --terms examples/terms/miaa.txt
```

An import only adds and changes values, so remove a setting, a record, or a term from the profile by hand.

When a command creates a project file, such as `.bibcc-venues.yaml`, it puts the file next to the project's other BibCC files (`.bibcc.yaml`, `.bibcc-venues.yaml`, or `.bibcc-terms.txt`), so that all three stay in the project's root directory. If the project has none yet, the file goes in the current directory. `init --scope project` always writes to the current directory.

## Development <a id="development"></a>

To set up a development checkout, run the following:

```bash
git clone https://github.com/3hiuwoo/BibCC.git && cd BibCC
git switch dev                 # work happens on dev; main holds only releases
uv sync                        # install the package (editable) and the dev tools
uv run pytest                  # run the tests (no network access; API responses are canned)
uv run ruff check .            # lint
uv tool install --editable .   # optional: put bibcc on your PATH, following the checkout
```

The code lives in `src/bibcc/`. Each command is one module, registered in `cli.py`: `checker.py`, `completer.py`, `adder.py`, `upgrader.py`, `formatter.py`, and `utils/` for `librarian`, `scholar`, `compose`, `venues`, `terms`, and `config`. These modules hold the shared pieces:

- `bibedit.py`: minimal, verified edits.
- `sources.py`: CrossRef, arXiv, OpenReview, and Semantic Scholar lookups.
- `official.py`: finding and downloading official BibTeX.
- `families.py` and `data/families.yaml`: the provider table, which says where each conference's official BibTeX comes from.
- `cache.py`: the disk cache of downloaded official BibTeX.
- `schemas.py`: learning venue schemas.
- `scopes.py`: the user and project scopes, file names, and shared examples that the venue libraries, terms files, and configs have in common.
- `venues.py`: the venue libraries and their scopes.
- `terms.py`: the protected-terms files and their scopes.
- `config.py`: the config files, their scopes, and the settings of each section.
- `missing_venues.py`: the fill-in YAML file.
- `crosscheck.py`: the CrossRef check of `complete --online`.
- `logging_utils.py`: reports and logs.

For code conventions, branches, versioning, and releases, see [`CONTRIBUTING.md`](CONTRIBUTING.md). For the changes in each version, see [`CHANGELOG.md`](CHANGELOG.md). BibCC is released under the [MIT License](LICENSE).

## Additional resources

Apart from `bibcc format`, BibCC keeps your existing formatting and only adds or replaces the fields that it targets. If you want another formatter, try one of these:

- [BibTeX Tidy](https://flamingtempura.github.io/bibtex-tidy/)
- The LaTeX Workshop extension for VS Code

## Roadmap

This section lists planned and shipped work, grouped by command. [`CHANGELOG.md`](CHANGELOG.md) records the changes in each version.

### Planned

- **Field removal through the venue library**: a `remove:` list on a venue record, so that `complete --resolve library` deletes a field the record should never have defined from the entries it patched. Scoped to the venue's own entries, so that cleaning one venue never touches another. Ideas and requests are welcome as issues.

### Shipped

- **`complete` and the venue library**
  - A unified venue management workflow: the YAML venue library and `--update-venues`.
  - User and project venue libraries, merged with project priority; no bundled library, and shared ones in `examples/venues/` (`bibcc venues`).
  - Aliases, ISSN matching, and previous-edition pre-fill.
  - Minimal, verified edits that keep the rest of the file untouched (`bibedit.py`).
  - Fields guessed from journal and conference names (the publisher), marked `# auto-guessed`.
  - YAML pre-fill from existing bibliographies in the same venue.
  - Conflicts reported in every mode, including dry runs (`.conflicts.txt`).
  - Interim booktitles (CVF Open Access and OpenReview) linked to their proceedings (`interim:` in the library).
  - An opt-in CrossRef source that pre-fills the YAML file and checks entries and the library, off by default (`--online`).
  - A fill-in YAML file that's merged across runs and shared by `complete`, `add`, and `upgrade`.
  - Conflict resolution: `--resolve library` overwrites fields with the library's values, scoped by `--fields` and `--ids`.
  - Merging the fill-in file into the library without completing the `.bib` file (`--update-venues-only`).
  - Family records with the fields that every edition of a conference shares, and the facts about where its official BibTeX comes from (`families:` in the library).
  - Venue schemas, the per-paper fields that a venue's official BibTeX has, learned by `check official --learn` and `check editions --learn` (`entry_fields`).
  - The values that every edition of a conference shares, moved into its family record (`check venues --apply`), and the provider table that applies, with the rows your family records change (`venues providers`).
- **`check`**
  - Citation key legibility, including the first author's surname (`check keys`).
  - Exit status 1 on findings, for scripts (`--strict`), and your own terms braced in titles (`check quote --apply`).
  - Field name typos, malformed values, and duplicate papers (`check fields`).
  - Venue library records with missing fields (`check venues`).
  - Cross-edition consistency: fields that one edition of a conference defines and another lacks (`check venues`).
  - Entry fields of the venue's schema, learned from official BibTeX or proposed by the other entries of the venue (`check editions`).
  - Entries compared with their official BibTeX, downloaded again or saved by hand, and the official fields that they lack added back (`check official`).
  - Robust term protection that skips numbers and filters author names (`check quote`).
  - User and project protected-terms files that `check quote` reads and `--interactive` adds to, with shared ones in `examples/terms/` (`bibcc terms`).
  - Robust title case with hyphenated words and a configurable style (`check title`).
  - Interactive title case application (`check title --interactive`).
  - A modular sub-checker architecture (the `checkers/` package), with one subcommand for each check.
- **`add`**
  - Papers added by DOI, arXiv ID, or title, with duplicate checks (`bibcc add`).
  - Official BibTeX from IEEE Xplore, Springer, PMLR, NeurIPS, ICLR, ACL Anthology, IJCAI, OpenReview, and arXiv, with interim CVF and OpenReview BibTeX, and empty entries to fill in by hand.
  - Paper page URLs as identifiers.
  - Entries built from metadata when official BibTeX is unavailable, and a list of what's left to do by hand (`--fallback` and `add.txt`).
  - BibTeX that you downloaded yourself, empty entries filled in place, manifests that set the keys, and retries (`.bib` identifiers, `--from FILE.csv`, and `--retry`).
- **`upgrade`**
  - Preprints replaced with their published versions (`bibcc upgrade`).
  - Official BibTeX only; interim CVF and OpenReview entries and entries built from metadata are candidates too.
  - A report of which preprints have been published, with the official BibTeX URL (`--report-only`).
- **`format`**
  - Whole-file formatting: alignment, braces, month macros, and sorting (`bibcc format`).
- **`librarian`**
  - Unified PDF library alignment: missing, extra, and rename.
- **`scholar`**
  - A unified citation and title tool (`cite` and `titles`).
  - Title verification without DBLP, which is behind a bot challenge: Semantic Scholar, with a CrossRef title search as a fallback.
- **`compose`**
  - Directory-based `.bib` composition that keeps comments.
- **CLI and output**
  - A unified CLI entry point (`bibcc`).
  - Consistent output formatting and logging: shared format constants and a report writer.
  - One report directory for each input (`.bibcc/NAME/`), with no nesting and no stale reports.
  - An installable command-line tool (`pyproject.toml` and `uv`).
  - Tagged releases, CI on every push and pull request, and an MIT license (`.github/workflows/` and `CONTRIBUTING.md`).
