"""Cutting the corpus by legal structure, not by blind size (ARG-053).

An article and its paragraph are the natural unit of a citation, and the citation is what turns
the assistant into a tool: «el RGPD exige X» is noise for a DPO; «art. 32.1.a» with the fragment
beside it is an answer. So a fragment is one paragraph, carrying the heading of its article as
context, and only a paragraph that is genuinely too long gets split — and then its citation says so
with a suffix, instead of pretending to be the whole paragraph.
"""

import hashlib
import re
from dataclasses import dataclass

# Long enough to hold a whole paragraph of a regulation, short enough to leave room for several
# fragments in one context window.
MAX_CHARS = 1200
_ARTICLE = re.compile(r"^Art[íi]culo\s+(\d+[a-z]*)\s*\.?\s*(.*)$", re.IGNORECASE)
_PARAGRAPH = re.compile(r"^(\d+)\.\s+(.*)$")
_LETTER = re.compile(r"^([a-z])\)\s+(.*)$")


@dataclass(frozen=True, slots=True)
class Chunk:
    """A citable piece of the corpus."""

    reference: str
    heading: str
    body: str

    @property
    def text(self) -> str:
        """What is indexed and what the model reads: the heading gives the body its meaning."""
        return f"{self.heading}\n{self.body}".strip()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(f"{self.reference}\n{self.text}".encode()).hexdigest()


def _split(body: str) -> list[str]:
    """A paragraph that does not fit, cut on word boundaries."""
    words = body.split()
    pieces: list[str] = []
    current: list[str] = []
    length = 0
    for word in words:
        if current and length + len(word) + 1 > MAX_CHARS:
            pieces.append(" ".join(current))
            current, length = [], 0
        current.append(word)
        length += len(word) + 1
    if current:
        pieces.append(" ".join(current))
    return pieces or [body]


def chunk_legal_text(text: str, norm: str) -> list[Chunk]:
    """The fragments of a legal text, in the order they appear.

    Text before the first article is dropped: a preamble is not an article, and giving it a
    citation would be inventing one. Three levels of state, and no more: the article gives the
    heading, the paragraph gives the number a letter hangs from, and `current` is simply where the
    next line of text goes.
    """
    if not norm.strip():
        raise ValueError("a fragment needs the norm it belongs to: norm is empty")
    headings: dict[str, str] = {}
    article = ""
    paragraph = ""
    current = ""
    bodies: dict[str, list[str]] = {}
    order: list[str] = []

    def open_fragment(reference: str, first_line: str) -> str:
        if reference not in bodies:
            bodies[reference] = []
            order.append(reference)
        bodies[reference].append(first_line)
        return reference

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        found = _ARTICLE.match(line)
        if found is not None:
            article, title = found[1], found[2].strip()
            headings[article] = f"Artículo {article}. {title}".rstrip(". ")
            paragraph = current = ""
            continue
        if not article:
            continue
        numbered = _PARAGRAPH.match(line)
        if numbered is not None:
            paragraph = numbered[1]
            current = open_fragment(f"{norm} art. {article}.{paragraph}", numbered[2])
            continue
        lettered = _LETTER.match(line)
        if lettered is not None and paragraph:
            current = open_fragment(f"{norm} art. {article}.{paragraph}.{lettered[1]}", lettered[2])
            continue
        if current:
            bodies[current].append(line)

    chunks: list[Chunk] = []
    for reference in order:
        body = " ".join(bodies[reference]).strip()
        if not body:
            continue
        heading = headings.get(reference.split("art. ", 1)[1].split(".", 1)[0], "")
        pieces = _split(body) if len(body) > MAX_CHARS else [body]
        if len(pieces) == 1:
            chunks.append(Chunk(reference, heading, pieces[0]))
            continue
        chunks.extend(
            Chunk(f"{reference}-{number}", heading, piece)
            for number, piece in enumerate(pieces, start=1)
        )
    return chunks
