"""xli v2 — Phase 0 de-risk spike  (inline-rendering revision).

Proves the four historical "wall" features AND native text selection, using the
correct rendering model: INLINE, not full-screen.

  * Finalized cells are COMMITTED to the terminal's normal scrollback
    -> natively selectable + scrollable (Bug 1 fix).
  * Only the active tail (running tool card, spinner, streaming, status, composer)
    lives in a small redrawing region at the bottom -> mutable / animated.
  * A cell is mutable while live; once finalized it commits to scrollback.

Gates:
  1. Concurrent input — type / queue prompts while a handler runs.
  2. ESC interrupt    — cancel the turn, fire on_interrupt cleanup, ONE marker, survive.
  3. Mutable cells    — tool card flips running->done while live, then commits.
  4. Inline image     — image renders as a (selectable) scrollback cell.

    python spikes/phase0.py --harness    # headless, asserts the mechanics
    python spikes/phase0.py              # interactive inline demo (real terminal)
    python spikes/phase0.py --probe      # report this terminal's image protocol
"""

from __future__ import annotations

import asyncio
import io
import os
import shutil
import sys
from typing import Awaitable, Callable, Optional

from rich.console import Console, Group
from rich.style import Style
from rich.text import Text


# ---------------------------------------------------------------------------
# Layer 2 — rich renderable -> ANSI lines (cached per cell version + width)
# ---------------------------------------------------------------------------

def render_to_ansi(renderable, width: int) -> list[str]:
    buf = io.StringIO()
    Console(
        file=buf, width=width, force_terminal=True, color_system="truecolor",
        highlight=False, soft_wrap=False,
    ).print(renderable, end="")
    out = buf.getvalue().split("\n")
    if out and out[-1] == "":
        out.pop()
    return out


def halfblock(img, cols: int) -> Group:
    w, h = img.size
    tw = max(1, cols)
    th = max(2, round(h * tw / w))
    if th % 2:
        th += 1
    img = img.convert("RGB").resize((tw, th))
    px = img.load()
    lines = []
    for y in range(0, th, 2):
        t = Text(no_wrap=True)
        for x in range(tw):
            r1, g1, b1 = px[x, y]
            r2, g2, b2 = px[x, y + 1]
            t.append("▀", style=Style(color=f"#{r1:02x}{g1:02x}{b1:02x}",
                                            bgcolor=f"#{r2:02x}{g2:02x}{b2:02x}"))
        lines.append(t)
    return Group(*lines)


def _demo_image():
    from PIL import Image
    for name in ("plot.png", "image.png", "demo.png"):
        p = os.path.join(os.path.dirname(__file__), name)
        if os.path.exists(p):
            try:
                return Image.open(p)
            except Exception:
                pass
    w, h = 64, 32
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (int(255 * x / w), int(255 * y / h), 160)
    return img


# ---------------------------------------------------------------------------
# Layer 3 — scene model: cells + handles
# ---------------------------------------------------------------------------

class Cell:
    def __init__(self, session: "Session"):
        self._session = session
        self.version = 0
        self._cache: tuple[int, int, list[str]] | None = None

    def renderable(self):
        raise NotImplementedError

    def update(self, **fields) -> "Cell":
        for k, v in fields.items():
            setattr(self, k, v)
        self.version += 1
        self._session._on_cell_update(self)
        return self

    def lines(self, width: int) -> list[str]:
        if self._cache and self._cache[0] == self.version and self._cache[1] == width:
            return self._cache[2]
        out = render_to_ansi(self.renderable(), width)
        self._cache = (self.version, width, out)
        return out


class ToolCell(Cell):
    TERMINAL = {"done", "error", "cancelled"}

    def __init__(self, session, name, *, status="running", output=""):
        super().__init__(session)
        self.name, self.status, self.output = name, status, output

    def renderable(self):
        glyph = {"running": "[yellow]▸[/]", "done": "[green]✓[/]",
                 "error": "[red]✗[/]", "cancelled": "[red]⦻[/]"}.get(self.status, "▸")
        head = Text.from_markup(f"{glyph} [blue]{self.name}[/]  [dim]({self.status})[/]")
        if self.output:
            return Group(head, Text("    " + self.output.replace("\n", "\n    "), style="dim"))
        return head


class TextCell(Cell):
    def __init__(self, session, role, text):
        super().__init__(session)
        self.role, self.text = role, text

    def renderable(self):
        color = {"you": "cyan", "assistant": "green"}.get(self.role, "grey50")
        return Text.from_markup(f"[{color}]{self.role}[/]  {self.text}")


