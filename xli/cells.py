"""The scene model — transcript cells and their live handles.

A **cell** is one retained transcript element (a message, a tool call, a diff, an
image, …). Every cell is *mutable* via the handle returned from the ``UI`` method
that created it::

    card = ui.tool("shell", status="running")
    ...
    card.update(status="done", output=result)   # re-renders in place
    card.remove()                                # drop it entirely

Cells are pure renderers: each turns its state into a Rich renderable (reusing the
``xli.render`` functions) and caches the ANSI lines per ``(version, width)`` so the
engine only re-renders what changed.

A cell lives in one of two tiers, managed by the engine:

* **live** — in the redrawing region at the bottom (mutable, animated).
* **committed** — printed into terminal scrollback (selectable, immutable).

A cell graduates from live to committed when it reports ``final`` (e.g. a tool card
reaching a terminal status, a stream closing). Messages/diffs/images are ``final``
on creation and commit immediately.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any, Protocol

from rich.console import Group, RenderableType
from rich.style import Style
from rich.text import Text

from .render import (
    render_diff,
    render_message,
    render_plan,
    render_reasoning,
    render_tool,
)
from .render_bridge import render_to_ansi
from .theme import Theme


class CellSink(Protocol):
    """What a cell needs from its owning engine. The engine implements this."""

    theme: Theme

    def cell_changed(self, cell: Cell) -> None: ...
    def cell_remove(self, cell: Cell) -> None: ...


# ---------------------------------------------------------------------------


class Cell:
    """Base class: versioned, cached, mutable transcript element + handle."""

    #: Cells that are ``final`` commit to scrollback; non-final cells stay live.
    final: bool = True

    def __init__(self) -> None:
        self.version = 0
        self._sink: CellSink | None = None
        self._cache: tuple[int, int, list[str]] | None = None  # (version, width, lines)

    # -- subclass hook -----------------------------------------------------
    def renderable(self, theme: Theme) -> RenderableType:
        raise NotImplementedError

    # -- rendering (cached) ------------------------------------------------
    def lines(self, width: int, theme: Theme) -> list[str]:
        if self._cache and self._cache[0] == self.version and self._cache[1] == width:
            return self._cache[2]
        out = render_to_ansi(self.renderable(theme), width)
        self._cache = (self.version, width, out)
        return out

    # -- public handle API -------------------------------------------------
    def update(self, **fields: Any) -> Cell:
        """Mutate fields and re-render in place. Returns ``self`` for chaining."""
        for key, value in fields.items():
            setattr(self, key, value)
        self.version += 1
        if self._sink is not None:
            self._sink.cell_changed(self)
        return self

    def remove(self) -> None:
        """Remove this cell from the transcript (only meaningful while live)."""
        if self._sink is not None:
            self._sink.cell_remove(self)

    def _bump(self) -> None:
        """Internal: mark dirty + notify without setting attributes."""
        self.version += 1
        if self._sink is not None:
            self._sink.cell_changed(self)


# ---------------------------------------------------------------------------
# Concrete cells — thin wrappers over the pure xli.render functions
# ---------------------------------------------------------------------------


class MessageCell(Cell):
    def __init__(self, role: str, text: str, *, markdown: bool | None = None, label: bool = True) -> None:
        super().__init__()
        self.role, self.text, self.markdown, self.label = role, text, markdown, label

    def renderable(self, theme: Theme) -> RenderableType:
        return render_message(
            self.text, role=self.role, theme=theme, markdown=self.markdown, label=self.label,  # type: ignore[arg-type]
        )


class NoteCell(Cell):
    """A single muted line (``· text``) — status-y, no role label."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text

    def renderable(self, theme: Theme) -> RenderableType:
        return Text(f"· {self.text}", style=theme.muted_color)


