"""Image protocol detection + escape generation (the half-block path is in test_ui/render)."""

from __future__ import annotations

import pytest

from xli import images
from xli.cells import ImageCell


def _img(w=8, h=8):
    PIL = pytest.importorskip("PIL.Image")
    im = PIL.new("RGB", (w, h), (10, 20, 30))
    return im


@pytest.fixture(autouse=True)
def _reset_protocol_cache():
    images._protocol = None
    yield
    images._protocol = None


def test_detect_kitty(monkeypatch):
    monkeypatch.delenv("XLI_IMAGE_PROTOCOL", raising=False)
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    monkeypatch.setenv("TERM", "xterm-kitty")
    assert images.detect_protocol() == "kitty"


def test_detect_iterm(monkeypatch):
    monkeypatch.delenv("KITTY_WINDOW_ID", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    assert images.detect_protocol() == "iterm"


def test_detect_fallback(monkeypatch):
    for var in ("KITTY_WINDOW_ID", "TERM_PROGRAM"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert images.detect_protocol() == "halfblock"


def test_protocol_env_override(monkeypatch):
    monkeypatch.setenv("XLI_IMAGE_PROTOCOL", "kitty")
    assert images.protocol() == "kitty"


def test_iterm_escape_structure():
    esc = images.iterm_escape(_img(), cols=10, rows=5)
    assert esc.startswith("\033]1337;File=inline=1;width=10;height=5")
    assert esc.endswith("\a")
    assert "preserveAspectRatio=1:" in esc and len(esc) > 40  # carries base64 payload


def test_kitty_escape_structure_and_chunking():
    esc = images.kitty_escape(_img(64, 64), cols=20, rows=10)
    assert esc.startswith("\033_Ga=T,f=100,c=20,r=10,m=")
    assert esc.endswith("\033\\")
    # control sequence present; final chunk marks m=0
    assert "m=0;" in esc


def test_target_rows_keeps_aspect():
    # a 2:1 (wide) image at 20 cols -> ~5 rows (20 * 0.5 / 2.0)
    assert images.target_rows(200, 100, 20) == 5


def test_image_cell_raw_emit_halfblock_is_none(monkeypatch):
    monkeypatch.setenv("XLI_IMAGE_PROTOCOL", "halfblock")
    images._protocol = None
    cell = ImageCell(_img())
    assert cell.raw_emit(80) is None  # -> falls back to half-block lines


def test_image_cell_raw_emit_graphics(monkeypatch):
    monkeypatch.setenv("XLI_IMAGE_PROTOCOL", "iterm")
    images._protocol = None
    cell = ImageCell(_img(), width_cols=12)
    esc = cell.raw_emit(80)
    assert esc is not None and esc.startswith("\033]1337;File=inline=1")


def test_image_cell_halfblock_renders_truecolor():
    cell = ImageCell(_img(8, 8), width_cols=8)
    rendered = "\n".join(cell.lines(40, __import__("xli").CODEX))
    assert "▀" in rendered and "\x1b[" in rendered


def test_image_cell_without_pillow_shows_hint(monkeypatch):
    import xli

    cell = ImageCell("x.png")
    monkeypatch.setattr(cell, "_load", lambda: None)  # simulate Pillow missing
    assert cell.raw_emit(80) is None  # -> no graphics escape
    rendered = "\n".join(cell.lines(60, xli.CODEX))
    assert "Pillow" in rendered  # friendly hint, not a crash
