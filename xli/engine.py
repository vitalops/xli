"""The runtime engine — inline two-tier transcript on prompt_toolkit.

This is the heart of xli v2, validated by the Phase 0 spike. Design:

* **Inline, not full-screen.** The app runs under ``patch_stdout`` and renders only a
  small live region at the bottom. Finalized cells are *printed into normal terminal
  scrollback* — so transcript text is natively selectable and scrollable. Only the
  active tail (running tool cards, spinners, the open stream, status, composer) is
  redrawn. (Full-screen breaks selection; that's why we don't use it.)
* **Two tiers.** ``live`` cells are mutable + animated; on reaching ``final`` they
  commit to scrollback and become immutable.
* **Concurrent.** The composer stays live while a handler runs as a task. Submissions
  queue (type-ahead). ESC cancels the running turn cooperatively and fires the
  ``on_interrupt`` cleanup hook; the session survives.

The engine implements :class:`xli.cells.CellSink`. The public :class:`xli.UI` is a thin
facade over it.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI, to_formatted_text
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.layout.controls import BufferControl, UIContent, UIControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Group
from rich.text import Text

from .approval import Decision
from .cells import (
    ApprovalCell,
    Cell,
    CustomCell,
    MessageCell,
    NoteCell,
    SpinnerCell,
    StreamingCell,
    ToolCell,
)
from .render_bridge import render_to_ansi
from .slash import SlashLexer, SlashRegistry
from .status import StatusBar
from .theme import Theme

Handler = Callable[[str], Coroutine[Any, Any, None]]
InterruptHook = Callable[[], Awaitable[None]]


class Engine:
    def __init__(
        self,
        *,
        theme: Theme,
        slash: SlashRegistry,
        status: StatusBar,
        title: str | None = None,
        intro: str | None = None,
        history_file: str | None = None,
        pet: list[str] | None = None,
        notify_after: float | None = None,
    ) -> None:
        self.theme = theme
        self._slash = slash
        self._status = status
        self._title = title
        self._intro = intro
        self._history_file = history_file
        self._pet = pet
        self._pet_i = 0
        self._pet_ticks = 0
        self._notify_after = notify_after

        # scene
        self.live: list[Cell] = []
        self.committed: list[Cell] = []

        # dispatch / turn state
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._pending: list[str] = (
            []
        )  # queued prompts, shown as type-ahead in the live tail
        self._current: asyncio.Task | None = None
        self._handler: Handler | None = None
        self._on_interrupt: InterruptHook | None = None
        self._exit = asyncio.Event()

        # inline-modal state: an arrow-selectable picker (approve/confirm/pick/wizard)
        # and a one-line capture (input). Both render in the live region.
        self._picker: _Picker | None = None
        self._line: asyncio.Future[str | None] | None = None

        # completion — our own list rendered below the composer (replaces the pt popup,
        # which used solid-bg chrome + fragile float positioning). Serves /commands and
        # @file mentions.
        self._sugg_index = 0
        self._suggest_dismissed = False
        self._file_cache: list[str] | None = None

        # wiring filled in at run()
        self._invalidate: Callable[[], None] = lambda: None
        self._print_committed: Callable[[Cell], None] | None = None
        self._app: Application | None = None
        self._buffer: Buffer | None = None

    # ------------------------------------------------------- CellSink
    def emit(self, cell: Cell, *, live: bool) -> Cell:
        cell._sink = self
        if live and not cell.final:
            self.live.append(cell)
            self._invalidate()
        else:
            self._commit(cell)
        return cell

    def cell_changed(self, cell: Cell) -> None:
        if isinstance(cell, StreamingCell):
            self._drain_stream(cell)
            if cell._closed:
                if cell in self.live:  # fully drained into committed chunks
                    self.live.remove(cell)
                self._invalidate()
                return
        if cell in self.live and cell.final:
            self._commit(cell)
        else:
            self._invalidate()

    def _drain_stream(self, cell: StreamingCell) -> None:
        """Commit finalized chunks of a stream to scrollback so only the live tail
        re-renders each frame. The role label rides the first committed chunk only."""
        while True:
            block = cell.take_committable_block()
            if block is None:
                break
            if not block.strip():
                continue  # whitespace-only boundary; skip
            self.emit(
                MessageCell(
                    cell.role,
                    block.strip("\n"),
                    markdown=cell.markdown,
                    label=cell.consume_label(),
                ),
                live=False,
            )

    def cell_remove(self, cell: Cell) -> None:
        if cell in self.live:
            self.live.remove(cell)
            self._invalidate()

    def _commit(self, cell: Cell) -> None:
        if cell in self.live:
            self.live.remove(cell)
        self.committed.append(cell)
        if self._print_committed is not None:
            self._print_committed(cell)
        self._invalidate()

    # ------------------------------------------------------- working spinner
    def spinner(self, label: str):
        engine = self

        class _Working:
            def __enter__(self_):
                self_.cell = SpinnerCell(label)
                engine.emit(self_.cell, live=True)
                return self_.cell

            def __exit__(self_, *exc):
                self_.cell.remove()

        return _Working()

    # ------------------------------------------------------- dispatch
    def set_handler(self, handler: Handler) -> None:
        self._handler = handler

    def set_on_interrupt(self, hook: InterruptHook) -> None:
        self._on_interrupt = hook

    @property
    def busy(self) -> bool:
        return self._current is not None and not self._current.done()

    @property
    def queue_depth(self) -> int:
        return self.queue.qsize()

    def submit_turn(self, text: str) -> None:
        """Enqueue a prompt for the handler (type-ahead safe). Shown as a muted
        ``⋯`` line in the live tail until the dispatcher picks it up."""
        if text:
            self.queue.put_nowait(text)
            self._pending.append(text)
            self._invalidate()

    async def _run_loop(self) -> None:
        while not self._exit.is_set():
            text = await self.queue.get()
            if self._pending:
                self._pending.pop(0)  # it's now running -> stop showing it queued
            assert self._handler is not None
            cancelled = False
            started = time.monotonic()
            self._set_title(working=True)
            self._current = asyncio.create_task(self._handler(text))
            try:
                await self._current
            except asyncio.CancelledError:
                # Distinguish a TURN interrupt (interrupt() cancelled only the child task,
                # so OUR cancelling() count is 0) from the _run_loop task itself being
                # cancelled at shutdown (cancelling() > 0). Re-raise the latter so the loop
                # actually stops instead of swallowing its own cancellation (which hangs exit).
                me = asyncio.current_task()
                if me is not None and me.cancelling() > 0:
                    if self._current is not None:
                        self._current.cancel()
                    raise
                cancelled = True
                if self._on_interrupt is not None:
                    try:
                        await self._on_interrupt()
                    except Exception:
                        pass
                self.emit(NoteCell("⦻ interrupted"), live=False)
            except Exception as e:  # a crashing turn must not kill the session
                self.emit(NoteCell(f"error: {e!r}"), live=False)
            finally:
                self._current = None
                self._finalize_orphans(cancelled)
                self._set_title(working=False)
                elapsed = time.monotonic() - started
                if self._notify_after is not None and elapsed >= self._notify_after:
                    self.notify(f"{self._title or 'xli'}: response ready")
                self._invalidate()

    def _finalize_orphans(self, cancelled: bool) -> None:
        """Sweep any live cells the handler left behind so nothing stays stuck live.

        Context-managed cells (streaming, spinner) finalize on block exit / cancel
        unwind; this catches e.g. a ``running`` tool card the handler never closed.
        """
        for cell in list(self.live):
            if isinstance(cell, SpinnerCell):
                self.live.remove(cell)  # transient; its CM normally removes it
                continue
            if cancelled and isinstance(cell, ToolCell) and cell.status == "running":
                cell.status = "cancelled"
                cell.version += 1
            self._commit(cell)  # graduate leftovers to scrollback

    def interrupt(self) -> bool:
        if self.busy:
            self._current.cancel()  # type: ignore[union-attr]
            return True
        return False

    def tick(self) -> None:
        dirty = False
        spinners = [c for c in self.live if isinstance(c, SpinnerCell)]
        for c in spinners:
            c.tick()
        dirty = dirty or bool(spinners)
        if self._pet:  # advance the ambient pet ~every 0.6s
            self._pet_ticks = (self._pet_ticks + 1) % 6
            if self._pet_ticks == 0:
                self._pet_i = (self._pet_i + 1) % len(self._pet)
                dirty = True
        if dirty:
            self._invalidate()

    # ------------------------------------------------------- notifications / title / links
    def notify(self, message: str, title: str | None = None) -> None:
        """Fire a desktop notification (OSC 9, plus OSC 777 for terminals that prefer it)."""
        name = title or self._title or "xli"
        seq = f"\033]9;{message}\a\033]777;notify;{name};{message}\a"
        try:
            sys.stdout.write(seq)
            sys.stdout.flush()
        except Exception:
            pass

    def _set_title(self, *, working: bool) -> None:
        if not self._title or self._app is None:
            return
        out = self._app.output
        if hasattr(out, "set_title"):
            out.set_title(f"● {self._title}" if working else self._title)

    def _pet_fragment(self) -> tuple[str, str] | None:
        if not self._pet:
            return None
        return ("class:pet", self._pet[self._pet_i % len(self._pet)])

    # ------------------------------------------------------- empty-state intro
    def intro_lines(self, width: int) -> list[str]:
        """Welcome shown in the live region while the transcript is empty.

        App-aware: lists the registered commands so users see what's possible.
        ``intro=""`` disables it; ``intro="..."`` overrides the hint body.
        """
        if self._intro == "":
            return []
        from rich.console import Group
        from rich.text import Text

        t = self.theme
        parts = []
        if self._title:
            parts.append(Text(self._title, style=f"bold {t.assistant_color}"))
        if self._intro:
            parts.append(Text(self._intro, style=t.muted_color))
        else:
            parts.append(
                Text(
                    "Type a message (use @ to mention a file), or a command:",
                    style=t.muted_color,
                )
            )
            names = "  ".join(f"/{c.name}" for c in self._slash.all())
            if names:
                parts.append(Text("  " + names, style=t.muted_color))
        parts.append(
            Text(
                "/help for details · esc interrupts · ctrl-d quits", style=t.muted_color
            )
        )
        lines = render_to_ansi(Group(*parts), width)
        lines.append("")  # breathing room between the welcome and the input dock
        return lines

    # ------------------------------------------------------- inline modals
    #
    # Pattern (matches codex/claude): the *context* commits to scrollback so it
    # auto-scrolls and persists; an arrow-selectable picker shows the choices in the
    # live region; the outcome commits right below the context. Esc cancels.

    async def _pick(self, options: list[tuple[str, str]]) -> str | None:
        """Run an inline arrow-selectable picker; return the chosen key (None on esc)."""
        if not options:  # nothing to choose -> don't open a dead picker
            return None
        fut: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
        self._picker = _Picker(options, fut)
        self._invalidate()
        try:
            return await fut
        finally:
            self._picker = None
            self._invalidate()

    async def approve(
        self, *, title: str, body: str = "", reason: str = ""
    ) -> Decision:
        self.emit(ApprovalCell(title, body, reason), live=False)
        key = await self._pick(
            [
                ("approved", "Yes"),
                ("approved_for_session", "Yes, and don't ask again"),
                ("denied", "No"),
            ]
        )
        decision: Decision = key if key is not None else "aborted"  # type: ignore[assignment]
        approved = decision in ("approved", "approved_for_session")
        color = self.theme.success_color if approved else self.theme.error_color
        self._commit_result(_DECISION.get(decision, f"→ {decision}"), color)
        return decision

    async def confirm(self, question: str) -> bool:
        self.emit(NoteCell(question), live=False)
        result = await self._pick([("yes", "Yes"), ("no", "No")]) == "yes"
        self._commit_result(
            *(
                ("✓ yes", self.theme.success_color)
                if result
                else ("✗ no", self.theme.error_color)
            )
        )
        return result

    async def choose(self, title: str, options: list[tuple[str, str]]) -> str | None:
        if title:
            self.emit(NoteCell(title), live=False)
        key = await self._pick(options)
        if key is not None:
            self._commit_result(
                f"→ {dict(options).get(key, key)}", self.theme.muted_color
            )
        return key

    async def capture_line(self, prompt: str) -> str | None:
        # The composer is the input; record the prompt, then capture the next line.
        self.emit(
            NoteCell(f"{prompt}\n  type your answer below, then enter · esc to cancel"),
            live=False,
        )
        self._line = asyncio.get_running_loop().create_future()
        try:
            value = await self._line
        finally:
            self._line = None
        if value:
            self._commit_result(f"→ {value}", self.theme.muted_color)
        return value

    def _commit_result(self, label: str, color: str) -> None:
        self.emit(CustomCell(Text(label, style=color)), live=False)

    def _picker_lines(self, width: int) -> list[str]:
        p = self._picker
        if not p:
            return []
        rows = []
        for i, (_key, label) in enumerate(p.options):
            chosen = i == p.index
            row = Text()
            row.append(
                f" {'›' if chosen else ' '} {i + 1}. ",
                style=self.theme.command_color if chosen else self.theme.muted_color,
            )
            row.append(label, style=self.theme.command_color if chosen else "default")
            rows.append(row)
        rows.append(
            Text(
                "  ↑↓ select · enter confirm · esc cancel", style=self.theme.muted_color
            )
        )
        return render_to_ansi(Group(*rows), width)

    # ------------------------------------------------------- lifecycle
    def exit(self) -> None:
        self._exit.set()
        if self._app is not None:
            self._app.exit()

    def run(self) -> None:
        try:
            asyncio.run(self._main())
        except (KeyboardInterrupt, EOFError):
            return

    async def _main(self) -> None:
        app = self._build_app()
        self._app = app
        self._invalidate = app.invalidate
        self._set_title(working=False)  # initial idle window title
        # No printed banner — the empty-state intro (in the live region) is the welcome,
        # and it gets out of the way once the first message lands.

        def printer(cell: Cell) -> None:
            width = max(20, shutil.get_terminal_size((80, 24)).columns)
            raw = getattr(cell, "raw_emit", None)
            escape = raw(width) if raw is not None else None
            if escape is not None:  # graphics-protocol image: print the escape as-is
                print(escape)
            else:
                for ln in cell.lines(width, self.theme):
                    print(ln)
            for _ in range(self.theme.item_spacing):
                print()

        self._print_committed = printer

        async def ticker() -> None:
            while True:
                await asyncio.sleep(0.1)
                self.tick()

        tasks = [asyncio.create_task(self._run_loop()), asyncio.create_task(ticker())]
        try:
            with patch_stdout(raw=True):
                await app.run_async()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(
                *tasks, return_exceptions=True
            )  # clean shutdown, no hang

    # ------------------------------------------------------- completion (/ and @)
    #
    # Two triggers share one inline list (rendered below the composer): a leading "/"
    # offers slash commands; an "@token" anywhere offers file paths. _completion_context
    # finds the active trigger + the buffer span to replace on accept.

    def _completion_context(self):
        """Return (kind, prefix, start, end) for the active completion, or None.

        kind ∈ {"slash","file"}; [start,end) is the buffer span replaced on accept.
        """
        if self._buffer is None:
            return None
        text = self._buffer.text
        cursor = self._buffer.cursor_position
        # slash: whole line is "/..." with no space yet (and not an exact command — then
        # the color cue takes over and we hide the list)
        if text.startswith("/") and " " not in text:
            name = text[1:]
            if name and self._slash.get(name.lower()) is not None:
                return None
            return ("slash", name, 0, len(text))
        # file: the whitespace-delimited token ending at the cursor starts with "@"
        before = text[:cursor]
        start = cursor
        while start > 0 and not before[start - 1].isspace():
            start -= 1
        token = text[start:cursor]
        if token.startswith("@"):
            return ("file", token[1:], start, cursor)
        return None

    def _refresh_completion(self, buff: Buffer) -> None:
        # new text: reset selection to the top and un-dismiss so the list tracks typing
        self._sugg_index = 0
        self._suggest_dismissed = False

    def _suggestions(self):
        """Return (ctx, items) where items = list of (label, value, meta)."""
        if self._suggest_dismissed:
            return None, []
        ctx = self._completion_context()
        if ctx is None:
            return None, []
        kind, prefix = ctx[0], ctx[1]
        if kind == "slash":
            items = [
                (f"/{c.name}", c.name, c.description)
                for c in self._slash.match("/" + prefix)
            ]
        else:
            items = [(p, p, "") for p in self._file_search(prefix)]
        return ctx, items

    def _suggest_items(self):
        return self._suggestions()[1]

    def _suggest_visible(self) -> bool:
        return bool(self._suggest_items())

    def _suggest_lines(self, width: int) -> list[str]:
        items = self._suggest_items()
        if not items:
            return []
        sel = max(0, min(self._sugg_index, len(items) - 1))
        t = self.theme
        rows = []
        for i, (label, _value, meta) in enumerate(items):
            chosen = i == sel
            row = Text()
            row.append(
                f" {'›' if chosen else ' '} ",
                style=t.command_color if chosen else t.muted_color,
            )
            row.append(label, style=t.command_color if chosen else t.muted_color)
            if meta:
                row.append(f"   {meta}", style=t.muted_color)
            rows.append(row)
        return render_to_ansi(Group(*rows), width)

    def _move_suggestion(self, delta: int) -> None:
        n = len(self._suggest_items())
        if n:
            self._sugg_index = max(0, min(self._sugg_index + delta, n - 1))
            self._invalidate()

    def _accept_suggestion(self, *, submit: bool) -> None:
        ctx, items = self._suggestions()
        if not items or ctx is None:
            return
        _label, value, _meta = items[max(0, min(self._sugg_index, len(items) - 1))]
        kind, _prefix, start, end = ctx
        buf = self._buffer
        if kind == "slash":
            if submit:  # enter -> run it
                buf.reset()  # type: ignore[union-attr]
                self.submit_turn(f"/{value}")
            else:  # tab -> fill it in
                buf.text = f"/{value} "  # type: ignore[union-attr]
                buf.cursor_position = len(buf.text)  # type: ignore[union-attr]
        else:  # file: insert "@path ", keep composing
            text = buf.text  # type: ignore[union-attr]
            insert = f"@{value} "
            buf.text = text[:start] + insert + text[end:]  # type: ignore[union-attr]
            buf.cursor_position = start + len(insert)  # type: ignore[union-attr]

    # ------------------------------------------------------- file search (@mentions)
    _IGNORE_DIRS = {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".mypy_cache",
        ".pytest_cache",
        ".idea",
        ".tox",
        "target",
        ".next",
    }

    def _all_files(self) -> list[str]:
        if self._file_cache is None:
            import os

            files: list[str] = []
            root = os.getcwd()
            for dp, dns, fns in os.walk(root):
                dns[:] = [
                    d
                    for d in dns
                    if d not in self._IGNORE_DIRS and not d.startswith(".")
                ]
                for fn in fns:
                    files.append(os.path.relpath(os.path.join(dp, fn), root))
                    if len(files) >= 20000:
                        break
                if len(files) >= 20000:
                    break
            self._file_cache = files
        return self._file_cache

    def _file_search(self, prefix: str, limit: int = 12) -> list[str]:
        pl = prefix.lower()
        pre: list[str] = []
        sub: list[str] = []
        for rel in self._all_files():
            rl = rel.lower()
            if not pl or rl.startswith(pl):
                pre.append(rel)
            elif pl in rl:
                sub.append(rel)
        pre.sort(key=lambda p: (len(p), p))
        sub.sort(key=lambda p: (len(p), p))
        return (pre + sub)[:limit]

    # ------------------------------------------------------- pt app
    def _build_app(self) -> Application:
        # We drive completion ourselves via on_text_changed (which fires on *delete* too,
        # unlike complete_while_typing) so the list re-appears on backspace and hides
        # once a command is fully (exactly) typed. History persists across sessions when a
        # history_file is given; ↑/↓ navigate it (prompt_toolkit's default bindings).
        from pathlib import Path

        history = (
            FileHistory(str(Path(self._history_file).expanduser()))
            if self._history_file
            else InMemoryHistory()
        )
        buffer = Buffer(
            multiline=True,
            history=history,
            on_text_changed=self._refresh_completion,
        )
        self._buffer = buffer

        engine = self

        def _ansi_content(lines: list[str]) -> UIContent:
            return UIContent(
                get_line=lambda i: to_formatted_text(ANSI(lines[i])),
                line_count=len(lines),
                show_cursor=False,
            )

        class LiveTail(UIControl):
            def _lines(self, width):
                if (
                    not engine.committed
                    and not engine.live
                    and not engine._pending
                    and engine._picker is None
                ):
                    return engine.intro_lines(width)  # empty-state welcome
                out: list[str] = []
                for cell in engine.live:
                    out.extend(cell.lines(width, engine.theme))
                out.extend(engine._picker_lines(width))  # arrow-select modal
                for text in engine._pending:  # type-ahead, shown muted
                    out.extend(
                        render_to_ansi(
                            Text(f"⋯ {text}", style=engine.theme.muted_color), width
                        )
                    )
                return out

            def create_content(self, width, height):
                return _ansi_content(self._lines(width))

            # required so dont_extend_height sizes the window to its content (not 0)
            def preferred_height(
                self, width, max_available_height, wrap_lines, get_line_prefix
            ):
                return len(self._lines(width))

        class Suggest(UIControl):
            def create_content(self, width, height):
                return _ansi_content(engine._suggest_lines(width))

            def preferred_height(
                self, width, max_available_height, wrap_lines, get_line_prefix
            ):
                return len(engine._suggest_lines(width))

        def status_left():
            frags: list[tuple[str, str]] = [
                (
                    "class:status.busy" if engine.busy else "class:status.idle",
                    " working" if engine.busy else " idle",
                )
            ]
            body = engine._status.render()
            if body:
                frags.append(("class:status", "  ·  "))
                frags.extend(("class:status", t) for _, t in body)
            frags.append(
                ("class:status", "   enter send · esc interrupt · ctrl-d quit")
            )
            return frags

        class Status(UIControl):
            def create_content(self, width, height):
                frags = list(status_left())
                pet = engine._pet_fragment()
                if pet:  # park the pet bottom-right
                    used = sum(len(t) for _s, t in frags) + len(pet[1])
                    frags.append(("class:status", " " * max(1, width - used)))
                    frags.append(pet)
                return UIContent(
                    get_line=lambda i: frags, line_count=1, show_cursor=False
                )

        # dont_extend_height keeps every region sized to its CONTENT — without it a
        # flexible window (composer) greedily absorbs vertical slack and pads blank
        # lines below the input.
        live_win = Window(
            content=LiveTail(), height=Dimension(min=0), dont_extend_height=True
        )
        sep_win = Window(height=1, char="─", style="class:sep")
        composer_win = Window(
            content=BufferControl(buffer=buffer, lexer=SlashLexer(self._slash)),
            height=Dimension(min=1),
            wrap_lines=True,
            dont_extend_height=True,
            get_line_prefix=lambda *a: [
                ("class:prompt", f" {self.theme.prompt_glyph} ")
            ],
        )
        status_win = Window(content=Status(), height=1)

        # Command suggestions are our own list rendered directly BELOW the composer
        # (Claude-style) — themed via the rich bridge, no solid-bg popup, no float math.
        # It collapses to 0 height when there's nothing to suggest.
        suggest_win = ConditionalContainer(
            Window(content=Suggest(), height=Dimension(min=0), dont_extend_height=True),
            filter=Condition(lambda: engine._suggest_visible()),
        )
        root = HSplit([live_win, sep_win, composer_win, suggest_win, status_win])
        layout = Layout(root, focused_element=composer_win)

        return Application(
            layout=layout,
            key_bindings=self._key_bindings(),
            style=self._style(),
            full_screen=False,
            mouse_support=False,  # keep native text selection working
            refresh_interval=0.1,  # steady repaint for live animations
        )

    def _key_bindings(self) -> KeyBindings:
        kb = KeyBindings()
        engine = self

        picking = Condition(lambda: engine._picker is not None)
        capturing = Condition(lambda: engine._line is not None)
        suggesting = Condition(lambda: engine._suggest_visible())
        composing = ~picking & ~capturing  # normal composer-editing context

        # --- line capture (ui.input) ---
        @kb.add("enter", filter=capturing)
        def _(event):
            text = engine._buffer.text  # type: ignore[union-attr]
            engine._buffer.reset()  # type: ignore[union-attr]
            if engine._line and not engine._line.done():
                engine._line.set_result(text)

        # --- arrow-selectable picker (approve / confirm / pick / wizard) ---
        @kb.add("up", filter=picking)
        @kb.add("c-p", filter=picking)
        def _(event):
            if engine._picker:
                engine._picker.move(-1)
                engine._invalidate()

        @kb.add("down", filter=picking)
        @kb.add("c-n", filter=picking)
        def _(event):
            if engine._picker:
                engine._picker.move(1)
                engine._invalidate()

        @kb.add("enter", filter=picking)
        def _(event):
            p = engine._picker
            if p:
                p.resolve(p.options[p.index][0])

        def _digit(d: int):  # 1-9 quick-select
            @kb.add(str(d), filter=picking)
            def _(event):
                p = engine._picker
                if p and d - 1 < len(p.options):
                    p.resolve(p.options[d - 1][0])

        for _d in range(1, 10):
            _digit(_d)

        # --- command suggestions (only while composing) ---
        @kb.add("enter", filter=suggesting & composing)
        def _(event):
            engine._accept_suggestion(submit=True)

        @kb.add("tab", filter=suggesting & composing)
        def _(event):
            engine._accept_suggestion(submit=False)

        @kb.add("down", filter=suggesting & composing)
        def _(event):
            engine._move_suggestion(1)

        @kb.add("up", filter=suggesting & composing)
        def _(event):
            engine._move_suggestion(-1)

        # --- normal submit ---
        @kb.add("enter", filter=composing & ~suggesting)
        def _(event):
            text = engine._buffer.text.rstrip()  # type: ignore[union-attr]
            if text:
                engine._buffer.append_to_history()  # persist for ↑/↓ recall
            engine._buffer.reset()  # type: ignore[union-attr]
            if text:
                engine.submit_turn(text)

        @kb.add("c-j")  # newline (also alt+enter)
        @kb.add("escape", "enter")
        def _(event):
            event.current_buffer.insert_text("\n")

        @kb.add("escape", eager=True)
        def _(event):
            if engine._picker is not None:
                engine._picker.resolve(None)  # cancel the choice
            elif engine._line is not None:
                _resolve(engine._line, None)
            elif engine._suggest_visible():
                engine._suggest_dismissed = True  # close the command list
            else:
                engine.interrupt()

        @kb.add("c-c")
        def _(event):
            engine.interrupt()

        @kb.add("c-d")
        def _(event):
            engine.exit()

        return kb

    def _style(self) -> Style:
        t = self.theme
        prompt = _to_pt(t.prompt_color)
        if t.prompt_bg:
            prompt = f"{prompt} bg:{t.prompt_bg}"
        return Style.from_dict(
            {
                "sep": _to_pt(t.muted_color),
                "prompt": prompt or "",
                "slash": _to_pt(t.command_color),
                "status": _to_pt(t.status_color),
                "status.busy": f"{_to_pt(t.warning_color)} bold",
                "status.idle": _to_pt(t.success_color),
                "pet": _to_pt(t.muted_color),
            }
        )


class _Picker:
    """Transient arrow-selectable choice list, rendered in the live region."""

    def __init__(self, options: list[tuple[str, str]], future: asyncio.Future) -> None:
        self.options = list(options)  # [(key, label), ...]
        self.index = 0
        self.future = future

    def move(self, delta: int) -> None:
        self.index = (self.index + delta) % len(self.options)

    def resolve(self, key: str | None) -> None:
        if not self.future.done():
            self.future.set_result(key)


def _resolve(fut: asyncio.Future | None, value) -> None:
    if fut is not None and not fut.done():
        fut.set_result(value)


# Decision -> committed result label. The color is resolved from the theme at the call
# site (success vs error) so it honors the active palette.
_DECISION = {
    "approved": "✓ approved",
    "approved_for_session": "✓ approved (always)",
    "denied": "✗ denied",
    "aborted": "⦻ aborted",
}


# Rich color name -> prompt_toolkit style fragment (best effort; unknowns pass through).
_ANSI = {
    "black": "ansiblack",
    "red": "ansired",
    "green": "ansigreen",
    "yellow": "ansiyellow",
    "blue": "ansiblue",
    "magenta": "ansimagenta",
    "cyan": "ansicyan",
    "white": "ansiwhite",
    "grey50": "ansibrightblack",
    "grey46": "ansibrightblack",
    "bright_black": "ansibrightblack",
    "bright_red": "ansibrightred",
    "bright_green": "ansibrightgreen",
    "bright_yellow": "ansibrightyellow",
    "bright_blue": "ansibrightblue",
    "bright_magenta": "ansibrightmagenta",
    "bright_cyan": "ansibrightcyan",
    "bright_white": "ansibrightwhite",
    "default": "",
}


def _to_pt(rich_color: str) -> str:
    mods, color = [], None
    for part in (rich_color or "").split():
        if part in {"bold", "italic", "underline", "reverse", "dim"}:
            mods.append(part)
        elif part.startswith("#"):
            color = part
        else:
            color = _ANSI.get(part, "")
    return " ".join([*mods, color or ""]).strip()
