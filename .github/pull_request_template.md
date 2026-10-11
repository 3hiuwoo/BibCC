## What and why

<!-- Describe what this pull request changes and why. If it closes an issue, link the issue. -->

## Checklist

- [ ] The pull request targets `dev`, not `main`. `main` takes only releases.
- [ ] `uv run pytest` and `uv run ruff check .` pass.
- [ ] New behavior has tests under `tests/` (no network access; canned responses in `tests/fixtures/sources/`).
- [ ] User-visible changes are recorded in `CHANGELOG.md` under the top, unreleased version.
- [ ] If a command, option, or output file changed, the README and the `-h` help are updated.
- [ ] For a venue library in `examples/venues/`: it's written with `bibcc venues import FILE --venues examples/venues/NAME.yaml`, its values come from official sources, and its row is added to the README in `examples/venues/`.
