from pathlib import Path

import pytest

from bibcc.bibedit import (
    BibEditError,
    read_bib,
    replace_entry,
    scan,
    set_fields,
    unified_diff,
    write_bib,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _sample() -> str:
    return read_bib(FIXTURES / "sample.bib")


def test_scan_finds_entries_with_multiline_headers_and_values():
    entries = scan(_sample())
    assert [e.key for e in entries] == [
        "ISPC_Wang_CVPR2024",
        "DualPrompt_Wang_TPAMI2024",
        "PANDA_Raghavan_arXiv2025",
    ]
    dual = entries[1]
    assert set(dual.fields) == {"title", "author", "journal", "year", "month"}
    title = dual.fields["title"]
    assert "\n" in _sample()[title.value_start : title.value_end]


def test_scan_skips_comment_string_and_preamble_and_percent_lines():
    text = (
        "@string{cvpr = {CVPR}}\n"
        "@comment{ @article{fake, title={x}} }\n"
        "@preamble{ \"\\newcommand{\\x}{y}\" }\n"
        "% @article{commented, title = {no}}\n"
        "@misc(paren_key, title = \"A {B} c\", note = cvpr # { 2024 })\n"
    )
    entries = scan(text)
    assert [e.key for e in entries] == ["paren_key"]
    assert set(entries[0].fields) == {"title", "note"}


def test_scan_reports_unbalanced_braces_with_line():
    with pytest.raises(BibEditError, match="unbalanced braces starting at line 2"):
        scan("@misc{a,\n  title = {{oops}\n")


def test_insert_follows_alignment_and_keeps_everything_else():
    text = _sample()
    new, applied = set_fields(text, {"ISPC_Wang_CVPR2024": {"month": "June", "publisher": "IEEE"}})
    assert [a.action for a in applied] == ["added", "added"]
    assert "  citation  = {17},\n  month     = {June},\n  publisher = {IEEE}\n}" in new
    # Only insertions: removing them restores the original exactly.
    assert new.replace(",\n  month     = {June},\n  publisher = {IEEE}", "", 1) == text


def test_insert_with_trailing_comma_and_unaligned_fields():
    text = "@article{k,\n    title = {T},\n    year = {2024},\n}\n"
    new, _ = set_fields(text, {"k": {"issn": "1234-5678"}})
    assert new == "@article{k,\n    title = {T},\n    year = {2024},\n    issn = {1234-5678},\n}\n"


def test_edit_that_bibtexparser_would_read_differently_is_refused():
    # bibtexparser ignores field-less entries, so adding a field changes what it sees.
    with pytest.raises(BibEditError, match="same entries"):
        set_fields("@misc{k}\n", {"k": {"note": "x"}})


def test_replace_multiline_title_only_touches_that_value():
    text = _sample()
    new, applied = set_fields(
        text, {"DualPrompt_Wang_TPAMI2024": {"title": "A Study of Prompts for Continual Learning"}}
    )
    assert applied[0].action == "replaced"
    assert "title   = {A Study of Prompts for Continual Learning}," in new
    assert "             for continual learning}" not in new
    assert new.count("\n") == text.count("\n") - 1


def test_replace_false_leaves_existing_fields():
    text = _sample()
    new, applied = set_fields(text, {"ISPC_Wang_CVPR2024": {"year": "1999"}}, replace=False)
    assert new == text and applied == []


def test_crlf_is_preserved(tmp_path: Path):
    path = tmp_path / "crlf.bib"
    path.write_bytes(b"@misc{k,\r\n  title = {T}\r\n}\r\n")
    new, _ = set_fields(read_bib(path), {"k": {"year": "2024"}})
    write_bib(path, new)
    assert path.read_bytes() == b"@misc{k,\r\n  title = {T},\r\n  year = {2024}\r\n}\r\n"


def test_unknown_or_duplicate_keys_are_rejected():
    with pytest.raises(BibEditError, match="no entry"):
        set_fields(_sample(), {"Nope": {"a": "b"}})
    dup = "@misc{k, title={a}}\n@misc{k, title={b}}\n"
    with pytest.raises(BibEditError, match="appears 2 times"):
        set_fields(dup, {"k": {"note": "x"}})


def test_unbalanced_value_is_rejected():
    with pytest.raises(BibEditError, match="unbalanced"):
        set_fields(_sample(), {"ISPC_Wang_CVPR2024": {"note": "a}b{"}})


def test_replace_entry_keeps_neighbours():
    text = _sample()
    new_entry = "@inproceedings{PANDA_Raghavan_arXiv2025,\n  title = {PANDA},\n  year = {2026}\n}"
    new = replace_entry(text, "PANDA_Raghavan_arXiv2025", new_entry)
    assert new.startswith(text[: text.index("@misc{PANDA")])
    assert new_entry in new
    assert "% TODO: switch to official bibtex" in new


def test_replace_entry_must_keep_key():
    with pytest.raises(BibEditError, match="same key"):
        replace_entry(_sample(), "PANDA_Raghavan_arXiv2025", "@misc{Other, title={x}}")


def test_unified_diff_shows_change():
    text = _sample()
    new, _ = set_fields(text, {"ISPC_Wang_CVPR2024": {"month": "June"}})
    diff = unified_diff(text, new, "sample.bib")
    assert "+  month     = {June}" in diff
