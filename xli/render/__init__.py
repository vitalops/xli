"""Renderers — pure functions from data → Rich renderables.

Each module returns a ``rich.console.RenderableType``. The :class:`xli.UI`
prints these into the transcript. They're pure so they can be tested
without a terminal and reused outside the UI loop.
"""

from .diff import render_diff
from .message import render_message, render_streaming_message
from .plan import render_plan
from .reasoning import render_reasoning
from .tool import render_tool

__all__ = [
    "render_diff",
    "render_message",
    "render_plan",
    "render_reasoning",
    "render_streaming_message",
    "render_tool",
]