class SpinnerCell(Cell):
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, session, label):
        super().__init__(session)
        self.label, self.frame = label, 0

    def tick(self):
        self.frame = (self.frame + 1) % len(self.FRAMES)
        self.version += 1

    def renderable(self):
        return Text.from_markup(f"[yellow]{self.FRAMES[self.frame]}[/] [dim]{self.label}…[/]")


class ImageCell(Cell):
    def __init__(self, session, img, cols=48):
        super().__init__(session)
        self.img, self.cols = img, cols

    def renderable(self):
        return halfblock(self.img, self.cols)


# ---------------------------------------------------------------------------
# Layer 1 core — Session: two-tier scene (committed scrollback + live tail),
# dispatcher, cancellation. Drives BOTH the harness and the interactive App.
# ---------------------------------------------------------------------------

Handler = Callable[["Session", str], Awaitable[None]]


class Session:
    def __init__(self, handler: Handler,
                 on_interrupt: Optional[Callable[[], Awaitable[None]]] = None):
        self._handler = handler
        self._on_interrupt = on_interrupt
        self.live: list[Cell] = []          # active tail — redrawn, mutable
        self.committed: list[Cell] = []     # pushed to scrollback — selectable, immutable
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._current: Optional[asyncio.Task] = None
        self.invalidate_count = 0
        self.on_invalidate: Callable[[], None] = lambda: None   # redraw the live region
        self.commit_cb: Callable[[Cell], None] = lambda c: None  # print cell to scrollback

    # --- redraw / commit plumbing ---
    def invalidate(self) -> None:
        self.invalidate_count += 1
        self.on_invalidate()

    def _on_cell_update(self, cell: Cell) -> None:
        # A live cell reaching a terminal status graduates to scrollback.
        if isinstance(cell, ToolCell) and cell.status in ToolCell.TERMINAL and cell in self.live:
            self._commit(cell)
        else:
            self.invalidate()

    def _commit(self, cell: Cell) -> None:
        if cell in self.live:
            self.live.remove(cell)
        self.committed.append(cell)
        self.commit_cb(cell)   # interactive: print to scrollback (selectable)
        self.invalidate()

    def _commit_now(self, cell: Cell) -> Cell:
        """For already-final cells (messages, images): straight to scrollback."""
        self.committed.append(cell)
        self.commit_cb(cell)
        self.invalidate()
        return cell

    def _add_live(self, cell: Cell) -> Cell:
        self.live.append(cell)
        self.invalidate()
        return cell

    # --- public-API-ish surface ---
    def tool(self, name, **kw) -> ToolCell:
        return self._add_live(ToolCell(self, name, **kw))  # type: ignore[return-value]

    def message(self, role, text) -> TextCell:
        return self._commit_now(TextCell(self, role, text))  # type: ignore[return-value]

    def image(self, img, cols=48) -> ImageCell:
        return self._commit_now(ImageCell(self, img, cols))  # type: ignore[return-value]

    def working(self, label: str):
        session = self

        class _W:
            def __enter__(self_):
                self_.cell = session._add_live(SpinnerCell(session, label))
                return self_.cell
            def __exit__(self_, *exc):
                if self_.cell in session.live:
                    session.live.remove(self_.cell)
                session.invalidate()
        return _W()

    # --- concurrency ---
    @property
    def busy(self) -> bool:
        return self._current is not None and not self._current.done()

    @property
    def queue_depth(self) -> int:
        return self.queue.qsize()

    def submit(self, text: str) -> None:
        text = text.strip()
        if text:
            self.queue.put_nowait(text)

    def start(self) -> None:
        asyncio.create_task(self._run_loop())

    async def _run_loop(self) -> None:
        while True:
            text = await self.queue.get()
            self.message("you", text)
            self._current = asyncio.create_task(self._handler(self, text))
            try:
                await self._current
            except asyncio.CancelledError:
                if self._on_interrupt:
                    await self._on_interrupt()           # cleanup (no transcript writes)
                self.message("system", "⦻ interrupted")  # exactly ONE marker (Bug 2 fix)
            except Exception as e:
                self.message("system", f"[error] {e!r}")
            finally:
                self._current = None
                self.invalidate()

    def interrupt(self) -> bool:
        if self.busy:
            self._current.cancel()  # type: ignore[union-attr]
            return True
        return False

    def tick(self) -> None:
        dirty = any(isinstance(c, SpinnerCell) for c in self.live)
        for c in self.live:
            if isinstance(c, SpinnerCell):
                c.tick()
        if dirty:
            self.on_invalidate()


# ---------------------------------------------------------------------------
# Demo handler (interactive)
# ---------------------------------------------------------------------------

