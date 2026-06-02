"""Visual theme — colors, glyphs, role styling.

Themes are dataclasses, not classes you subclass. To customize, instantiate
:class:`Theme` with the fields you want to override; everything else uses
the codex-inspired defaults.

Three presets are bundled:

* ``"codex"`` (default) — flowing log, no borders, glyph-driven gutters
* ``"minimal"`` — even more austere: no glyphs, just indented text
* ``"boxed"`` — for users who want Rich-style rounded panels
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

ThemeName = Literal["codex", "minimal", "boxed"]


@dataclass(frozen=True)
class Theme:
    """Visual configuration for the UI. All fields have sane defaults."""

    # --- role labels ---
    user_label: str = "you"
    assistant_label: str = "assistant"
    system_label: str = "system"
    show_role_labels: bool = True

    user_color: str = "cyan"
    assistant_color: str = "green"
    system_color: str = "grey50"

    # --- structural glyphs ---
    tool_glyph: str = "▸"
    tool_done_glyph: str = "✓"
    tool_error_glyph: str = "✗"
    tool_cancelled_glyph: str = "⦻"
    tool_color: str = "blue"
    tool_output_indent: int = 2

    reasoning_glyph: str = "│"
    reasoning_color: str = "grey50"

    plan_pending_glyph: str = "☐"
    plan_in_progress_glyph: str = "▸"
    plan_completed_glyph: str = "☑"
    plan_color: str = "magenta"

    approval_glyph: str = "⚠"
    approval_color: str = "yellow"

    error_color: str = "red"
    warning_color: str = "yellow"
    success_color: str = "green"
    muted_color: str = "grey50"

    # --- diff ---
    diff_add_color: str = "green"
    diff_del_color: str = "red"
    diff_hunk_color: str = "magenta"

    # --- code blocks (passed to rich.Syntax) ---
    code_theme: str = "monokai"
    code_word_wrap: bool = True
    code_background: bool = False

    # --- composer ---
    # The prompt is a glyph in a soft accent color — NOT a filled block. We avoid
    # solid backgrounds for chrome (see docs/theme.md): separation comes from font
    # color + a thin rule, so the UI reads "light" and terminal-native.
    prompt_glyph: str = ">"
    prompt_color: str = "bold cyan"            # foreground of the glyph
    prompt_bg: str = ""                         # no background block
    prompt_text_color: str = "default"          # typed text uses the terminal's own fg
    command_color: str = "bold cyan"            # a recognized /command in the composer
    multiline_continuation: str = "  "

    # --- borders / spacing ---
    use_borders: bool = False
    panel_border: str = "rounded"  # if use_borders is True
    item_spacing: int = 1           # blank lines between transcript items

    # --- status bar ---
    status_separator: str = "  ·  "
    status_color: str = "grey50"

    @classmethod
    def named(cls, name: ThemeName) -> Theme:
        if name == "codex":
            return CODEX
        if name == "minimal":
            return MINIMAL
        if name == "boxed":
            return BOXED
        raise ValueError(f"unknown theme: {name!r}")

    def with_overrides(self, **kwargs) -> Theme:
        """Return a copy with the given fields replaced."""
        return replace(self, **kwargs)


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


#: The default theme. Aesthetic: codex / aider — minimal, glyph-driven, no boxes.
CODEX = Theme()

#: Even quieter — no glyphs, no colors except where strictly needed.
MINIMAL = Theme(
    show_role_labels=True,
    user_color="default",
    assistant_color="default",
    tool_glyph=">",
    tool_done_glyph="[ok]",
    tool_error_glyph="[x]",
    tool_cancelled_glyph="[-]",
    tool_color="default",
    reasoning_glyph=" ",
    reasoning_color="default",
    plan_pending_glyph="[ ]",
    plan_in_progress_glyph="[~]",
    plan_completed_glyph="[x]",
    plan_color="default",
    approval_glyph="!",
    approval_color="default",
    prompt_glyph=">",
    prompt_color="default",
    prompt_bg="",
    prompt_text_color="default",
    command_color="bold",  # austere: recognition via weight, not color
)

#: For users who want rounded panels around each item.
BOXED = Theme(
    use_borders=True,
    show_role_labels=True,
    tool_glyph="▸",
    item_spacing=0,
)


def resolve(theme: Theme | ThemeName | None) -> Theme:
    """Accept ``Theme`` instance, name string, or None (→ default)."""
    if theme is None:
        return CODEX
    if isinstance(theme, Theme):
        return theme
    return Theme.named(theme)
