"""Numista lists special editions of one emission as separate types; recognise them."""

import re

_COLOURED = re.compile(
    r";\s*(multi)?colou?red\b[^)]*|;\s*blue and yellow colou?red|;\s*blue flag|"
    r";\s*[a-z ]*(yellow|red|blue) star[^)]*",
    re.IGNORECASE,
)
_HOLOGRAM = re.compile(r"\s*[-;]\s*hologram version", re.IGNORECASE)
_CLASSIC = re.compile(r"\s*-\s*classic version", re.IGNORECASE)


def variant_kind(title: str) -> str | None:
    """'coloured' or 'hologram' for special editions, None for the plain emission."""
    if _COLOURED.search(title):
        return "coloured"
    if _HOLOGRAM.search(title):
        return "hologram"
    return None


def base_title(title: str) -> str:
    """Title of the plain emission this edition belongs to."""
    stripped = _COLOURED.sub("", title)
    stripped = _HOLOGRAM.sub("", stripped)
    stripped = _CLASSIC.sub("", stripped)
    return re.sub(r"\s+\)", ")", stripped).strip()