async def demo_handler(ui: Session, prompt: str) -> None:
    if prompt == "img":
        ui.image(_demo_image())
        return
    if prompt == "long":
        with ui.working("running a long task (hit ESC)"):
            await asyncio.sleep(30)
        return
    with ui.working("thinking"):
        await asyncio.sleep(0.6)
    card = ui.tool("shell", status="running", output="$ " + prompt)
    await asyncio.sleep(0.8)
    card.update(status="done", output="$ " + prompt + "\nok (exit 0)")
    ui.message("assistant", f"handled: {prompt}")


# ---------------------------------------------------------------------------
# Headless harness — asserts the mechanics on the shared Session core
# ---------------------------------------------------------------------------

async def run_harness() -> int:
    print("xli v2 Phase 0 — headless harness (inline model)\n")
    results: list[tuple[str, bool, str]] = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    state = {"cancelled_seen": False, "cleanup_ran": False, "ran": []}
    committed_log: list[str] = []

    async def handler(ui: Session, prompt: str):
        state["ran"].append(prompt)
        if prompt == "LONG":
            card = ui.tool("sleep", status="running")
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                state["cancelled_seen"] = True
                card.update(status="cancelled")
                raise
        elif prompt == "CARD":
            card = ui.tool("shell", status="running", output="$ ls")
            inv_before = ui.invalidate_count
            live_while_running = card in ui.live
            await asyncio.sleep(0.05)
            card.update(status="done", output="$ ls\nREADME.md")
            state.update(card=card, inv_delta=ui.invalidate_count - inv_before,
                         live_while_running=live_while_running,
                         committed_after=(card in ui.committed and card not in ui.live))
        else:
            await asyncio.sleep(0.2)

    async def cleanup():
        state["cleanup_ran"] = True

    session = Session(handler, on_interrupt=cleanup)
    session.commit_cb = lambda c: committed_log.append(type(c).__name__)
    session.start()

    # GATE 1 — concurrent input / type-ahead
    session.submit("LONG")
    await asyncio.sleep(0.05)
    busy = session.busy
    session.submit("QUEUED")
    queued = session.queue_depth >= 1
    check("1. concurrent input: busy while a turn runs", busy)
    check("1. type-ahead: 2nd prompt queued, not dropped", queued, f"depth={session.queue_depth}")

    # GATE 2 — ESC interrupt + single marker + cleanup + survival
    msgs_before = len(committed_log)
    interrupted = session.interrupt()
    await asyncio.sleep(0.05)
    check("2. ESC cancelled the running turn", interrupted and state["cancelled_seen"])
    check("2. on_interrupt cleanup hook fired", state["cleanup_ran"])
    await asyncio.sleep(0.3)
    # exactly one 'system' interrupt marker committed (not two) — Bug 2
    interrupt_markers = sum(1 for c in session.committed
                            if isinstance(c, TextCell) and c.role == "system" and "interrupted" in c.text)
    check("2. exactly ONE interrupt marker (no duplicate)", interrupt_markers == 1,
          f"markers={interrupt_markers}")
    check("2. session survived interrupt (queued turn ran)", "QUEUED" in state["ran"],
          f"ran={state['ran']}")

    # GATE 3 — mutable while live, then commits to scrollback (Bug 1 model)
    session.submit("CARD")
    await asyncio.sleep(0.2)
    card = state.get("card")
    after = "\n".join(card.lines(60)) if card else ""
    check("3. tool card was LIVE (mutable) while running", state.get("live_while_running"))
    check("3. mutable cell: handle flipped running->done", card and card.status == "done")
    check("3. mutated cell re-renders as 'done'", "done" in after and "running" not in after)
    check("3. finalized cell COMMITTED to scrollback (selectable)", state.get("committed_after"))
    check("3. .update() triggered a redraw", state.get("inv_delta", 0) >= 1,
          f"inv_delta={state.get('inv_delta')}")

    # GATE 4 — inline image renders as a (committed/selectable) cell
    img_cell = ImageCell(session, _demo_image(), cols=40)
    img_lines = img_cell.lines(80)
    has_color = any("\x1b[" in ln and "▀" in ln for ln in img_lines)
    check("4. inline image rendered as cell (half-block)", len(img_lines) > 3 and has_color,
          f"{len(img_lines)} rows")

    print()
    ok = True
    for name, passed, detail in results:
        mark = "\x1b[32mPASS\x1b[0m" if passed else "\x1b[31mFAIL\x1b[0m"
        print(f"  [{mark}] {name}" + (f"   \x1b[2m{detail}\x1b[0m" if detail else ""))
        ok = ok and passed
    print("\n" + ("\x1b[32mALL GATES PASS\x1b[0m" if ok else "\x1b[31mSOME GATES FAILED\x1b[0m"))
    return 0 if ok else 1


