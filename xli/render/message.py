"""Render user / assistant / system messages.

Each message is a small Rich renderable group: an optional role label
followed by the body. The body is markdown for assistant messages, plain
for user/system. Borders / left-rails are governed by the theme.
"""

from __future__ import annotations

from typing import Literal

from rich import box as _box
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from ..theme import Theme

Role = Literal["user", "assistant", "system"]


def _box_for(name: str):
    """Map a theme box name (e.g. 'rounded') to a rich Box, defaulting to ROUNDED."""
    return getattr(_box, name.upper(), _box.ROUNDED)


def render_message(
    text: str,
    *,
    role: Role,
    theme: Theme,
    markdown: bool | None = None,
    label: bool = True,
) -> RenderableType:
    """Static message render (the streaming case sees ``render_streaming_message``).

    ``label=False`` suppresses the role label — used for streamed continuation chunks
    that commit under an already-labelled first chunk (so the label isn't repeated).
    """

    # System messages are compact by design: ``· text`` on as few lines as
    # possible. They're meta-info, not part of the conversation flow.
    if role == "system":
        return _render_system(text, theme=theme)

    use_md = markdown if markdown is not None else (role == "assistant")
    body: RenderableType
    if use_md and text.strip():
        body = Markdown(
            text,
            code_theme=theme.code_theme,
            inline_code_theme=theme.code_theme,
        )
    else:
        body = Text(text or "", no_wrap=False)

    if theme.use_borders:
        return Panel(
            body,
            title=_role_label_text(role, theme) if label else None,
            title_align="left",
            border_style=_role_color(role, theme),
            box=_box_for(theme.panel_border),
        )

    parts: list[RenderableType] = []
    if label and theme.show_role_labels:
        parts.append(_role_label_text(role, theme))
    parts.append(Padding(body, (0, 0, 0, 2)))
    return Group(*parts)


def _render_system(text: str, *, theme: Theme) -> RenderableType:
    """``· first line``, additional lines indented to align with the body."""

    lines = (text or "").splitlines() or [""]
    out = Text()
    for i, line in enumerate(lines):
        if i > 0:
            out.append("\n")
        if i == 0:
            out.append("· ", style=theme.muted_color)
        else:
            out.append("  ")
        out.append(line, style=theme.muted_color)
    return out


def render_streaming_message(
    text: str, *, role: Role, theme: Theme, markdown: bool | None = None
) -> RenderableType:
    """Renderable suitable for repeated update inside Rich's ``Live`` context.

    Same shape as :func:`render_message` but tolerant of partial markdown
    (we don't try to "complete" it — Rich handles partial blocks fine).
    """
    return render_message(text or " ", role=role, theme=theme, markdown=markdown)


def _role_label_text(role: Role, theme: Theme) -> Text:
    if role == "user":
        return Text(theme.user_label, style=f"bold {theme.user_color}")
    if role == "assistant":
        return Text(theme.assistant_label, style=f"bold {theme.assistant_color}")
    return Text(theme.system_label, style=f"bold {theme.system_color}")


def _role_color(role: Role, theme: Theme) -> str:
    if role == "user":
        return theme.user_color
    if role == "assistant":
        return theme.assistant_color
    return theme.system_color
