## What and why

<!-- What does this change, and why? Link the issue it closes, if any. -->

## Checklist

- [ ] `uv run pytest` and `uv run ruff check .` pass
- [ ] New behaviour has tests under `tests/` (no network access; canned responses in `tests/fixtures/sources/`)
- [ ] User-visible changes are recorded in `CHANGELOG.md` under the top, unreleased version
- [ ] README and `-h` help updated if a command, option, or output file changed
- [ ] For a venue library in `examples/venues/`: written with `bibcc venues import ... --venues`, values from official sources, row added to its README
