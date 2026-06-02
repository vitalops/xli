"""xli — terminal interfaces for transcript-style agent / chat apps.

The public surface is intentionally tiny. Most users only need::

    import xli

    ui = xli.UI()

    @ui.on_prompt
    async def reply(prompt: str) -> None:
        with ui.streaming("assistant") as out:
            out.write(f"You said: {prompt}")

    ui.run()

See ``README.md`` for the full cookbook and ``docs/`` for design + theming guides.
"""

from __future__ import annotations

from .cells import Cell
from .slash import SlashCommand
from .theme import BOXED, CODEX, MINIMAL, Theme
from .ui import UI, Streaming

__all__ = [
    "BOXED",
    "CODEX",
    "Cell",
    "MINIMAL",
    "SlashCommand",
    "Streaming",
    "Theme",
    "UI",
    "__version__",
]

__version__ = "0.2.0"
