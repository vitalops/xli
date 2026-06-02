"""Terminal image protocols — kitty / iTerm2 escapes, with a half-block fallback.

Why this is simpler here than in a full-screen TUI: xli commits images to the normal
scrollback (printed once), so we don't re-emit them every frame or juggle reserved rows
in a redraw loop — we print the escape once and the terminal scrolls it like any output.

Protocol detection is **env-only** (no terminal queries) so it can't interfere with the
running prompt_toolkit app's input loop. Override with ``XLI_IMAGE_PROTOCOL`` =
``kitty`` | ``iterm`` | ``halfblock``. Terminals without a graphics protocol (e.g. Windows
Terminal) use the half-block renderer in :class:`xli.cells.ImageCell`, which is just text.

kitty/iTerm output is best-effort and verified on capable terminals; the half-block path
is the safe default everywhere.
"""

from __future__ import annotations

import base64
import io
import os

# Approximate character-cell aspect (height / width). Used to pick a row count that
# keeps the image from looking stretched.
_CELL_ASPECT = 2.0
_KITTY_CHUNK = 4096

_protocol: str | None = None


def detect_protocol() -> str:
    """Best-effort env-based detection: 'kitty' | 'iterm' | 'halfblock'."""
    term = os.environ.get("TERM", "")
    if os.environ.get("KITTY_WINDOW_ID") or term == "xterm-kitty" or "ghostty" in term:
        return "kitty"
    if os.environ.get("TERM_PROGRAM", "") in ("iTerm.app", "WezTerm"):
        return "iterm"
    return "halfblock"


def protocol() -> str:
    """The active protocol (cached). ``XLI_IMAGE_PROTOCOL`` overrides detection."""
    global _protocol
    if _protocol is None:
        _protocol = os.environ.get("XLI_IMAGE_PROTOCOL") or detect_protocol()
    return _protocol


def target_rows(width_px: int, height_px: int, cols: int) -> int:
    return max(1, round(cols * (height_px / max(1, width_px)) / _CELL_ASPECT))


def _png_b64(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def iterm_escape(img, cols: int, rows: int) -> str:
    """iTerm2 inline image (OSC 1337). The image occupies the given cell box and the
    terminal advances the cursor past it."""
    data = _png_b64(img)
    return (
        f"\033]1337;File=inline=1;width={cols};height={rows};"
        f"preserveAspectRatio=1:{data}\a"
    )


def kitty_escape(img, cols: int, rows: int) -> str:
    """kitty graphics protocol: transmit-and-display a PNG (f=100), scaled into a
    ``cols``×``rows`` cell area, chunked at 4096 bytes per the spec."""
    data = _png_b64(img)
    chunks = [
        data[i : i + _KITTY_CHUNK] for i in range(0, len(data), _KITTY_CHUNK)
    ] or [""]
    out = []
    for i, chunk in enumerate(chunks):
        more = 1 if i < len(chunks) - 1 else 0
        if i == 0:
            ctrl = f"a=T,f=100,c={cols},r={rows},m={more}"
        else:
            ctrl = f"m={more}"
        out.append(f"\033_G{ctrl};{chunk}\033\\")
    return "".join(out)


def graphics_escape(img, cols: int) -> str | None:
    """Return the escape string for the active graphics protocol, or None for half-block."""
    proto = protocol()
    rows = target_rows(img.size[0], img.size[1], cols)
    if proto == "iterm":
        return iterm_escape(img, cols, rows)
    if proto == "kitty":
        return kitty_escape(img, cols, rows)
    return None