class ToolCell(Cell):
    TERMINAL = {"done", "error", "cancelled"}

    def __init__(
        self,
        name: str,
        *,
        args: dict[str, Any] | None = None,
        output: Any = None,
        error: str | None = None,
        status: str | None = None,
    ) -> None:
        super().__init__()
        self.name, self.args, self.output, self.error, self.status = (
            name, args, output, error, status,
        )

    @property
    def final(self) -> bool:  # type: ignore[override]
        # A one-shot card (no status) is final; a tracked card commits when it
        # reaches a terminal status.
        return self.status is None or self.status in self.TERMINAL

    def renderable(self, theme: Theme) -> RenderableType:
        return render_tool(
            self.name, args=self.args, output=self.output,
            error=self.error, status=self.status, theme=theme,
        )


class DiffCell(Cell):
    def __init__(self, diff: str, *, path: str | None = None) -> None:
        super().__init__()
        self.diff, self.path = diff, path

    def renderable(self, theme: Theme) -> RenderableType:
        return render_diff(self.diff, path=self.path, theme=theme)


class PlanCell(Cell):
    def __init__(self, steps: Iterable[Any], *, title: str | None = None) -> None:
        super().__init__()
        self.steps, self.title = list(steps), title

    def renderable(self, theme: Theme) -> RenderableType:
        return render_plan(self.steps, title=self.title, theme=theme)


class ReasoningCell(Cell):
    def __init__(self, summary: str) -> None:
        super().__init__()
        self.summary = summary

    def renderable(self, theme: Theme) -> RenderableType:
        return render_reasoning(self.summary, theme=theme)


class CustomCell(Cell):
    """Wraps an arbitrary Rich renderable (the ``ui.print`` escape hatch)."""

    def __init__(self, renderable: RenderableType) -> None:
        super().__init__()
        self._renderable = renderable

    def renderable(self, theme: Theme) -> RenderableType:
        return self._renderable


class ApprovalCell(Cell):
    """The *context* of an approval request — committed to scrollback so it persists
    and the terminal auto-scrolls to it. The interactive choices + the outcome are
    separate (a live prompt while deciding, then a committed result line)."""

    def __init__(self, title: str, body: str = "", reason: str = "", choices: str = "") -> None:
        super().__init__()
        self.title, self.body, self.reason, self.choices = title, body, reason, choices

    def renderable(self, theme: Theme) -> RenderableType:
        t = Text()
        t.append(f"{theme.approval_glyph} ", style=theme.approval_color)
        t.append("approval needed", style=f"bold {theme.approval_color}")
        t.append(f"  {self.title}")
        if self.body:
            t.append(f"\n  {self.body}")
        if self.reason:
            t.append(f"\n  {self.reason}", style=theme.muted_color)
        if self.choices:
            t.append(f"\n  {self.choices}", style=theme.approval_color)
        return t


class SpinnerCell(Cell):
    """Animated 'working' indicator. Lives in the live tail; never commits."""

    final = False
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label: str) -> None:
        super().__init__()
        self.label, self.frame = label, 0
        self._start = time.monotonic()

    def tick(self) -> None:
        self.frame = (self.frame + 1) % len(self.FRAMES)
        self.version += 1  # frame advance; the engine ticker drives the redraw

    def renderable(self, theme: Theme) -> RenderableType:
        spin = Text(self.FRAMES[self.frame], style=theme.warning_color)
        suffix = f" {self.label}…"
        elapsed = int(time.monotonic() - self._start)
        if elapsed >= 1:
            suffix += f"  {elapsed}s"
        return Text.assemble(spin, Text(suffix, style=theme.muted_color))


