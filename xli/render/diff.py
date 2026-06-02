"""Render unified diffs with sane colors and an optional path header."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.text import Text

from ..theme import Theme


def render_diff(
    diff: str,
    *,
    path: str | None = None,
    theme: Theme,
) -> RenderableType:
    """Colorize a unified-diff string. Path header is muted+bold above the diff."""

    body = Text(no_wrap=False)
    for i, line in enumerate(diff.splitlines()):
        if i > 0:
            body.append("\n")
        if line.startswith("+++") or line.startswith("---"):
            body.append(line, style="bold")
        elif line.startswith("@@"):
            body.append(line, style=theme.diff_hunk_color)
        elif line.startswith("+"):
            body.append(line, style=theme.diff_add_color)
        elif line.startswith("-"):
            body.append(line, style=theme.diff_del_color)
        else:
            body.append(line)

    if path is None:
        return body
    header = Text(f"diff  {path}", style=f"bold {theme.muted_color}")
    return Group(header, body)
