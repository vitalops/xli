"""Theme presets + overrides."""

from __future__ import annotations

import pytest

from xli.theme import BOXED, CODEX, MINIMAL, Theme, resolve


def test_codex_default_has_no_borders() -> None:
    assert CODEX.use_borders is False
    assert CODEX.tool_glyph == "▸"


def test_minimal_strips_glyphs_and_color() -> None:
    assert MINIMAL.user_color == "default"
    assert MINIMAL.tool_color == "default"
    assert MINIMAL.tool_glyph == ">"


def test_boxed_enables_borders() -> None:
    assert BOXED.use_borders is True


def test_resolve_accepts_name() -> None:
    assert resolve("codex") is CODEX
    assert resolve("minimal") is MINIMAL
    assert resolve("boxed") is BOXED


def test_resolve_accepts_instance() -> None:
    custom = Theme(user_color="red")
    assert resolve(custom) is custom


def test_resolve_default_none() -> None:
    assert resolve(None) is CODEX


def test_resolve_unknown_name_raises() -> None:
    with pytest.raises(ValueError):
        resolve("nope")  # type: ignore[arg-type]


def test_theme_is_frozen() -> None:
    with pytest.raises(AttributeError):
        CODEX.user_color = "x"  # type: ignore[misc]


def test_with_overrides_returns_copy() -> None:
    custom = CODEX.with_overrides(user_color="red", tool_glyph="→")
    assert custom is not CODEX
    assert custom.user_color == "red"
    assert custom.tool_glyph == "→"
    # Other fields preserved
    assert custom.assistant_color == CODEX.assistant_color
