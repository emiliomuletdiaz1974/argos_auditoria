"""ARG-053 · the corpus is cut by legal structure, not by blind size (F06-06).

An article and its paragraph are the natural unit of a citation. Cutting every 500 characters
would give fragments that no DPO can quote, and a citation that cannot be quoted is not a citation.
"""

import pytest
from argos_ai.rag.chunking import MAX_CHARS, Chunk, chunk_legal_text

TEXT = """Artículo 32. Seguridad del tratamiento
1. Teniendo en cuenta el estado de la técnica, el responsable aplicará medidas técnicas
apropiadas, entre otras:
a) la seudonimización y el cifrado de datos personales;
b) la capacidad de garantizar la confidencialidad permanente.
2. Al evaluar la adecuación del nivel de seguridad se tendrán particularmente en cuenta los
riesgos que presente el tratamiento.

Artículo 33. Notificación de una violación de la seguridad
1. El responsable la notificará a la autoridad de control sin dilación indebida y, de ser
posible, a más tardar 72 horas después de que haya tenido constancia de ella.
5. El responsable documentará cualquier violación de la seguridad de los datos personales.
"""


def _by_reference(text: str = TEXT) -> dict[str, Chunk]:
    return {chunk.reference: chunk for chunk in chunk_legal_text(text, norm="RGPD")}


def test_each_paragraph_is_one_fragment_with_its_own_citation() -> None:
    chunks = _by_reference()
    assert set(chunks) == {
        "RGPD art. 32.1",
        "RGPD art. 32.1.a",
        "RGPD art. 32.1.b",
        "RGPD art. 32.2",
        "RGPD art. 33.1",
        "RGPD art. 33.5",
    }


def test_a_fragment_carries_the_heading_of_its_article_as_context() -> None:
    """Alone, «a) la seudonimización» says nothing: the model needs to know what it is about."""
    chunk = _by_reference()["RGPD art. 32.1.a"]
    assert "Artículo 32" in chunk.text and "Seguridad del tratamiento" in chunk.text
    assert "seudonimización" in chunk.text


def test_the_numbering_does_not_have_to_be_consecutive() -> None:
    """Article 33 jumps from 1 to 5, as the real one does; inventing a 2 would be worse."""
    assert "RGPD art. 33.5" in _by_reference()
    assert "RGPD art. 33.2" not in _by_reference()


def test_a_very_long_paragraph_is_split_and_its_citation_says_so() -> None:
    long_text = "Artículo 5. Principios\n1. " + ("palabra " * (MAX_CHARS // 4))
    references = [chunk.reference for chunk in chunk_legal_text(long_text, norm="RGPD")]
    assert references == ["RGPD art. 5.1-1", "RGPD art. 5.1-2"]


def test_a_paragraph_that_fits_is_never_given_a_suffix() -> None:
    assert all("-" not in chunk.reference for chunk in chunk_legal_text(TEXT, norm="RGPD"))


def test_the_same_text_always_gives_the_same_fragments_and_hashes() -> None:
    first = chunk_legal_text(TEXT, norm="RGPD")
    second = chunk_legal_text(TEXT, norm="RGPD")
    assert [c.reference for c in first] == [c.reference for c in second]
    assert [c.sha256 for c in first] == [c.sha256 for c in second]


def test_two_fragments_of_the_same_text_never_share_a_hash() -> None:
    chunks = chunk_legal_text(TEXT, norm="RGPD")
    assert len({chunk.sha256 for chunk in chunks}) == len(chunks)


def test_text_before_the_first_article_is_not_invented_into_one() -> None:
    """A preamble is not an article, and giving it a citation would be inventing one."""
    assert chunk_legal_text("Exposición de motivos sin artículos.", norm="RGPD") == []


def test_a_norm_without_a_name_is_an_error() -> None:
    with pytest.raises(ValueError, match="norm"):
        chunk_legal_text(TEXT, norm="")


def test_a_letter_that_spans_several_lines_keeps_its_tail() -> None:
    """The continuation of a letter belongs to the letter, not back to its paragraph."""
    text = (
        "Artículo 9. Categorías especiales\n"
        "2. El apartado 1 no será de aplicación cuando concurra:\n"
        "a) el interesado dio su consentimiento explícito\n"
        "para uno o más de los fines especificados;\n"
        "b) el tratamiento es necesario para la medicina preventiva.\n"
    )
    chunks = {chunk.reference: chunk for chunk in chunk_legal_text(text, norm="RGPD")}
    assert "para uno o más de los fines especificados" in chunks["RGPD art. 9.2.a"].body
    assert "para uno o más de los fines" not in chunks["RGPD art. 9.2"].body
