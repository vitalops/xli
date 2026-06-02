"""The :class:`UI` — xli's one public entry point.

Idioms (one way to do each thing, Pythonic):

* **Register handlers with decorators.** ``@ui.on_prompt``, ``@ui.command(name)``,
  ``@ui.renderer(name)``, ``@ui.on_interrupt``.
* **Stream with a context manager.** ``with ui.streaming("assistant") as out: ...``
* **Mutate cards with handles.** ``card = ui.tool(...); card.update(status="done")``
* **Show work with a spinner.** ``with ui.working("thinking"): ...``
* **Approve / pick with await.** ``await ui.approve(...)`` / ``await ui.pick(...)``
* **Run with ``ui.run()``.** That's it.

The transcript is inline: finalized cells live in your terminal's normal scrollback
(selectable, scrollable); only the active tail at the bottom redraws. Nothing in this
module knows about LLMs or agents — you decide what the events mean.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any

from rich.console import RenderableType
from rich.text import Text

from .approval import Decision
from .cells import (
    Cell,
    CustomCell,
    DiffCell,
    ImageCell,
    MessageCell,
    NoteCell,
    PlanCell,
    ReasoningCell,
    StreamingCell,
    ToolCell,
)
from .engine import Engine
from .pets import frames as pet_frames
from .slash import Handler, SlashCommand, SlashRegistry
from .status import StatusBar
from .theme import Theme, ThemeName, resolve
from .wizard import Step
from .wizard import step as _step

PromptHandler = Callable[[str], Awaitable[None] | None]
EventRenderer = Callable[["UI", Any], None]
InterruptHandler = Callable[[], Awaitable[None] | None]


class UI:
    """The xli app. Construct, register handlers, call ``ui.run()``."""

    def __init__(
        self,
        *,
        title: str | None = None,
        intro: str | None = None,
        theme: Theme | ThemeName | None = None,
        status_fields: Sequence[str] = (),
        history_file: str | None = None,
        slash_commands: Iterable[SlashCommand] = (),
        pet: str | Sequence[str] | None = None,
        notify_after: float | None = None,
    ) -> None:
        self.title = title
        self.theme: Theme = resolve(theme)
        self.status = StatusBar(fields=status_fields, theme=self.theme)
        self._slash = SlashRegistry()
        for cmd in slash_commands:
            self._slash.register(cmd)
        self._prompt_handler: PromptHandler | None = None
        self._interrupt_handler: InterruptHandler | None = None
        self._renderers: dict[str, EventRenderer] = {}
        self._register_builtin_commands()
        self._engine = Engine(
            theme=self.theme,
            slash=self._slash,
            status=self.status,
            title=title,
            intro=intro,
            history_file=history_file,
            pet=pet_frames(pet),
            notify_after=notify_after,
        )

    # ----------------------------------------------------- decorators
    def on_prompt(self, fn: PromptHandler) -> PromptHandler:
        """Register the handler called once per user submission (raw prompt text)."""
        self._prompt_handler = fn
        return fn

    def on_interrupt(self, fn: InterruptHandler) -> InterruptHandler:
        """Register a cleanup hook fired when the user interrupts a turn (ESC).

        For releasing resources — it should not write to the transcript (the library
        already emits a single interrupt marker).
        """
        self._interrupt_handler = fn
        return fn

    def command(
        self,
        name: str,
        *,
        description: str = "",
        aliases: Sequence[str] = (),
    ) -> Callable[[Handler], Handler]:
        """Register a slash command: ``@ui.command("model", description=...)``."""

        def decorator(fn: Handler) -> Handler:
            self._slash.register(
                SlashCommand(
                    name=name,
                    handler=fn,
                    description=description,
                    aliases=tuple(aliases),
                )
            )
            return fn

        return decorator

    def renderer(self, event_type: str) -> Callable[[EventRenderer], EventRenderer]:
        """Register a custom renderer for events dispatched via ``ui.dispatch``."""

        def decorator(fn: EventRenderer) -> EventRenderer:
            self._renderers[event_type] = fn
            return fn

        return decorator

    # ----------------------------------------------------- transcript API
    def print(self, renderable: RenderableType) -> Cell:
        """Append any Rich renderable to the transcript. Returns its cell handle."""
        return self._engine.emit(CustomCell(renderable), live=False)

    def message(self, role: str, text: str, *, markdown: bool | None = None) -> Cell:
        """One-shot message. Returns a handle you can ``.update(text=...)``."""
        return self._engine.emit(
            MessageCell(_normalize_role(role), text, markdown=markdown), live=False
        )

    def header(self, text: str) -> Cell:
        """A single muted banner line for runtime context (e.g. ``app · model · mode``)."""
        return self._engine.emit(
            CustomCell(Text(text, style=self.theme.muted_color)), live=False
        )

    def note(self, text: str) -> Cell:
        """Single muted ``· line`` — good for status updates."""
        return self._engine.emit(NoteCell(text), live=False)

    def tool(
        self,
        name: str,
        *,
        args: dict[str, Any] | None = None,
        output: Any = None,
        error: str | None = None,
        status: str | None = None,
    ) -> ToolCell:
        """A tool-call card. Pass ``status="running"`` to keep it live + mutable; it
        commits to scrollback when you ``.update(status="done")`` (or "error"/"cancelled").
        Omit ``status`` for a one-shot card."""
        cell = ToolCell(name, args=args, output=output, error=error, status=status)
        return self._engine.emit(cell, live=status == "running")  # type: ignore[return-value]

    def diff(self, diff: str, *, path: str | None = None) -> Cell:
        return self._engine.emit(DiffCell(diff, path=path), live=False)

    def plan(self, steps: Iterable[Any], *, title: str | None = None) -> Cell:
        return self._engine.emit(PlanCell(steps, title=title), live=False)

    def reasoning(self, summary: str) -> Cell:
        return self._engine.emit(ReasoningCell(summary), live=False)

    def image(self, source: Any, *, width_cols: int = 48) -> Cell:
        """Render an inline image (path / bytes / PIL image) as a transcript cell.

        Uses the terminal's graphics protocol (kitty / iTerm2) when available, else a
        half-block fallback. See ``XLI_IMAGE_PROTOCOL`` to override detection.
        """
        return self._engine.emit(ImageCell(source, width_cols=width_cols), live=False)

    def link(self, label: str, url: str) -> Cell:
        """Commit a clickable hyperlink (OSC 8) line to the transcript."""
        return self.print(Text(label, style=f"link {url} {self.theme.user_color}"))

    def notify(self, message: str, *, title: str | None = None) -> None:
        """Fire a desktop notification (OSC 9 / OSC 777)."""
        self._engine.notify(message, title)

    def streaming(self, role: str, *, markdown: bool | None = None) -> Streaming:
        """Context manager for streamed text. Renders live, commits on exit::

        with ui.streaming("assistant") as out:
            for chunk in chunks:
                out.write(chunk)
        """
        return Streaming(self, role=_normalize_role(role), markdown=markdown)

    def working(self, label: str = "working"):
        """Context manager showing an animated spinner in the live tail while the block runs."""
        return self._engine.spinner(label)

    # ----------------------------------------------------- approvals + modals
    async def approve(
        self, *, title: str, body: str = "", reason: str = ""
    ) -> Decision:
        """Inline approval prompt. Blocks until y / a / n / esc."""
        return await self._engine.approve(title=title, body=body, reason=reason)

    async def confirm(self, question: str, *, title: str = "Confirm") -> bool:
        return await self._engine.confirm(question)

    async def input(
        self, question: str, *, title: str = "Input", default: str = ""
    ) -> str | None:
        prompt = question if not default else f"{question} [{default}]"
        text = await self._engine.capture_line(f"{prompt}  (enter)")
        if text is None:
            return None
        return text or default

    async def pick(
        self, title: str, items: Sequence[str | tuple[str, str]]
    ) -> str | None:
        """Arrow-selectable picker (↑/↓ · 1-9 · enter · esc). Returns the chosen key
        (or the item itself for plain strings), or None if cancelled."""
        options = [it if isinstance(it, tuple) else (it, it) for it in items]
        return await self._engine.choose(title, options)

    #: Build wizard steps: ``ui.step.pick(...) / .confirm(...) / .text(...)``.
    step = _step

    async def wizard(self, steps: Iterable[Step]) -> dict[str, Any] | None:
        """Run a sequence of steps; return {key: answer}, or None if any step is cancelled."""
        answers: dict[str, Any] = {}
        for s in steps:
            if s.kind == "pick":
                ans: Any = await self.pick(s.prompt, s.options)
            elif s.kind == "confirm":
                ans = await self.confirm(s.prompt)
            else:
                ans = await self.input(s.prompt, default=s.default)
            if ans is None:
                return None
            answers[s.key] = ans
        return answers

    # ----------------------------------------------------- generic dispatch
    def dispatch(self, event: Any) -> None:
        """Route an event to a registered ``@ui.renderer``; falls back to printing repr."""
        kind = (
            event["type"] if isinstance(event, dict) else getattr(event, "type", None)
        )
        fn = self._renderers.get(kind) if kind else None
        if fn is None:
            self.print(Text(repr(event)))
            return
        fn(self, event)

    # ----------------------------------------------------- lifecycle
    def clear_transcript(self) -> None:
        """Clear the visible screen (terminal scrollback may retain history)."""
        self._engine.committed.clear()
        self._engine.live.clear()
        print("\033[2J\033[3J\033[H", end="", flush=True)

    def exit(self) -> None:
        """Stop the run loop."""
        self._engine.exit()

    def run(self) -> None:
        """Block on the event loop until the user quits."""
        if self._prompt_handler is None:
            raise RuntimeError(
                "No @ui.on_prompt handler registered. Did you forget the decorator?"
            )
        self._engine.set_handler(self._handle_one)
        if self._interrupt_handler is not None:
            self._engine.set_on_interrupt(self._interrupt_async)
        self._engine.run()

    async def _interrupt_async(self) -> None:
        await _maybe_await(self._interrupt_handler())  # type: ignore[misc]

    async def _handle_one(self, prompt: str) -> None:
        if prompt.startswith("/"):
            cmd, args = self._slash.parse(prompt)
            if cmd is None:
                self.note(f"unknown command: {prompt.split()[0]}")
                return
            await _maybe_await(cmd.handler(self, args))
            return
        self.message("user", prompt)  # echo (the composer clears on submit)
        assert self._prompt_handler is not None
        await _maybe_await(self._prompt_handler(prompt))

    # ----------------------------------------------------- builtin commands
    def _register_builtin_commands(self) -> None:
        async def cmd_help(ui: UI, args: str) -> None:
            ui._print_help()

        async def cmd_quit(ui: UI, args: str) -> None:
            ui.exit()

        async def cmd_clear(ui: UI, args: str) -> None:
            ui.clear_transcript()

        self._slash.register(
            SlashCommand(
                "help", description="show commands", handler=cmd_help, aliases=("?",)
            )
        )
        self._slash.register(
            SlashCommand(
                "quit", description="exit", handler=cmd_quit, aliases=("q", "exit")
            )
        )
        self._slash.register(
            SlashCommand("clear", description="clear the transcript", handler=cmd_clear)
        )

    def _print_help(self) -> None:
        lines = ["commands"]
        for cmd in self._slash.all():
            alias = (
                f"  ({', '.join('/' + a for a in cmd.aliases)})" if cmd.aliases else ""
            )
            lines.append(f"  /{cmd.name:<14} {cmd.description}{alias}")
        lines += [
            "",
            "keys",
            "  enter — send  ·  alt+enter / ctrl+j — newline",
            "  esc — interrupt the current turn  ·  ctrl+d — quit",
            "  y / a / n — accept / always / deny when an approval is active",
        ]
        self.print(Text("\n".join(lines), style=self.theme.muted_color))


# ---------------------------------------------------------------------------
# Streaming context manager
# ---------------------------------------------------------------------------


class Streaming:
    """Yielded by :meth:`UI.streaming`. Live while open, commits to scrollback on exit."""

    def __init__(self, ui: UI, *, role: str, markdown: bool | None) -> None:
        self._cell = StreamingCell(role, markdown=markdown)
        self._engine = ui._engine

    def __enter__(self) -> Streaming:
        self._engine.emit(self._cell, live=True)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._cell.close()

    def write(self, chunk: str) -> None:
        self._cell.append(chunk)

    @property
    def text(self) -> str:
        return self._cell.text


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _normalize_role(role: str) -> str:
    role = role.lower()
    if role not in {"user", "assistant", "system"}:
        return "system"
    return role