class StreamingCell(Cell):
    """A message that grows token-by-token while live, then commits on close.

    For performance, finalized content is committed to scrollback as it completes (the
    engine drains it via :meth:`take_committable_block`), so only the in-progress *tail*
    is re-rendered each frame instead of the whole growing message. Boundaries are blank
    lines that are not inside an open code fence — keeping each committed chunk's markdown
    intact. The role label is emitted once (on the first committed/rendered chunk).
    """

    def __init__(self, role: str, *, markdown: bool | None = None) -> None:
        super().__init__()
        self.role, self.markdown = role, markdown
        self.text = ""
        self._closed = False
        self._committed_len = 0
        self._label_committed = False

    @property
    def final(self) -> bool:  # type: ignore[override]
        return self._closed

    def append(self, chunk: str) -> None:
        if not chunk:
            return
        self.text += chunk
        self._bump()

    def close(self) -> None:
        self._closed = True
        self._bump()

    def consume_label(self) -> bool:
        """True the first time (this chunk shows the role label); False after."""
        if self._label_committed:
            return False
        self._label_committed = True
        return True

    def take_committable_block(self) -> str | None:
        """Pop the next finalized chunk (up to the last safe boundary), advancing the
        committed offset. When closed, the entire remainder is committable. None if there
        is nothing safe to commit yet."""
        region = self.text[self._committed_len:]
        if self._closed:
            if not region:
                return None
            self._committed_len = len(self.text)
            return region
        boundary = _safe_boundary(region)
        if boundary <= 0:
            return None
        self._committed_len += boundary
        return region[:boundary]

    def renderable(self, theme: Theme) -> RenderableType:
        tail = self.text[self._committed_len:] or " "
        return render_message(
            tail, role=self.role, theme=theme, markdown=self.markdown,  # type: ignore[arg-type]
            label=not self._label_committed,
        )


def _safe_boundary(region: str) -> int:
    """Index up to which `region` can be committed: end of the last blank line that is
    not inside an open code fence. 0 if none (keep buffering). Fences are balanced in
    already-committed text, so we start outside a fence."""
    in_fence = False
    pos = 0
    last_safe = 0
    for line in region.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        pos += len(line)
        if not in_fence and stripped == "":
            last_safe = pos
    return last_safe


class ImageCell(Cell):
    """An inline image.

    Renders via the terminal's graphics protocol (kitty / iTerm2) when available, else a
    half-block Unicode fallback (which is just selectable text). Accepts a path, raw bytes,
    or a PIL image. Pillow is required (an install extra); the import is lazy so importing
    xli never needs it.

    The engine's commit printer calls :meth:`raw_emit` first; if it returns an escape
    string (graphics protocol), that's printed as-is, otherwise the half-block
    :meth:`renderable` lines are printed.
    """

    def __init__(self, source: Any, *, width_cols: int = 48) -> None:
        super().__init__()
        self.source, self.width_cols = source, width_cols

    def _load(self):  # -> PIL.Image (RGB) or None if Pillow is missing
        try:
            from PIL import Image  # lazy
        except ImportError:
            return None
        src = self.source
        if hasattr(src, "convert"):       # already a PIL image
            img = src
        elif isinstance(src, (bytes, bytearray)):
            import io as _io
            img = Image.open(_io.BytesIO(src))
        else:
            img = Image.open(src)         # path-like
        return img.convert("RGB")

    def raw_emit(self, term_cols: int) -> str | None:
        """Graphics-protocol escape for this image, or None to use the half-block path."""
        from . import images

        img = self._load()
        if img is None or images.protocol() == "halfblock":
            return None
        cols = max(1, min(self.width_cols, term_cols - 1))
        return images.graphics_escape(img, cols)

    def renderable(self, theme: Theme) -> RenderableType:
        img = self._load()
        if img is None:                   # Pillow not installed
            return Text("⚠ image — install Pillow:  pip install 'xli[images]'",
                        style=theme.warning_color)
        cols = self.width_cols
        w, h = img.size
        rows_px = max(2, round(h * cols / w))
        if rows_px % 2:
            rows_px += 1
        img = img.resize((cols, rows_px))
        px = img.load()
        lines = []
        for y in range(0, rows_px, 2):
            t = Text(no_wrap=True)
            for x in range(cols):
                r1, g1, b1 = px[x, y]
                r2, g2, b2 = px[x, y + 1]
                t.append("▀", style=Style(color=f"#{r1:02x}{g1:02x}{b1:02x}",
                                                bgcolor=f"#{r2:02x}{g2:02x}{b2:02x}"))
            lines.append(t)
        return Group(*lines)
