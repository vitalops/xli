"""Render tool calls.

Each tool call is a compact card:

    ▸ shell  ls -la
      total 48
      drwxr-xr-x 8 ...

Title line uses the tool glyph + name + a short summary; the output is
indented. When output is missing or empty, just the title shows.
"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.text import Text

from ..theme import Theme

_MAX_TITLE_DETAIL = 100
_MAX_OUTPUT_INLINE = 8000


def render_tool(
    name: str,
    *,
    args: dict[str, Any] | None = None,
    output: Any = None,
    error: str | None = None,
    status: str | None = None,
    theme: Theme,
) -> RenderableType:
    args = args or {}
    title = _title_for(name, args, theme=theme, errored=error is not None, status=status)
    if output is None and error is None:
        return title
    body_text = _body_for(output, error)
    if not body_text:
        return title
    body = Padding(
        Text(body_text, style=theme.muted_color, no_wrap=False),
        (0, 0, 0, theme.tool_output_indent),
    )
    return Group(title, body)


def _title_for(
    name: str, args: dict[str, Any], *, theme: Theme, errored: bool, status: str | None = None
) -> Text:
    # Status drives the gutter glyph + accent so a card reads at a glance as it
    # moves running -> done. When no status is given we keep the plain tool glyph
    # (back-compat with one-shot ``ui.tool(...)`` cards).
    if errored or status == "error":
        color, glyph = theme.error_color, theme.tool_error_glyph
    elif status == "cancelled":
        color, glyph = theme.error_color, theme.tool_cancelled_glyph
    elif status == "done":
        color, glyph = theme.success_color, theme.tool_done_glyph
    else:  # running / None
        color, glyph = theme.tool_color, theme.tool_glyph
    summary = _summary_for(name, args)
    title = Text()
    title.append(f"{glyph} ", style=color)
    title.append(name, style=f"bold {color}")
    if summary:
        title.append("  ")
        title.append(summary, style=theme.muted_color)
    return title


def _summary_for(name: str, args: dict[str, Any]) -> str:
    if name == "shell":
        return _truncate(" ".join(args.get("command", []) or args.get("argv", [])), _MAX_TITLE_DETAIL)
    if name == "apply_patch":
        patch = args.get("patch", "")
        n = (
            patch.count("*** Add File:")
            + patch.count("*** Update File:")
            + patch.count("*** Delete File:")
        ) or 1
        return f"({n} change{'s' if n != 1 else ''})"
    if name == "view_image":
        return str(args.get("path", ""))
    if name == "save_artifact":
        return str(args.get("path", ""))
    if name == "read_artifact":
        return str(args.get("path", ""))
    if name == "web_search":
        return str(args.get("query", ""))
    if name == "update_plan":
        steps = args.get("steps") or []
        return f"({len(steps)} step{'s' if len(steps) != 1 else ''})"
    if name == "remember":
        return _truncate(str(args.get("content", "")), _MAX_TITLE_DETAIL)
    if name == "task":
        sub = args.get("subagent_type", "")
        desc = args.get("description", "")
        return _truncate(f"[{sub}] {desc}".strip(), _MAX_TITLE_DETAIL) if (sub or desc) else ""
    # generic fallback
    if args:
        return _truncate(json.dumps(args, default=str, separators=(",", ":")), _MAX_TITLE_DETAIL)
    return ""


def _body_for(output: Any, error: str | None) -> str:
    if error:
        return f"error: {error}"
    if output is None:
        return ""
    if isinstance(output, str):
        return _truncate(output, _MAX_OUTPUT_INLINE)
    if isinstance(output, (bytes, bytearray)):
        return f"<{len(output)} bytes>"
    try:
        return _truncate(json.dumps(output, default=str, indent=2), _MAX_OUTPUT_INLINE)
    except Exception:  # pragma: no cover
        return _truncate(repr(output), _MAX_OUTPUT_INLINE)


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
