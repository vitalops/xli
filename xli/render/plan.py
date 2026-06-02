"""Render a plan: list of (title, status) steps as a checklist.

Status values: ``"pending"`` (default), ``"in_progress"``, ``"completed"``.
Anything else is treated as ``"pending"`` (forward-compat).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from rich.console import RenderableType
from rich.text import Text

from ..theme import Theme


def render_plan(
    steps: Iterable[Any],
    *,
    theme: Theme,
    title: str | None = None,
) -> RenderableType:
    out = Text()
    if title:
        out.append(title, style=f"bold {theme.plan_color}")
        out.append("\n")
    rows = list(_iter_steps(steps))
    for i, (step_title, status, notes) in enumerate(rows):
        glyph = _glyph(status, theme)
        out.append(f"  {glyph}  ", style=theme.plan_color)
        out.append(step_title)
        if notes:
            out.append(f"   ({notes})", style=theme.muted_color)
        if i != len(rows) - 1:
            out.append("\n")
    return out


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _glyph(status: str, theme: Theme) -> str:
    if status == "completed":
        return theme.plan_completed_glyph
    if status == "in_progress":
        return theme.plan_in_progress_glyph
    return theme.plan_pending_glyph


def _iter_steps(steps: Iterable[Any]) -> Iterable[tuple[str, str, str | None]]:
    """Accept any of: dicts, dataclasses, (title, status[, notes]) tuples, bare strings."""
    for s in steps:
        if isinstance(s, dict):
            yield (str(s.get("title", "")), str(s.get("status", "pending")), s.get("notes"))
        elif isinstance(s, str):
            yield (s, "pending", None)
        elif isinstance(s, tuple):
            if len(s) == 2:
                yield (str(s[0]), str(s[1]), None)
            else:
                yield (str(s[0]), str(s[1]), str(s[2]) if s[2] else None)
        else:
            yield (
                str(getattr(s, "title", s)),
                str(getattr(s, "status", "pending")),
                getattr(s, "notes", None),
            )
