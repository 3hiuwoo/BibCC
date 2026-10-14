"""Month rules: official values first, event months only within one month, and no-month records."""

from pathlib import Path

from bibcc.adder import build_entry
from bibcc.bibedit import retype_entries
from bibcc.checkers.edition_fields import check_edition_fields
from bibcc.checkers.field_issues import CONFERENCE_ARTICLE, check_field_issues
from bibcc.checkers.missing_fields import check_missing_fields
from bibcc.completer import main as complete_main
from bibcc.crosscheck import check_entry
from bibcc.official import Official, clean_official, official_fields
from bibcc.sources import Record, record_from_crossref
from bibcc.venues import JOURNAL, NO_MONTH, PROCEEDINGS, Venue, VenueLibrary, is_conference_journal

COLLAS = """@InProceedings{pmlr-v274-doe25a,
  title = {A Paper},
  author = {Doe, Jane},
  booktitle = {Proceedings of The 3rd Conference on Lifelong Learning Agents},
  pages = {1--20},
  year = {2025},
  volume = {274},
  series = {Proceedings of Machine Learning Research},
  month = {29 Jul--01 Aug},
  publisher = {PMLR}
}
"""

AAAI = """@article{Doe_2024,
  title = {A Paper},
  volume = {38},
  number = {5},
  journal = {Proceedings of the AAAI Conference on Artificial Intelligence},
  author = {Doe, Jane},
  year = {2024},
  month = {Mar.},
  pages = {1-9}
}
"""

IJCV = """@Article{Doe2026,
  author = {Doe, Jane},
  title = {A Paper},
  journal = {International Journal of Computer Vision},
  year = {2026},
  month = {Sep},
  day = {28},
  volume = {134},
  number = {10},
  pages = {454}
}
"""


def test_is_conference_journal():
    assert is_conference_journal("Proceedings of the AAAI Conference on Artificial Intelligence")
    assert is_conference_journal("Proceedings of the ACM on Web Conference 2025")
    assert not is_conference_journal("Proceedings of the National Academy of Sciences")
    assert not is_conference_journal("Proceedings of the IEEE")
    assert not is_conference_journal("Proceedings of the ACM on Human-Computer Interaction")
    assert not is_conference_journal("International Journal of Computer Vision")


def test_official_period_across_two_months_is_dropped_and_reported():
    cleaned = clean_official(COLLAS)
    assert "month" not in cleaned.fields and "day" not in cleaned.fields
    assert cleaned.dropped_period == "29 Jul--01 Aug"
    assert any("period across two months" in note for note in cleaned.notes())


def test_official_period_within_one_month_is_split():
    _, fields = official_fields(COLLAS.replace("29 Jul--01 Aug", "21--27 Jul"))
    assert fields["month"] == "Jul" and fields["day"] == "21--27"


def test_official_journal_month_and_day_are_kept():
    entry_type, fields = official_fields(IJCV)
    assert entry_type == "article"
    assert fields["month"] == "Sep" and fields["day"] == "28"


def test_official_aaai_article_becomes_inproceedings_with_its_issue_month():
    cleaned = clean_official(AAAI)
    assert cleaned.entry_type == "inproceedings"
    assert cleaned.retyped_from == "article"
    assert cleaned.fields["booktitle"] == "Proceedings of the AAAI Conference on Artificial Intelligence"
    assert "journal" not in cleaned.fields
    assert cleaned.fields["month"] == "Mar."  # official, so kept
    assert any("@article" in note for note in cleaned.notes())


def test_build_entry_does_not_add_the_library_month_after_dropping_a_period():
    library = VenueLibrary(proceedings=[Venue(
        PROCEEDINGS, "Proceedings of The 3rd Conference on Lifelong Learning Agents",
        {"venue": "Pisa, Italy", "month": "July"}, year="2025")])
    built = build_entry(Official("PMLR", "", COLLAS), library)
    assert "month" not in built.fields
    assert built.fields["venue"] == "Pisa, Italy"
    assert any("period across two months" in note for note in built.notes)
    assert any(f"'{NO_MONTH}'" in note for note in built.notes)


def test_retype_entries_keeps_alignment_and_values():
    text = AAAI.replace("title = ", "title   = ").replace("volume = ", "volume  = ")
    aligned = (
        "@article{K,\n"
        "  title   = {A},\n"
        "  journal = {Proceedings of the AAAI Conference on Artificial Intelligence},\n"
        "  year    = {2024}\n"
        "}\n"
    )
    new = retype_entries(aligned, {"K": ("inproceedings", {"journal": "booktitle"})})
    assert new == (
        "@inproceedings{K,\n"
        "  title     = {A},\n"
        "  booktitle = {Proceedings of the AAAI Conference on Artificial Intelligence},\n"
        "  year      = {2024}\n"
        "}\n"
    )
    assert retype_entries(text, {}) == text


def _no_month_library() -> VenueLibrary:
    return VenueLibrary(
        journals=[Venue(JOURNAL, "Transactions on Machine Learning Research", {"month": NO_MONTH})],
        proceedings=[
            Venue(PROCEEDINGS, "Proceedings of the AAAI Conference on Artificial Intelligence",
                  {"venue": "Philadelphia, PA, USA", "month": NO_MONTH}, year="2025"),
            Venue(PROCEEDINGS, "Advances in Neural Information Processing Systems",
                  {"month": NO_MONTH}, year="2022"),
        ],
    )


