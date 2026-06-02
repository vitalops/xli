"""Ambient pets — a tiny animated companion in the status line's bottom-right.

Opt-in (``xli.UI(pet="cat")``). Each pet is a list of one-line frames the engine cycles
slowly; the animation is purely decorative and respects the light aesthetic (muted, no
chrome). Pass a custom list of frames for your own creature.
"""

from __future__ import annotations

from collections.abc import Sequence

PETS: dict[str, list[str]] = {
    # mostly-open frames with an occasional blink/wiggle so it idles gently
    "cat": ["(=^･ω･^=)", "(=^･ω･^=)", "(=^･ω･^=)", "(=˘ω˘=)"],
    "dog": ["( •ᴥ• )", "( •ᴥ• )", "( •ᴥ• )", "( ◕ᴥ◕ )"],
    "fox": ["(^≖ᆺ≖^)", "(^≖ᆺ≖^)", "(^-ᆺ-^)"],
    "owl": ["{ʘᴥʘ}", "{ʘᴥʘ}", "{-ᴥ-}"],
}


def frames(pet: str | Sequence[str] | None) -> list[str] | None:
    """Resolve a pet name or explicit frame list to frames (None disables)."""
    if pet is None:
        return None
    if isinstance(pet, str):
        return PETS.get(pet, PETS["cat"])
    return list(pet)
