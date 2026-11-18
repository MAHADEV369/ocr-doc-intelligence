"""Shared text normalisation for extraction and benchmarking.

The goal is to compare content, not formatting: Markdown markers, ligatures,
soft hyphens, smart quotes and line-wrap hyphens should not look like OCR
errors.
"""
from __future__ import annotations

import re
import unicodedata


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def dehyphenate(text: str) -> str:
    """Join words broken across lines: 'manage-\\nment' -> 'management'."""
    t = re.sub(r"(?<=[A-Za-z])[-\u2010\u2011]\s*\n\s*(?=[a-z])", "", text or "")
    return t


def strip_markdown(text: str) -> str:
    t = text or ""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", t)
    t = re.sub(r"(?m)^\s*[-*_]{3,}\s*$", "", t)
    t = re.sub(r"[*_`]{1,3}", "", t)
    t = re.sub(r"\|", " ", t)
    t = re.sub(r"(?m)^\s*[-: ]+\s*$", "", t)
    return t


def clean_text(text: str, markdown: bool = False) -> str:
    t = nfkc(text)
    if markdown:
        t = strip_markdown(t)
    t = t.replace("\u00ad", "").replace("\ufb01", "fi").replace("\ufb02", "fl")
    t = t.replace("\u00a0", " ").replace("\u2019", "'").replace("\u2018", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = t.replace("\u2013", "-").replace("\u2014", "-")
    t = dehyphenate(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def normalise_line(line: str) -> str:
    return re.sub(r"\s+", " ", clean_text(line)).strip().lower()
