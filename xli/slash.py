"""Slash command registry + prompt_toolkit completer.

User-facing API:

    @ui.command("model", description="switch model", aliases=["m"])
    async def cmd_model(ui, args): ...

Internally we keep one registry per :class:`UI` instance.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.lexers import Lexer

if TYPE_CHECKING:
    from .ui import UI


Handler = Callable[["UI", str], Awaitable[None]]


@dataclass(frozen=True)
class SlashCommand:
    """One registered slash command."""

    name: str
    handler: Handler
    description: str = ""
    aliases: tuple[str, ...] = ()


class SlashRegistry:
    """Per-UI command registry. Supports aliases + prefix lookup."""

    def __init__(self) -> None:
        self._by_name: dict[str, SlashCommand] = {}

    def register(self, cmd: SlashCommand) -> None:
        self._by_name[cmd.name] = cmd
        for alias in cmd.aliases:
            self._by_name[alias] = cmd

    def unregister(self, name: str) -> None:
        cmd = self._by_name.pop(name, None)
        if cmd is None:
            return
        for alias in cmd.aliases:
            self._by_name.pop(alias, None)

    def get(self, name: str) -> SlashCommand | None:
        return self._by_name.get(name)

    def all(self) -> list[SlashCommand]:
        """Each canonical command once (aliases deduped)."""
        seen: set[str] = set()
        out: list[SlashCommand] = []
        for cmd in self._by_name.values():
            if cmd.name in seen:
                continue
            seen.add(cmd.name)
            out.append(cmd)
        out.sort(key=lambda c: c.name)
        return out

    def match(self, prefix: str, *, limit: int = 12) -> list[SlashCommand]:
        prefix = prefix.lstrip("/").lower()
        if not prefix:
            return self.all()[:limit]
        out: list[SlashCommand] = []
        seen: set[str] = set()
        # Names that start with the prefix first.
        for cmd in self.all():
            if cmd.name.startswith(prefix):
                out.append(cmd)
                seen.add(cmd.name)
        # Then aliases that start with prefix (but commands not yet listed).
        for name, cmd in self._by_name.items():
            if cmd.name in seen:
                continue
            if name.startswith(prefix):
                out.append(cmd)
                seen.add(cmd.name)
        return out[:limit]

    def parse(self, line: str) -> tuple[SlashCommand | None, str]:
        """Split ``/<name> <args>`` → (cmd-or-None, args)."""
        if not line.startswith("/"):
            return None, line
        body = line[1:].lstrip()
        name, _, args = body.partition(" ")
        return self.get(name.lower()), args


class SlashCompleter(Completer):
    """prompt_toolkit completer for slash commands.

    Active only when the buffer starts with ``/`` and contains no spaces yet.
    Yields each matching command name as a completion.
    """

    def __init__(self, registry: SlashRegistry) -> None:
        self.registry = registry

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        if " " in text:
            return
        prefix = text[1:]
        for cmd in self.registry.match("/" + prefix):
            yield Completion(
                cmd.name,
                start_position=-len(prefix),
                display=f"/{cmd.name}",
                display_meta=cmd.description,
            )


class SlashLexer(Lexer):
    """Highlight a *recognized* ``/command`` in the composer.

    The moment the typed first word is an exact registered command (or alias), the
    ``/name`` token is styled with ``class:slash`` — a recognition cue. While it's only
    a partial match (``/imag``) it stays default-colored, so the color flips exactly at
    the full-match boundary and reverts on backspace. Arguments after the command and
    any non-command text render normally.
    """

    def __init__(self, registry: SlashRegistry, style: str = "class:slash") -> None:
        self.registry = registry
        self.style = style

    def lex_document(self, document: Document):
        lines = document.lines

        def get_line(lineno: int):
            text = lines[lineno] if lineno < len(lines) else ""
            if lineno == 0 and text.startswith("/"):
                name, sep, rest = text[1:].partition(" ")
                if name and self.registry.get(name.lower()) is not None:
                    frags = [(self.style, "/" + name)]
                    if sep:
                        frags.append(("", sep + rest))
                    return frags
            return [("", text)]

        return get_line
