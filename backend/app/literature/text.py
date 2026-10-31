"""Text utilities: HTML stripping and JATS/PubMed XML text extraction."""

from __future__ import annotations

import html
import re
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET

_TAG_RE = re.compile(r"<[^>]+>")
_ALL_WS_RE = re.compile(r"\s+")
_BLANKLINES_RE = re.compile(r"\n{3,}")


def clean_html(text: str | None) -> str | None:
    """Strip HTML tags/entities and collapse whitespace. Returns None for empty input."""
    if not text:
        return None
    text = html.unescape(_TAG_RE.sub(" ", text))
    text = _ALL_WS_RE.sub(" ", text).strip()
    return text or None


def element_text(el: Element | None) -> str:
    """All text inside an element (including children), whitespace-collapsed."""
    if el is None:
        return ""
    return _ALL_WS_RE.sub(" ", "".join(el.itertext())).strip()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


# JATS elements that are noise for an LLM reading the paper.
_JATS_SKIP = {"xref", "table-wrap-foot", "inline-formula", "disp-formula", "math"}


def jats_to_text(xml_text: str) -> str:
    """Convert a JATS article (Europe PMC fullTextXML) into readable plain text.

    Keeps title, abstract, section headings and paragraphs; drops references,
    formulas and other markup noise.
    """
    root = SafeET.fromstring(xml_text)
    parts: list[str] = []

    title = next((el for el in root.iter() if _local(el.tag) == "article-title"), None)
    if title is not None:
        parts.append(element_text(title))

    abstract = next((el for el in root.iter() if _local(el.tag) == "abstract"), None)
    if abstract is not None:
        parts.append("ABSTRACT\n" + element_text(abstract))

    body = next((el for el in root.iter() if _local(el.tag) == "body"), None)
    if body is not None:
        _walk_body(body, parts, depth=0)

    text = "\n\n".join(p for p in parts if p)
    return _BLANKLINES_RE.sub("\n\n", text).strip()


def _walk_body(el: Element, parts: list[str], depth: int) -> None:
    for child in el:
        name = _local(child.tag)
        if name in _JATS_SKIP:
            continue
        if name == "sec":
            heading = next((c for c in child if _local(c.tag) == "title"), None)
            if heading is not None:
                parts.append("#" * min(depth + 2, 4) + " " + element_text(heading))
            _walk_body(child, parts, depth + 1)
        elif name == "p":
            parts.append(element_text(child))
        elif name in {"fig", "table-wrap"}:
            caption = next((c for c in child if _local(c.tag) == "caption"), None)
            if caption is not None:
                parts.append(f"[{name.replace('-wrap', '')} caption] " + element_text(caption))
        elif name in {"list", "boxed-text", "disp-quote"}:
            parts.append(element_text(child))
        elif name == "title":
            continue  # handled by the parent <sec>
        else:
            _walk_body(child, parts, depth)


def truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    cut = text.rfind(" ", 0, max_chars)
    return text[: cut if cut > max_chars * 0.8 else max_chars] + " …[truncated]", True
