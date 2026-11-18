"""Unit detection and canonicalisation for financial values.

Every extracted monetary value is stored in one canonical unit: INR crore.
The original unit and the scale factor are kept separately so a reader can
always recover the number that was printed in the source document.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CANONICAL_UNIT = "INR crore"

# Order matters: "million" must be checked before "crore" defaults, and
# "billion" before "million" (they do not overlap, but explicit ordering keeps
# the intent obvious).
_UNIT_PATTERNS: tuple[tuple[str, float, str], ...] = (
    (r"\bbillions?\b|\bbn\b", 100.0, "INR billion"),
    (r"\bmillions?\b|\bmn\b", 0.1, "INR million"),
    (r"\blakhs?\b|\blacs?\b", 0.01, "INR lakh"),
    (r"\bthousands?\b|'?000s\b|\b000s\b", 0.0001, "INR thousand"),
    (r"\bcrores?\b|\bcr\b", 1.0, "INR crore"),
)

_MONETARY_HINT = re.compile(
    r"₹|\binr\b|\brs\.?\b|\brupees?\b|\bamounts?\b|\bfigures?\b|\bexcept\b|"
    r"\bper\b|\bin\b|\b'?000s\b|\b000s\b",
    re.I,
)


@dataclass(frozen=True)
class UnitInfo:
    """How to turn a printed number into the canonical unit."""

    multiplier: float = 1.0
    source_unit: str = "INR crore"
    canonical_unit: str = CANONICAL_UNIT

    def to_canonical(self, value: float) -> float:
        return round(value * self.multiplier, 6)

    @property
    def is_canonical(self) -> bool:
        return abs(self.multiplier - 1.0) < 1e-12 and self.source_unit == CANONICAL_UNIT


def normalise_unit_text(text: str) -> str:
    """Lower-case and normalise currency markers without corrupting words."""
    t = (text or "").lower()
    # Do not replace the letter "h": that turns "thousand" into "t₹ousand"
    # and "lakh" into "lak₹". Only replace standalone currency markers.
    t = re.sub(r"₹|`|\brs\.?\b|\brupee(?:s)?\b", " inr ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def detect_unit(text: str) -> UnitInfo:
    """Return the unit described by a statement header.

    Defaults to INR crore when no monetary unit can be identified. The caller
    should only pass header lines, not arbitrary narrative text.
    """
    t = normalise_unit_text(text)
    if not t:
        return UnitInfo()
    for pattern, multiplier, source_unit in _UNIT_PATTERNS:
        if re.search(pattern, t, re.I):
            return UnitInfo(multiplier=multiplier, source_unit=source_unit)
    return UnitInfo()


def is_unit_header(line: str) -> bool:
    """True when a line looks like an amount/unit header rather than a number."""
    t = normalise_unit_text(line)
    if len(t) > 140:
        return False
    if not _MONETARY_HINT.search(t):
        return False
    return bool(re.search(
        r"\b(crore|crores|million|billion|lakh|lakhs|thousand|'?000s|000s|inr)\b",
        t,
        re.I,
    ))