def run_probe() -> int:
    print("Image-protocol probe for this terminal:\n")
    for k in ("TERM", "TERM_PROGRAM", "KITTY_WINDOW_ID", "WT_SESSION", "COLORTERM"):
        print(f"  {k:16} = {os.environ.get(k, '')!r}")
    try:
        from term_image.image import auto_image_class
        proto = auto_image_class().__name__
    except Exception as e:
        proto = f"(needs a real tty: {e.__class__.__name__})"
    print(f"\n  term-image auto class : {proto}")
    print("  Phase 0 uses half-block fallback (selectable text-cells); true kitty/iTerm/sixel = Phase 4.")
    return 0


# ---------------------------------------------------------------------------
# Interactive — INLINE app: scrollback (selectable) + live tail (mutable)
# ---------------------------------------------------------------------------

def run_interactive() -> int:
    from prompt_toolkit.application import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout, HSplit, Window
    from prompt_toolkit.layout.controls import (
        BufferControl, FormattedTextControl, UIContent, UIControl)
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    from prompt_toolkit.patch_stdout import patch_stdout
    from prompt_toolkit.styles import Style

    holder: dict[str, Session] = {}

    def term_width() -> int:
        return max(20, shutil.get_terminal_size((80, 24)).columns)

    class LiveTailControl(UIControl):
        """Renders ONLY the live cells (running tool card, spinner). Small + redrawn."""
        def create_content(self, width, height):
            lines: list[str] = []
            for cell in holder["s"].live:
                lines.extend(cell.lines(width))
            def get_line(i):
                return to_formatted_text(ANSI(lines[i]))
            return UIContent(get_line=get_line, line_count=len(lines), show_cursor=False)

    composer = Buffer(multiline=False)

    def status_text():
        s = holder["s"]
        return [
            ("class:status.busy" if s.busy else "class:status.idle",
             f" {'working' if s.busy else 'idle'}"),
            ("class:status",
             f"  ·  queue:{s.queue_depth}  ·  ENTER send · ESC interrupt · Ctrl-Q quit"
             f"  ·  try: img · long · anything"),
        ]

    kb = KeyBindings()

    @kb.add("enter")
    def _(event):
        text = composer.text
        composer.reset()
        holder["s"].submit(text)

    @kb.add("escape", eager=True)
    def _(event):
        holder["s"].interrupt()

    @kb.add("c-q")
    @kb.add("c-c")
    def _(event):
        event.app.exit()

    live_win = Window(content=LiveTailControl(), height=Dimension(min=0, max=12))
    status_win = Window(content=FormattedTextControl(status_text), height=1)  # no solid bg
    composer_win = Window(content=BufferControl(buffer=composer), height=1,
                          get_line_prefix=lambda *a: [("class:prompt", " > ")])
    sep_win = Window(height=1, char="─", style="class:sep")  # border line for separation
    # order top->bottom: live tail, separator, composer, status bar below the input
    layout = Layout(HSplit([live_win, sep_win, composer_win, status_win]),
                    focused_element=composer_win)

    # Separation via font color + a border rule — no solid backgrounds.
    style = Style.from_dict({
        "sep": "fg:#3a3a3a",
        "prompt": "fg:#5fd7ff bold",
        "status": "fg:#808080",
        "status.busy": "fg:#d7af00 bold",
        "status.idle": "fg:#5f8700",
    })

    # NOTE: mouse_support stays OFF so the terminal's native text selection works.
    # full_screen=False so finalized cells live in real scrollback (selectable).
    # refresh_interval drives steady repaints so live-region animations (spinner) run
    # even while a turn is just awaiting with no I/O.
    app = Application(layout=layout, key_bindings=kb, style=style, full_screen=False,
                      mouse_support=False, refresh_interval=0.1)

    def commit_to_scrollback(cell):
        # printed under patch_stdout -> appears in scrollback above the live region
        for ln in cell.lines(term_width()):
            print(ln)
        print()  # one blank line of breathing room after every cell (margin under images)

    async def cleanup():
        pass  # release resources here — intentionally NO transcript writes (Bug 2)

    async def main():
        s = Session(demo_handler, on_interrupt=cleanup)
        s.on_invalidate = app.invalidate
        s.commit_cb = commit_to_scrollback
        holder["s"] = s
        s.start()
        s.message("system", "inline spike — finalized lines are selectable scrollback; the "
                            "bottom is the live region. try: img · long+ESC · any text.")

        async def ticker():
            while True:
                await asyncio.sleep(0.1)
                s.tick()
        t = asyncio.create_task(ticker())
        try:
            with patch_stdout(raw=True):
                await app.run_async()
        finally:
            t.cancel()

    asyncio.run(main())
    return 0


if __name__ == "__main__":
    if "--harness" in sys.argv:
        sys.exit(asyncio.run(run_harness()))
    elif "--probe" in sys.argv:
        sys.exit(run_probe())
    else:
        sys.exit(run_interactive())
