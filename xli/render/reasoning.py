"""Render reasoning summaries — muted, lightly-railed."""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text

from ..theme import Theme


def render_reasoning(summary: str, *, theme: Theme) -> RenderableType:
    text = Text()
    rail = theme.reasoning_glyph
    style = theme.reasoning_color
    for i, line in enumerate(summary.strip().splitlines() or [""]):
        if i > 0:
            text.append("\n")
        text.append(f"{rail} ", style=style)
        text.append(line, style=style)
    return text
