"""The render bridge — Rich renderables → ANSI lines for the prompt_toolkit engine.

The engine draws its live region (and commits to scrollback) as plain ANSI text.
Rich does all the actual rendering — markdown, syntax highlighting, tables, diffs,
half-block images — and this module turns a renderable into a list of ANSI strings
at a given width. prompt_toolkit then displays each line via ``ANSI(...)``.

Kept tiny and pure so it's trivially testable and cache-friendly.
"""

from __future__ import annotations

import io

from rich.console import Console, RenderableType


def render_to_ansi(renderable: RenderableType, width: int) -> list[str]:
    """Render ``renderable`` to a list of ANSI lines at ``width`` columns.

    Truecolor is forced (degrade is the terminal's job via its own palette); a
    trailing empty line from Rich's newline is stripped so callers control spacing.
    """
    buf = io.StringIO()
    Console(
        file=buf,
        width=max(1, width),
        force_terminal=True,
        color_system="truecolor",
        highlight=False,
        soft_wrap=False,
    ).print(renderable, end="")
    lines = buf.getvalue().split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines
