from pathlib import Path

from bibcc.checkers.smart_protection import check_smart_protection, find_unprotected_terms
from bibcc.cli import main


def _words(title: str, **kwargs) -> dict:
    return dict(find_unprotected_terms(title, vocab_terms=[], **kwargs))


def test_min_length_applies_to_acronyms():
    assert _words("Deep AI for ML") == {"AI": "Acronym", "ML": "Acronym"}
    assert _words("Deep AI for ML with BERT", min_length=3) == {"BERT": "Acronym"}


def test_standalone_term_kept_next_to_longer_term_containing_it():
    assert _words("BERT and RoBERTa") == {"BERT": "Acronym", "RoBERTa": "Mixed Case"}


def test_terms_with_numbers():
    assert _words("3D Splatting with 3DGS, 6DoF, Llama2, V2 and ResNet50") == {
        "3D": "Contains Number",
        "3DGS": "Contains Number",
        "6DoF": "Contains Number",
        "Llama2": "Contains Number",
        "V2": "Contains Number",
        "ResNet50": "Contains Number",
    }


def test_lowercase_and_capitalized_words_are_not_flagged():
    assert _words("Word2vec and word2vec in Part 2 of a Study") == {"Word2vec": "Contains Number"}
    assert _words("A Study of Deep Learning") == {}


def test_two_letter_mixed_case_and_roman_numerals():
    assert _words("Part II of the dB and pH Study") == {"dB": "Mixed Case", "pH": "Mixed Case"}


def test_braced_text_and_author_surnames_are_skipped():
    found = dict(find_unprotected_terms("{BERT} meets Fisher and GPT-4", author="Fisher, Ronald"))
    assert found == {"GPT": "Acronym"}


def test_check_smart_protection_uses_min_length(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{k, title = {AI for BERT}}\n")
    rows = check_smart_protection(str(bib), [], min_length=3, log=lambda _msg: None)
    assert rows == [("k", "BERT", "Acronym")]


def test_cli_checks_month_by_default(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{k, title = {T}, year = {2024}}\n")
    main(["check", str(bib)])
    report = tmp_path / ".bibcc" / "refs.bib.missing_fields.txt"
    assert "k\tarticle\t2024\tmonth" in report.read_text()

    report.unlink()
    main(["check", str(bib), "--fields", ""])
    assert not report.exists()
