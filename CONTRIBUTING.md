# Contributing to BibCC

Thanks for helping. Bug reports, ideas, code, and venue libraries are all welcome.

## Development Setup

```bash
git clone https://github.com/3hiuwoo/BibCC.git && cd BibCC
uv sync                        # .venv with BibCC (editable) and the dev tools
uv run bibcc --help            # run from the checkout
uv run pytest                  # tests (no network access; API responses are canned)
uv run ruff check .            # lint
uv tool install --editable .   # optional: `bibcc` on your PATH, following the checkout
```

Code conventions are in [`CLAUDE.md`](CLAUDE.md). In short: code lives in `src/bibcc/`, tools log through a `log` callback instead of `print()`, network access goes through `bibcc.sources.fetch_url`, every help page has a description and examples, and new behaviour comes with tests.

Tests never use your own venue library: `tests/conftest.py` points the user library at a temporary folder for every test.

## Branches

- **`main`** is the development line. It must always pass CI, and it is what you get from `uv tool install git+https://github.com/3hiuwoo/BibCC` without a tag.
- **Work branches** are short-lived and branch off `main`: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`, or `venues/<library>` for venue library contributions. Open a pull request to `main`. CI (lint, tests on Python 3.10 to 3.14, and a wheel build) must pass before merging. Prefer squash merges, so that each change is one commit on `main`.
- **Releases** are tags `vX.Y.Z` on `main`. Users pin one with `uv tool install git+https://github.com/3hiuwoo/BibCC@vX.Y.Z`.
- **`release/X.Y`** branches exist only when an older release needs a fix after `main` has moved on. Create the branch from the last `vX.Y.*` tag, cherry-pick the fix from `main`, and tag `vX.Y.(Z+1)` on the branch.

## Commit Messages

Commit messages are lowercase `verb: short description`, for example `add: venues import command`, `fix: keep braces in titles`, `update: help for complete`, `remove: unused module`, `docs: release checklist`.

## Versioning

BibCC follows [Semantic Versioning](https://semver.org/). The version lives only in [`src/bibcc/__init__.py`](src/bibcc/__init__.py), and `pyproject.toml` reads it from there.

- **Patch** (`0.2.1`): bug fixes only.
- **Minor** (`0.3.0`): new commands, options, or fields. Before 1.0, a minor version may also break things. Say so under **Changed** or **Removed** in the changelog.
- **Major** (`1.0.0` onwards): incompatible changes to command-line options, output file names, or the venue library schema.

Between releases, `__version__` on `main` is the next version with a `.dev0` suffix (for example `0.3.0.dev0`), so `bibcc --version` tells a development install from a release. Every user-visible change is recorded in [`CHANGELOG.md`](CHANGELOG.md) under the top section, `## [0.3.0] - Unreleased`.

## Releasing

1. On `main`, with CI green:
   - Set `__version__` in `src/bibcc/__init__.py` to the release version (drop `.dev0`).
   - In `CHANGELOG.md`, replace `Unreleased` with today's date (`## [0.3.0] - 2026-11-02`). Point the version's link at the tag (`[0.3.0]: https://github.com/3hiuwoo/BibCC/compare/v0.2.0...v0.3.0`).
2. Commit (`release: 0.3.0`), then run `python3 .github/scripts/release.py check v0.3.0`.
3. Tag and push: `git tag -a v0.3.0 -m "BibCC 0.3.0" && git push origin main v0.3.0`.
4. The [Release workflow](.github/workflows/release.yml) checks that the tag, the version, and the changelog agree. It then runs the lint and the tests, builds the wheel and sdist, and creates the GitHub release with the changelog section as notes. Tags such as `v0.3.0rc1` become pre-releases.
5. Open the next version: set `__version__ = "0.4.0.dev0"` and add a `## [0.4.0] - Unreleased` section at the top of the changelog.

### Publishing to PyPI (optional)

The workflow can also publish each release to PyPI, so users can run `uv tool install bibcc`. To switch it on once:

1. On PyPI, add a [trusted publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/) for the project `bibcc`. Use owner `3hiuwoo`, repository `BibCC`, workflow `release.yml`, and environment `pypi`.
2. In the GitHub repository settings, create the environment `pypi`, and set the repository variable `PUBLISH_TO_PYPI` to `true`.

## Contributing a Venue Library

BibCC ships no venue library, but shared ones live in [`examples/venues/`](examples/venues/). See its [README](examples/venues/README.md) for how to add yours or improve one.
