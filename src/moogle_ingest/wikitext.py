from __future__ import annotations

import html
import re


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _render_templates(text: str) -> str:
    text = re.sub(r"\{\{\s*[^{}]+\s*\}\}", lambda m: m.group(0).replace("{{", "[").replace("}}", "]"), text)
    text = re.sub(r"\{\{\s*([^|{}]+)\|([^{}]+)\}\}", r"\1: \2", text)
    return text


def _render_links(text: str) -> str:
    text = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"[\2](https://www.bg-wiki.com/ffxi/\1)", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"[\1](https://www.bg-wiki.com/ffxi/\1)", text)
    text = re.sub(r"\[https?://([^\]]+)\s+([^\]]+)\]", r"[\2](https://\1)", text)
    return text


def _render_headings(text: str) -> str:
    text = re.sub(r"^==\s*(.+?)\s*==\s*$", r"## \1", text, flags=re.MULTILINE)
    text = re.sub(r"^=\s*(.+?)\s*=\s*$", r"# \1", text, flags=re.MULTILINE)
    return text


def _render_lists(text: str) -> str:
    text = re.sub(r"^\*\s*(.+)$", r"- \1", text, flags=re.MULTILINE)
    text = re.sub(r"^#\s*(.+)$", r"1. \1", text, flags=re.MULTILINE)
    return text


def _render_bold_italics(text: str) -> str:
    text = re.sub(r"'''([^']+?)'''", r"**\1**", text)
    text = re.sub(r"''([^']+?)''", r"*\1*", text)
    return text


def _render_tables(text: str) -> str:
    text = re.sub(r"\{\|\s*class=\"wikitable\"\s*\|\s*(.*?)\|\}\s*", lambda m: "\n\n| " + m.group(1).replace("!", "|") + " |\n\n", text, flags=re.DOTALL)
    return text


def _decode_entities(text: str) -> str:
    return html.unescape(text)


def wikitext_to_markdown(wikitext: str) -> str:
    text = _decode_entities(wikitext)
    text = _strip_comments(text)
    text = _render_templates(text)
    text = _render_links(text)
    text = _render_headings(text)
    text = _render_lists(text)
    text = _render_bold_italics(text)
    text = _render_tables(text)
    text = re.sub(r"\n{2,}", "\n\n", text)
    text = _normalize_whitespace(text)
    return text
