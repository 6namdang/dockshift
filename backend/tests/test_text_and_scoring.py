from __future__ import annotations

from app.literature.models import Document, Source
from app.literature.scoring import query_terms, score_documents, tokenize
from app.literature.text import clean_html, jats_to_text, truncate
from tests.fixtures.payloads import JATS_XML


def doc(title: str, abstract: str | None = None) -> Document:
    return Document(
        id=f"pubmed:{abs(hash(title))}", source=Source.PUBMED, title=title, abstract=abstract
    )


# ---------------------------------------------------------------- text
def test_clean_html_strips_tags_entities_and_whitespace():
    assert clean_html("<h4>Abstract</h4>  A &amp; B\n\n<i>c</i>") == "Abstract A & B c"
    assert clean_html("") is None
    assert clean_html("<p> </p>") is None


def test_jats_to_text_keeps_sections_and_drops_noise():
    text = jats_to_text(JATS_XML)
    assert text.startswith("Docking KRAS G12C")
    assert "ABSTRACT\nShort abstract." in text
    assert "## Introduction" in text and "### Background" in text
    assert "KRAS is an oncogene [1]." in text
    assert "[fig caption] Docking poses." in text
    assert "E = mc^2" not in text  # formulas dropped
    assert "Ref one." not in text  # reference list dropped


def test_truncate():
    assert truncate("short", 100) == ("short", False)
    text, cut = truncate("word " * 100, 50)
    assert cut and len(text) <= 50 + len(" …[truncated]") and text.endswith("…[truncated]")


# ------------------------------------------------------------- scoring
def test_query_terms_drop_stopwords_tags_and_fold_plurals():
    assert query_terms("Kinases AND docking[tiab] of the inhibitors") == [
        "kinase",
        "docking",
        "inhibitor",
    ]
    assert tokenize("analysis class") == ["class"]  # 'analysis' is a stopword, 'ss' kept


def test_scores_are_bounded_and_rank_full_matches_first():
    docs = [
        doc("Bananas", "Nothing relevant here."),
        doc("Docking of kinase inhibitors", "We study kinase inhibitors by docking."),
        doc("Kinase biology", "A review of kinase signalling."),
    ]
    score_documents("kinase inhibitor docking", docs)
    scores = {d.title: d.confidence for d in docs}
    assert all(0.0 <= s <= 1.0 for s in scores.values())
    assert scores["Docking of kinase inhibitors"] > scores["Kinase biology"] > scores["Bananas"]
    assert scores["Bananas"] == 0.0


def test_phrase_match_beats_scattered_terms():
    adjacent = doc("Covalent inhibitor", "covalent inhibitor of KRAS")
    scattered = doc("Covalent chemistry", "an inhibitor of KRAS that is covalent")
    score_documents("covalent inhibitor KRAS", [adjacent, scattered])
    assert adjacent.confidence > scattered.confidence


def test_query_with_only_stopwords_scores_zero():
    docs = [doc("Anything", "at all")]
    score_documents("the of and", docs)
    assert docs[0].confidence == 0.0
