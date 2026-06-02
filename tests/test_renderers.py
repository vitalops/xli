"""Pure renderer tests — assert text output via Rich's record/export."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from xli.render import (
    render_diff,
    render_message,
    render_plan,
    render_reasoning,
    render_tool,
)
from xli.theme import CODEX, MINIMAL


def _render(renderable, *, theme=CODEX) -> str:
    """Render to a stripped string."""
    out = Console(file=StringIO(), force_terminal=False, width=80, no_color=True)
    out.print(renderable)
    return out.file.getvalue()


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def test_user_message_has_role_label() -> None:
    text = _render(render_message("hi", role="user", theme=CODEX))
    assert "you" in text
    assert "hi" in text


def test_assistant_message_renders_markdown() -> None:
    text = _render(render_message("**bold** text", role="assistant", theme=CODEX))
    assert "bold" in text


def test_system_message() -> None:
    text = _render(render_message("system note", role="system", theme=CODEX))
    assert "system" in text
    assert "system note" in text


def test_minimal_theme_drops_color_glyphs() -> None:
    out = _render(render_message("hi", role="user", theme=MINIMAL))
    # No special user_color marker — text just shows up
    assert "hi" in out


def test_boxed_theme_renders_panel_without_crashing() -> None:
    from xli.theme import BOXED

    # regression: the boxed theme (use_borders=True) used to pass an invalid `box_style`
    # kwarg to rich.Panel — it must render a bordered message cleanly.
    out = _render(render_message("hi there", role="assistant", theme=BOXED))
    assert "hi there" in out
    assert "─" in out or "╭" in out          # some box drawing present


# ---------------------------------------------------------------------------
# Tool calls
# ---------------------------------------------------------------------------


def test_tool_call_shell_shows_command() -> None:
    text = _render(
        render_tool("shell", args={"command": ["ls", "-la"]}, output="total 48", theme=CODEX)
    )
    assert "shell" in text
    assert "ls -la" in text
    assert "total 48" in text


def test_tool_apply_patch_summary() -> None:
    text = _render(
        render_tool(
            "apply_patch",
            args={"patch": "*** Add File: foo.txt\n*** Update File: bar.py"},
            output={"applied": [{"path": "foo.txt"}]},
            theme=CODEX,
        )
    )
    assert "apply_patch" in text
    assert "2 changes" in text


def test_tool_error_marks_as_error() -> None:
    text = _render(
        render_tool("shell", args={"command": ["false"]}, error="exit=1", theme=CODEX)
    )
    assert "error: exit=1" in text


def test_tool_with_no_output_renders_title_only() -> None:
    text = _render(render_tool("shell", args={"command": ["ls"]}, theme=CODEX))
    assert "shell" in text
    assert "ls" in text


def test_tool_truncates_long_output() -> None:
    text = _render(render_tool("shell", args={"command": ["x"]}, output="x" * 20000, theme=CODEX))
    # Output gets clipped to ~8000 chars; the printed text contains an ellipsis
    assert "…" in text


def test_tool_generic_args_renders_json() -> None:
    text = _render(
        render_tool("unknown-tool", args={"a": 1, "b": "hi"}, output="ok", theme=CODEX)
    )
    assert "unknown-tool" in text
    assert "a" in text and "b" in text


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


def test_diff_with_path_renders_header() -> None:
    text = _render(
        render_diff("--- a/x\n+++ b/x\n@@\n-old\n+new", path="x.py", theme=CODEX)
    )
    assert "diff" in text
    assert "x.py" in text
    assert "+new" in text
    assert "-old" in text


def test_diff_without_path() -> None:
    text = _render(render_diff("--- a/x\n+++ b/x\n+new\n", theme=CODEX))
    assert "+new" in text


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def test_plan_renders_glyphs() -> None:
    text = _render(
        render_plan(
            [("explore", "completed"), ("write", "in_progress"), ("ship", "pending")],
            theme=CODEX,
        )
    )
    assert "☑" in text
    assert "▸" in text
    assert "☐" in text


def test_plan_accepts_dicts_and_strings() -> None:
    text = _render(
        render_plan(
            [
                {"title": "a", "status": "completed", "notes": "done"},
                "b",
            ],
            theme=CODEX,
        )
    )
    assert "a" in text
    assert "b" in text
    assert "done" in text


def test_plan_minimal_uses_ascii() -> None:
    text = _render(render_plan([("x", "completed")], theme=MINIMAL))
    assert "[x]" in text


# ---------------------------------------------------------------------------
# Reasoning
# ---------------------------------------------------------------------------


def test_reasoning_renders_with_rail() -> None:
    text = _render(render_reasoning("thinking about life", theme=CODEX))
    assert "│" in text
    assert "thinking" in text


def test_reasoning_multiline() -> None:
    text = _render(render_reasoning("line one\nline two", theme=CODEX))
    assert "line one" in text
    assert "line two" in text
