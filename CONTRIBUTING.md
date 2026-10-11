# Contributing to BibCC

Thanks for helping. Bug reports, ideas, code, and venue libraries are all welcome.

## Development setup

To set up a development checkout, run the following commands:

```bash
git clone https://github.com/3hiuwoo/BibCC.git && cd BibCC
uv sync                        # .venv with BibCC (editable) and the dev tools
uv run bibcc --help            # run from the checkout
uv run pytest                  # tests (no network access; API responses are canned)
uv run ruff check .            # lint
uv tool install --editable .   # optional: `bibcc` on your PATH, following the checkout
```

The code conventions are in [`CLAUDE.md`](CLAUDE.md). In summary:

- Code lives in `src/bibcc/`.
- Tools log through a `log` callback instead of `print()`.
- Network access goes through `bibcc.sources.fetch_url`.
- Every help page has a description and examples.
- New behavior comes with tests.

Tests never use your own venue library: `tests/conftest.py` points the user library at a temporary directory for every test.

## Branches

The repository uses the following branches and tags:

- **`main`**: The development line. It must always pass CI. It's what you get from `uv tool install git+https://github.com/3hiuwoo/BibCC` without a tag.
- **Work branches**: Short-lived branches off `main`, named `feat/TOPIC`, `fix/TOPIC`, `docs/TOPIC`, or, for venue library contributions, `venues/LIBRARY`. Open a pull request to `main`. Before you merge, CI (lint, tests on Python 3.10 to 3.14, and a wheel build) must pass. Prefer squash merges, so that each change is one commit on `main`.
- **Releases**: Tags `vX.Y.Z` on `main`. To pin a release, users run `uv tool install git+https://github.com/3hiuwoo/BibCC@vX.Y.Z`.
- **`release/X.Y`**: Branches that exist only when an older release needs a fix after `main` has moved on. To fix an older release, create the branch from the last `vX.Y.*` tag, cherry-pick the fix from `main`, and tag `vX.Y.(Z+1)` on the branch.

## Commit messages

Write commit messages in lowercase, in the form `verb: short description`. For example:

- `add: venues import command`
- `fix: keep braces in titles`
- `update: help for complete`
- `remove: unused module`
- `docs: release checklist`

## Versioning

BibCC follows [Semantic Versioning](https://semver.org/). The version lives only in [`src/bibcc/__init__.py`](src/bibcc/__init__.py), and `pyproject.toml` reads it from there. Each part of the version covers the following changes:

- **Patch** (`0.2.1`): Bug fixes only.
- **Minor** (`0.3.0`): New commands, options, or fields. Before `1.0.0`, a minor version can also include breaking changes. List them in the `Changed` or `Removed` section of the changelog.
- **Major** (`1.0.0` onward): Incompatible changes to command-line options, output file names, or the venue library schema.

Between releases, `__version__` on `main` is the next version with a `.dev0` suffix (for example, `0.3.0.dev0`), so `bibcc --version` distinguishes a development install from a release. Record every user-visible change in [`CHANGELOG.md`](CHANGELOG.md) under the top section, `## [0.3.0] - Unreleased`.

## Releasing

To release a version, follow these steps. The examples release version `0.3.0`.

1. On `main`, with CI passing, make the following changes:
   - In `src/bibcc/__init__.py`, set `__version__` to the release version (drop `.dev0`).
   - In `CHANGELOG.md`, replace `Unreleased` with today's date (`## [0.3.0] - 2026-11-02`), and point the version's link at the tag (`[0.3.0]: https://github.com/3hiuwoo/BibCC/compare/v0.2.0...v0.3.0`).
2. Commit the changes (`release: 0.3.0`), and then run `python3 .github/scripts/release.py check v0.3.0`.
3. Tag the release and push it: `git tag -a v0.3.0 -m "BibCC 0.3.0" && git push origin main v0.3.0`.
4. The [Release workflow](.github/workflows/release.yml) checks that the tag, the version, and the changelog agree. It then runs the lint and the tests, builds the wheel and sdist, and creates the GitHub release with the changelog section as the release notes. Tags such as `v0.3.0rc1` become pre-releases.
5. To open the next version, set `__version__ = "0.4.0.dev0"`, and add a `## [0.4.0] - Unreleased` section at the top of the changelog.

### Publishing to PyPI (optional)

The Release workflow can also publish each release to PyPI, so that users can run `uv tool install bibcc`. To turn on publishing, which you do only once, follow these steps:

1. On PyPI, add a [trusted publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/) for the project `bibcc`. Use owner `3hiuwoo`, repository `BibCC`, workflow `release.yml`, and environment `pypi`.
2. In the GitHub repository settings, create the environment `pypi`, and set the repository variable `PUBLISH_TO_PYPI` to `true`.

## Contributing a venue library

BibCC doesn't ship a venue library, but shared libraries live in [`examples/venues/`](examples/venues/). To add your library or improve an existing one, see [Contributing a library](examples/venues/README.md#contributing-a-library).
