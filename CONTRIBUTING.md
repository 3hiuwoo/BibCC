# Contributing to BibCC

Thanks for helping. Bug reports, ideas, code, and venue libraries are all welcome.

## Development setup

To set up a development checkout, run the following commands:

```bash
git clone https://github.com/3hiuwoo/BibCC.git && cd BibCC
git switch dev                 # work happens on dev; main holds only releases
uv sync                        # .venv with BibCC (editable) and the dev tools
uv run bibcc --help            # run from the checkout
uv run pytest                  # tests (no network access; API responses are canned)
uv run ruff check .            # lint
uv tool install --editable .   # optional: `bibcc` on your PATH, following the checkout
```

Tests never use your own venue library: `tests/conftest.py` points the user library at a temporary directory for every test.

## Code conventions

- **Package layout**: All code lives in `src/bibcc/`. Import with absolute `bibcc.` paths, and don't modify `sys.path`.
- **Output**: Tool logic doesn't call `print()`. It accepts a `log: Callable[[str], None]` callback and logs through it. Only `cli.py` (usage and `--version`) and the `Logger` sink in `logging_utils.py` write to stdout.
- **Output format**: The constants for reports and logs live in `bibcc/logging_utils.py`: `SEPARATOR_WIDTH`, `SEPARATOR_HEAVY`, `SEPARATOR_LIGHT`, `SEPARATOR_THIN`, `Logger`, and `write_report`. Use them instead of hard-coding widths or separator characters.
- **Commands**: The main tools expose `build_parser()` and `run(args)`. The tools in `utils/` expose `build_parser()` and `main()`, with subcommands. Register a new tool in `bibcc/cli.py`.
- **Help pages**: Build parsers with `bibcc.helptext.HelpFormatter` and an `epilog(...)` that lists examples, output files, the exit status, and environment variables. `tests/test_cli.py` requires every help page to have a description, `examples:`, `DOCS_URL`, and help text for every option.
- **Writing style**: User-facing text, such as the docs, help pages, and messages, follows the [Google developer documentation style guide](https://developers.google.com/style). Keep text that BibCC parses back, or that tests check exactly, unchanged. This includes marker comments, report headers, and status words.
- **Version and changelog**: The version lives only in `src/bibcc/__init__.py`, and `pyproject.toml` reads it from there. Record user-visible changes in `CHANGELOG.md` under the top, unreleased version. For details, see [Versioning](#versioning).
- **Venue library**: The venue library is user data, and BibCC never packages one. Commands read the merged user and project libraries with `bibcc.venues.load_library(args.venues or None, start=BIB_FILE)`, and treat that view as read-only. They write exactly one file, from `open_library(scope, ...)`, and log which scope and file they write. Shared libraries live in `examples/venues/`, and tests use `tests/conftest.py::MIAA_VENUES`. When you write YAML strings by hand, such as in the missing-venues file, quote them with `json.dumps` so that backslashes and quotes are escaped.
- **Network access**: Go through `bibcc.sources.fetch_url` or `fetch_json`, so that tests can replace one function. Tests never use the network. Canned API responses live in `tests/fixtures/sources/`.
- **Tests**: Add tests under `tests/` for new behavior.

## Branches

The repository uses the following branches and tags:

- **`main`**: The latest release, and nothing else. It moves only when a version comes out, and every commit on it is a tagged release. It's the default branch on GitHub, so the README there describes the latest release, and `uv tool install git+https://github.com/3hiuwoo/BibCC` without a tag installs it. CI fails any push or pull request to `main` whose version isn't a release with a dated changelog section.
- **`dev`**: The development line, where all work lands. It must always pass CI. Its version is the next release with a `.dev0` suffix. Users who want the newest changes install it with `@dev`.
- **Work branches**: Short-lived branches off `dev`, named `feat/TOPIC`, `fix/TOPIC`, `docs/TOPIC`, or, for venue library contributions, `venues/LIBRARY`. Open a pull request to `dev`. Because GitHub proposes `main` as the base, change the base to `dev`. Before you merge, CI (lint, tests on Python 3.10 to 3.14, and a wheel build) must pass. Prefer squash merges, so that each change is one commit on `dev`.
- **Releases**: Tags `vX.Y.Z` on `main`. To pin a release, users run `uv tool install git+https://github.com/3hiuwoo/BibCC@vX.Y.Z`.
- **`release/X.Y`**: Branches that exist only when an older release needs a fix after a newer minor version is out. See [Fixing an older release](#fixing-an-older-release).

## Commit messages

Write commit messages in lowercase, in the form `verb: short description`. For example:

- `add: venues import command`
- `fix: keep braces in titles`
- `update: help for complete`
- `remove: unused module`
- `docs: release checklist`

## Versioning

BibCC follows [Semantic Versioning](https://semver.org/). The version lives only in [`src/bibcc/__init__.py`](src/bibcc/__init__.py), and `pyproject.toml` reads it from there. Each part of the version covers the following changes:

- **Patch** (`0.2.1`): Bug fixes and documentation fixes only.
- **Minor** (`0.3.0`): New commands, options, or fields. Before `1.0.0`, a minor version can also include breaking changes. List them in the `Changed` or `Removed` section of the changelog.
- **Major** (`1.0.0` onward): Incompatible changes to command-line options, output file names, or the venue library schema.

`__version__` on `main` is always the latest release. On `dev`, it's the next version with a `.dev0` suffix (for example, `0.4.0.dev0`), so `bibcc --version` distinguishes a development install from a release. Record every user-visible change in [`CHANGELOG.md`](CHANGELOG.md) under the top section, `## [0.4.0] - Unreleased`.

You don't change the version while you work. It changes only when you release, and when you open the next version right after. Release when a set of changes is finished and you want users to get it: a new feature, or a bug fix that users of the last release need.

## Releasing

To release a version, follow these steps. The examples release version `0.4.0`.

1. On `dev`, with CI passing, make the following changes:
   - In `src/bibcc/__init__.py`, set `__version__` to the release version (drop `.dev0`).
   - In `CHANGELOG.md`, replace `Unreleased` with today's date (`## [0.4.0] - 2026-12-01`), and point the version's link at the tag (`[0.4.0]: https://github.com/3hiuwoo/BibCC/compare/v0.3.0...v0.4.0`).
2. Commit the changes (`release: 0.4.0`), and then run `python3 .github/scripts/release.py check v0.4.0`.
3. Move `main` to the release, tag it, and push both together:

   ```bash
   git switch main && git merge --ff-only dev
   git tag -a v0.4.0 -m "BibCC 0.4.0"
   git push --atomic origin main v0.4.0
   ```

4. The [Release workflow](.github/workflows/release.yml) checks that the tag, the version, and the changelog agree, and that the tag is on `main` (or a `release/X.Y` branch). It then runs the lint and the tests, builds the wheel and sdist, and creates the GitHub release with the changelog section as the release notes. Tags such as `v0.4.0rc1` become pre-releases.
5. Open the next version on `dev`: run `git switch dev`, set `__version__ = "0.5.0.dev0"`, and add a `## [0.5.0] - Unreleased` section at the top of the changelog, with the link `[0.5.0]: https://github.com/3hiuwoo/BibCC/compare/v0.4.0...dev`. Commit the change (`update: open 0.5.0 development`), and push `dev`.

### Fixing the latest release

To release a bug fix without the unreleased work on `dev`, make a patch release from `main`. The examples release version `0.4.1`.

1. Create a branch from `main`: `git switch -c fix/TOPIC main`.
2. Fix the bug, and add a test. Then set `__version__ = "0.4.1"`, and add a dated `## [0.4.1]` section to the changelog, below `[0.5.0] - Unreleased` if you're copying it from `dev`. Commit the changes, ending with `release: 0.4.1`.
3. Release it as in steps 2 to 4 of [Releasing](#releasing), with `git merge --ff-only fix/TOPIC` on `main`.
4. Bring the fix into `dev`: run `git switch dev && git merge main`. If `__init__.py` conflicts, keep the `.dev0` version of `dev`. In the changelog, keep `[0.5.0] - Unreleased` at the top, followed by the `[0.4.1]` section. Push `dev`.

### Fixing an older release

When a fix is needed for an older minor version (for example, 0.3 after 0.4.0 is out), create `release/0.3` from the last `v0.3.*` tag. Cherry-pick the fix, set the version and changelog to `0.3.1`, commit `release: 0.3.1`, and then push the branch and the tag `v0.3.1` together with `git push --atomic origin release/0.3 v0.3.1`.

### Publishing to PyPI (optional)

The Release workflow can also publish each release to PyPI, so that users can run `uv tool install bibcc`. To turn on publishing, which you do only once, follow these steps:

1. On PyPI, add a [trusted publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/) for the project `bibcc`. Use owner `3hiuwoo`, repository `BibCC`, workflow `release.yml`, and environment `pypi`.
2. In the GitHub repository settings, create the environment `pypi`, and set the repository variable `PUBLISH_TO_PYPI` to `true`.

## Contributing a venue library

BibCC doesn't ship a venue library, but shared libraries live in [`examples/venues/`](examples/venues/). To add your library or improve an existing one, see [Contributing a library](examples/venues/README.md#contributing-a-library).
