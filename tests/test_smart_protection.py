from pathlib import Path

import pytest

from bibcc.checkers.smart_protection import (
    check_smart_protection,
    find_overbraced_compounds,
    find_unprotected_terms,
    split_overbraced_compounds,
)
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


def test_check_smart_protection_reports_clean_file(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{k, title = {{BERT} for Everyone}}\n")
    messages = []
    assert check_smart_protection(str(bib), [], log=messages.append) == []
    assert messages[-1] == "✅ No unprotected terms in 1 entries."


@pytest.mark.parametrize(
    "title,expected",
    [
        ("{CLIP-Based} Prompting", "{CLIP}-Based Prompting"),
        ("{ViT-based} and {Non-IID}", "{ViT}-based and Non-{IID}"),
        ("{SD-LoRA-Net}", "{SD-LoRA}-Net"),
        ("{GPT-4-Based} Agents", "{GPT-4}-Based Agents"),
        ("{4-Bit-LoRA}", "4-Bit-{LoRA}"),
        ("{X-Ray} Images", "{X}-Ray Images"),
        # Method names and names stay whole: every part needs braces, or none does.
        ("{SD-LoRA} {R-CNN} {GPT-4} {LLaVA-1.5} {IEEE/CVF}", None),
        ("{Navier-Stokes} and {Hamilton-Jacobi}", None),
        # Groups inside a larger group, or glued to a word, are left alone.
        ("{{CLIP-Based} Prompting}", None),
        ("Lo{RA-Based}", None),
    ],
)
def test_overbraced_compounds(title, expected):
    assert split_overbraced_compounds(title) == (title if expected is None else expected)
    assert bool(find_overbraced_compounds(title)) == (expected is not None)


def test_listed_compound_stays_whole():
    assert find_overbraced_compounds("{Transformer-XL}") == [("{Transformer-XL}", "Transformer-{XL}")]
    assert find_overbraced_compounds("{Transformer-XL}", ["transformer-xl"]) == []


def test_listed_part_does_not_keep_compound_whole():
    # Only the whole compound listed in the vocabulary stays whole; a listed
    # part doesn't, so a lab vocabulary of acronyms doesn't stop the split.
    assert find_overbraced_compounds("{CLIP-Based}", ["clip"]) == [("{CLIP-Based}", "{CLIP}-Based")]


def test_check_smart_protection_reports_overbraced_compounds(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{k, title = {{CLIP-Based} Prompting with BERT}}\n")
    messages = []
    rows = check_smart_protection(str(bib), [], log=messages.append)
    assert rows == [("k", "BERT", "Acronym"), ("k", "{CLIP-Based}", "Over-Braced: use {CLIP}-Based")]
    assert "⚠️  Found 1 terms to protect and 1 over-braced compounds to split." in messages
    hint = "\n".join(messages)
    assert ".bibcc/refs.bib/vocab.txt" in hint
    assert "--interactive" in hint


def test_each_check_runs_alone(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{k, title = {Deep BERT}, year = {2024}}\n")
    reports = tmp_path / ".bibcc" / "refs.bib"
    main(["check", "quote", str(bib)])
    assert (reports / "smart_protection.txt").exists()
    assert not (reports / "missing_fields.txt").exists()

    main(["check", "missing", str(bib)])
    assert "k\tarticle\t2024\tmonth" in (reports / "missing_fields.txt").read_text()