def test_complete_retypes_aaai_and_never_adds_a_no_month(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text(AAAI.replace("year = {2024}", "year = {2025}").replace("  month = {Mar.},\n", "")
                   + "@inproceedings{N,\n  title = {T},\n"
                   "  booktitle = {Advances in Neural Information Processing Systems},\n"
                   "  year = {2022},\n  month = nov\n}\n")
    logs = []
    complete_main(str(bib), str(bib), library=_no_month_library(), log=logs.append)
    text = bib.read_text()
    assert text.startswith("@inproceedings{Doe_2024,")
    assert "booktitle = {Proceedings of the AAAI Conference" in text
    assert "venue = {Philadelphia, PA, USA}" in text
    assert "none" not in text
    assert "month = nov" in text  # reported, never removed without --resolve library
    conflicts = (tmp_path / ".bibcc" / "refs.bib" / "conflicts.txt").read_text()
    assert f"N\tmonth\tEXISTING=November\tLIBRARY={NO_MONTH}" in conflicts
    assert any("now @inproceedings" in line for line in logs)


def test_complete_resolve_library_removes_the_month_of_a_no_month_venue(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text("@inproceedings{N,\n  title = {T},\n"
                   "  booktitle = {Advances in Neural Information Processing Systems},\n"
                   "  year = {2022},\n  month = nov,\n  day = {28}\n}\n")
    complete_main(str(bib), str(bib), library=_no_month_library(), resolve="library", log=lambda _: None)
    text = bib.read_text()
    assert "month" not in text and "day" not in text


def test_check_missing_skips_no_month_venues(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{T, title = {T}, journal = {Transactions on Machine Learning Research}, year = {2024}}\n"
        "@article{P, title = {P}, journal = {Pattern Recognition}, year = {2024}}\n"
    )
    logs = []
    rows = check_missing_fields(str(bib), ["month"], ["article"], log=logs.append, library=_no_month_library())
    assert [r[0] for r in rows] == ["P"]
    assert any("T" in line and "has none" in line for line in logs)
    assert [r[0] for r in check_missing_fields(str(bib), ["month"], ["article"], log=lambda _: None)] == ["T", "P"]


def test_check_editions_skips_month_of_a_no_month_edition(tmp_path: Path):
    entries = "".join(
        f"@inproceedings{{N{y}{i}, title = {{T}}, booktitle = {{Advances in Neural Information Processing "
        f"Systems}}, year = {{{y}}}{', month = dec' if y != 2022 else ''}}}\n"
        for y in (2021, 2022, 2023, 2024) for i in range(3)
    )
    bib = tmp_path / "refs.bib"
    bib.write_text(entries)
    rows = check_edition_fields(str(bib), library=_no_month_library(), log=lambda _: None)
    assert not [r for r in rows if r[3] == "month"]
    assert [r for r in check_edition_fields(str(bib), log=lambda _: None) if r[3] == "month"]


def test_check_fields_reports_conference_articles(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text(AAAI + "@article{PNAS, title = {T}, journal = {Proceedings of the National Academy of "
                          "Sciences}, year = {2024}}\n")
    rows = check_field_issues(str(bib), log=lambda _: None)
    assert [(r[0], r[1]) for r in rows if r[1] == CONFERENCE_ARTICLE] == [("Doe_2024", CONFERENCE_ARTICLE)]


def test_crossref_event_month_only_within_one_month():
    msg = {
        "type": "proceedings-article", "title": ["T"], "container-title": ["Some Conference"],
        "event": {"start": {"date-parts": [[2022, 11, 28]]}, "end": {"date-parts": [[2022, 12, 9]]}},
        "published-print": {"date-parts": [[2023, 4]]},
    }
    record = record_from_crossref(msg)
    assert "event_month" not in record.extra
    assert "month" not in record.fields  # the proceedings' publication month isn't the event month
    msg["event"]["end"] = {"date-parts": [[2022, 11, 30]]}
    assert record_from_crossref(msg).extra["event_month"] == "11"


def test_crossref_article_month_is_the_issue_month():
    msg = {
        "type": "journal-article", "title": ["T"], "container-title": ["Pattern Recognition"],
        "published-online": {"date-parts": [[2025, 9, 28]]},
        "issued": {"date-parts": [[2025, 9, 28]]},
        "journal-issue": {"issue": "10", "published-print": {"date-parts": [[2025, 10]]}},
    }
    assert record_from_crossref(msg).fields["month"] == "10"
    del msg["journal-issue"]
    assert "month" not in record_from_crossref(msg).fields  # only the online date: no month
    pnas = dict(msg, **{"container-title": ["Proceedings of the National Academy of Sciences"]})
    assert record_from_crossref(pnas).entry_type == "article"


def test_crosscheck_ignores_a_no_month_record():
    venue = Venue(JOURNAL, "Transactions on Machine Learning Research", {"month": NO_MONTH})
    record = Record(entry_type="article", fields={"month": "10"}, source="CrossRef")
    checks = check_entry("K", {"journal": "Transactions on Machine Learning Research"}, JOURNAL, venue, record)
    assert not [c for c in checks if c.name == "month"]
