from pathlib import Path

from bibcc.checkers.missing_fields import check_missing_fields
from bibcc.checkers.template_fields import check_template_fields

VENUES = """\
journals:
- name: Journal Complete
  fields:
    publisher: P
    issn: 1234-5678
- name: Journal Without ISSN
  fields:
    publisher: P
proceedings:
- name: European Conference on Computer Vision (ECCV)
  year: '2024'
  fields:
    venue: Milan, Italy
    publisher: Springer
    month: September
- name: Some Workshop
  year: '2023'
  fields:
    publisher: P
"""


def test_template_fields_reports_and_counts_override_fields(tmp_path: Path):
    path = tmp_path / "venues.yaml"
    path.write_text(VENUES, encoding="utf-8")
    logs = []

    check_template_fields(path, ["publisher", "issn"], ["venue", "publisher", "month"], log=logs.append)
    text = "\n".join(logs)

    assert "Journal Without ISSN" in text and "Journal Complete" not in text
    assert "1/2 journals have missing fields" in text
    assert "2/2 proceedings have missing fields" in text
    summary = text.split("Summary by field")[1]
    proceedings = summary.split("Proceedings:")[1]
    assert "issn: 1 missing" in summary
    assert "venue: 1 missing" in proceedings
    assert "month: 1 missing" in proceedings
    assert "series: 1 missing" in proceedings


def test_missing_fields_filters_types_and_blank_values(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        """\
@inproceedings{HasMonth, title={A}, year={2024}, month=jun}
@inproceedings{BlankMonth, title={B}, year={2024}, month={ }}
@article{NoMonth, title={C}, year={2023}}
@misc{IgnoredType, title={D}}
""",
        encoding="utf-8",
    )
    logs = []

    rows = check_missing_fields(str(bib), ["month", " "], ["inproceedings", "article"], log=logs.append)

    assert rows == [
        ("BlankMonth", "inproceedings", "2024", ["month"]),
        ("NoMonth", "article", "2023", ["month"]),
    ]
    assert "month: 2" in logs[-1]


def test_missing_fields_skips_when_no_fields(tmp_path: Path):
    logs = []
    assert check_missing_fields(str(tmp_path / "absent.bib"), [""], ["article"], log=logs.append) == []
    assert "skipping" in logs[0]
