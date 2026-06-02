"""Status bar — named fields rendered into prompt_toolkit's bottom toolbar.

Usage from a UI handler::

    ui.status.set(model="gpt-5-codex", tokens="3.2k/400k")

Only fields listed in :class:`UI`'s ``status_fields`` are rendered; that
keeps the bar tidy and the order stable.
"""

from __future__ import annotations

from collections.abc import Iterable

from prompt_toolkit.formatted_text import FormattedText

from .theme import Theme


class StatusBar:
    """Tracks named-field state. Used by the Composer's bottom toolbar callable."""

    def __init__(
        self,
        *,
        fields: Iterable[str],
        theme: Theme,
    ) -> None:
        self._order = tuple(fields)
        self._values: dict[str, str] = {f: "" for f in self._order}
        self._theme = theme

    def set(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            if key not in self._values:
                # Unknown fields are silently ignored — UIs evolve; better
                # than throwing in the middle of a turn.
                continue
            self._values[key] = "" if value is None else str(value)

    def get(self, name: str) -> str:
        return self._values.get(name, "")

    def render(self) -> FormattedText:
        """Render as prompt_toolkit ``FormattedText`` for the bottom toolbar."""
        parts: list[tuple[str, str]] = []
        first = True
        for name in self._order:
            value = self._values.get(name, "")
            if not value:
                continue
            if not first:
                parts.append(("class:status-sep", self._theme.status_separator))
            parts.append(("class:status", value))
            first = False
        return FormattedText(parts)

    def is_empty(self) -> bool:
        return not any(self._values.values())
