"""Contract tests for the UI public surface."""

from __future__ import annotations

import xli
from xli.status import StatusBar
from xli.theme import CODEX, MINIMAL


def test_ui_constructs_with_no_arguments() -> None:
    ui = xli.UI()
    assert ui.theme is CODEX
    # Built-in commands are registered
    names = {c.name for c in ui._slash.all()}
    assert {"help", "quit", "clear"} <= names


def test_ui_title_and_theme_name() -> None:
    ui = xli.UI(title="foo", theme="minimal")
    assert ui.title == "foo"
    assert ui.theme is MINIMAL


def test_ui_status_fields_round_trip() -> None:
    ui = xli.UI(status_fields=("model", "tokens"))
    ui.status.set(model="x")
    ui.status.set(tokens="100")
    assert ui.status.get("model") == "x"
    assert ui.status.get("tokens") == "100"


def test_ui_status_ignores_unknown_fields() -> None:
    ui = xli.UI(status_fields=("model",))
    ui.status.set(model="x", tokens="100")  # tokens silently dropped
    assert ui.status.get("model") == "x"
    assert ui.status.get("tokens") == ""


def test_ui_command_decorator_registers() -> None:
    ui = xli.UI()

    @ui.command("foo", description="do foo")
    async def cmd_foo(ui, args):
        pass

    cmd = ui._slash.get("foo")
    assert cmd is not None
    assert cmd.description == "do foo"


def test_ui_command_aliases() -> None:
    ui = xli.UI()

    @ui.command("model", aliases=["m"])
    async def cmd(ui, args):
        pass

    assert ui._slash.get("model") is ui._slash.get("m")


def test_ui_on_prompt_decorator_sets_handler() -> None:
    ui = xli.UI()

    async def handler(prompt: str) -> None:
        pass

    ui.on_prompt(handler)
    assert ui._prompt_handler is handler


def test_ui_renderer_decorator_registers() -> None:
    ui = xli.UI()

    @ui.renderer("custom")
    def render(ui, event):
        pass

    assert "custom" in ui._renderers


def test_ui_dispatch_routes_to_renderer() -> None:
    ui = xli.UI()
    seen = []

    @ui.renderer("custom")
    def render(ui, event):
        seen.append(event["data"])

    ui.dispatch({"type": "custom", "data": 42})
    assert seen == [42]


def test_ui_exit_sets_event() -> None:
    ui = xli.UI()
    assert not ui._engine._exit.is_set()
    ui.exit()
    assert ui._engine._exit.is_set()


def test_ui_message_emits_cell() -> None:
    ui = xli.UI()
    cell = ui.message("user", "hello")
    # final messages commit straight to the (scrollback) committed tier
    assert cell in ui._engine.committed
    rendered = "\n".join(cell.lines(80, ui.theme))
    assert "you" in rendered
    assert "hello" in rendered


def test_ui_streaming_context_manager_commits_on_exit() -> None:
    ui = xli.UI()
    with ui.streaming("assistant") as out:
        out.write("hello")
        out.write(" world")
        assert out.text == "hello world"
        # while open, the stream is live (mutable), not yet committed
        assert ui._engine.live and ui._engine.live[-1] not in ui._engine.committed
    # on exit it graduates to scrollback
    assert any(
        "hello world" in "\n".join(c.lines(80, ui.theme)) for c in ui._engine.committed
    )


def test_ui_tool_handle_updates_in_place() -> None:
    ui = xli.UI()
    card = ui.tool("shell", status="running", args={"command": ["ls"]})
    assert card in ui._engine.live  # running -> live + mutable
    card.update(status="done", output="ok")
    assert card in ui._engine.committed  # terminal status -> commits
    rendered = "\n".join(card.lines(80, ui.theme))
    assert ui.theme.tool_done_glyph in rendered  # ✓ glyph marks done
    assert "ok" in rendered  # updated output present


def test_submit_turn_tracks_pending_for_type_ahead() -> None:
    ui = xli.UI()
    ui._engine.submit_turn("first")
    ui._engine.submit_turn("second")
    assert ui._engine._pending == ["first", "second"]
    assert ui._engine.queue_depth == 2


def test_finalize_orphans_cancels_leftover_running_card() -> None:
    ui = xli.UI()
    card = ui.tool("build", status="running")  # live + mutable
    assert card in ui._engine.live
    ui._engine._finalize_orphans(cancelled=True)  # e.g. interrupted turn
    assert card.status == "cancelled"
    assert card in ui._engine.committed
    assert ui._engine.live == []


def test_finalize_orphans_commits_without_relabel_on_normal_end() -> None:
    ui = xli.UI()
    card = ui.tool("build", status="running")
    ui._engine._finalize_orphans(cancelled=False)  # normal completion: don't lie
    assert card.status == "running"
    assert card in ui._engine.committed


def test_spinner_cell_shows_elapsed_seconds() -> None:
    from xli.cells import SpinnerCell

    cell = SpinnerCell("thinking")
    cell._start -= 5  # pretend 5s have passed
    rendered = "\n".join(cell.lines(40, xli.CODEX))
    assert "5s" in rendered


async def test_pick_returns_selected_key() -> None:
    import asyncio

    ui = xli.UI()
    ui._engine._print_committed = lambda c: None
    task = asyncio.create_task(ui.pick("Model", [("o", "Opus"), ("s", "Sonnet")]))
    await asyncio.sleep(0.01)
    assert ui._engine._picker is not None
    ui._engine._picker.move(1)  # highlight "Sonnet"
    ui._engine._picker.resolve(ui._engine._picker.options[ui._engine._picker.index][0])
    assert await task == "s"


async def test_pick_with_no_items_returns_none() -> None:
    ui = xli.UI()
    ui._engine._print_committed = lambda c: None
    assert await ui.pick("Nothing", []) is None  # no dead picker / no crash


async def test_pick_escape_returns_none() -> None:
    import asyncio

    ui = xli.UI()
    ui._engine._print_committed = lambda c: None
    task = asyncio.create_task(ui.pick("X", ["a", "b"]))
    await asyncio.sleep(0.01)
    ui._engine._picker.resolve(None)  # esc
    assert await task is None


async def test_wizard_collects_answers() -> None:
    import asyncio

    ui = xli.UI()
    ui._engine._print_committed = lambda c: None
    task = asyncio.create_task(
        ui.wizard(
            [
                ui.step.pick("Model", ["opus", "sonnet"]),
                ui.step.confirm("Enable telemetry?"),
            ]
        )
    )
    await asyncio.sleep(0.01)
    ui._engine._picker.resolve("opus")  # step 1
    await asyncio.sleep(0.01)
    ui._engine._picker.resolve("yes")  # step 2 (confirm -> True)
    assert await task == {"Model": "opus", "Enable telemetry?": True}


def test_at_mention_offers_files_and_inserts_path(tmp_path, monkeypatch) -> None:
    (tmp_path / "alpha.py").write_text("x")
    (tmp_path / "beta.txt").write_text("y")
    monkeypatch.chdir(tmp_path)

    ui = xli.UI()
    eng = ui._engine

    class _Buf:
        def __init__(self):
            self.text = ""
            self.cursor_position = 0

    eng._buffer = _Buf()

    eng._buffer.text = "explain @alph"
    eng._buffer.cursor_position = len(eng._buffer.text)
    ctx, items = eng._suggestions()
    assert ctx[0] == "file"
    assert "alpha.py" in [v for _l, v, _m in items]

    eng._sugg_index = 0
    eng._accept_suggestion(submit=False)
    assert eng._buffer.text == "explain @alpha.py "  # @token replaced, rest kept


def test_slash_completion_hidden_on_exact_match() -> None:
    ui = xli.UI()

    @ui.command("image", description="x")
    async def _(ui, a):
        pass

    class _Buf:
        def __init__(self):
            self.text = ""
            self.cursor_position = 0

    ui._engine._buffer = _Buf()
    ui._engine._buffer.text = "/image"
    ui._engine._buffer.cursor_position = 6
    assert ui._engine._completion_context() is None  # exact -> no list


def test_step_factory_builds_steps() -> None:
    s = xli.UI().step.pick("Model", ["a", "b"])
    assert s.kind == "pick" and s.key == "Model" and s.options == ["a", "b"]


def test_streaming_commits_at_blank_line_and_labels_once() -> None:
    ui = xli.UI()
    committed = []
    ui._engine._print_committed = committed.append
    with ui.streaming("assistant") as out:
        out.write("Para one.\n\n")
        assert len(committed) == 1  # finalized block commits at the blank line
        out.write("Para two, still going")
        assert len(committed) == 1  # partial tail stays live, not committed
        assert ui._engine.live  # streaming cell still live
    assert len(committed) == 2  # remainder commits on close
    assert ui._engine.live == []  # streaming cell removed once drained
    assert committed[0].label is True  # first chunk carries the role label
    assert committed[1].label is False  # continuation chunk does not repeat it


def test_safe_boundary_never_splits_inside_a_code_fence() -> None:
    from xli.cells import _safe_boundary

    open_fence = "```python\nx = 1\n\ny = 2\n"  # blank line is INSIDE an open fence
    assert _safe_boundary(open_fence) == 0
    closed = "```python\nx = 1\n```\n\n"  # fence closed, then blank line
    assert _safe_boundary(closed) == len(closed)


def test_history_file_is_wired_to_the_composer(tmp_path) -> None:
    from prompt_toolkit.history import FileHistory, InMemoryHistory

    ui = xli.UI(history_file=str(tmp_path / "hist.txt"))
    ui._engine._build_app()
    assert isinstance(ui._engine._buffer.history, FileHistory)

    ui2 = xli.UI()
    ui2._engine._build_app()
    assert isinstance(ui2._engine._buffer.history, InMemoryHistory)


def test_pet_frames_resolution() -> None:
    from xli.pets import frames

    assert frames(None) is None
    assert isinstance(frames("cat"), list) and frames("cat")
    assert frames(["a", "b"]) == ["a", "b"]
    assert frames("nonexistent") == frames("cat")  # unknown name -> default


def test_pet_advances_on_tick() -> None:
    ui = xli.UI(pet="cat")
    eng = ui._engine
    assert eng._pet_i == 0
    for _ in range(6):  # pet steps roughly every 6 ticks (~0.6s)
        eng.tick()
    assert eng._pet_i == 1
    assert eng._pet_fragment()[0] == "class:pet"


def test_link_emits_osc8_hyperlink() -> None:
    ui = xli.UI()
    cell = ui.link("docs", "https://example.com")
    out = "\n".join(cell.lines(40, ui.theme))
    assert "\x1b]8;" in out and "example.com" in out


def test_notify_emits_osc9(capsys) -> None:
    ui = xli.UI(title="app")
    ui.notify("hello")
    out = capsys.readouterr().out
    assert "\x1b]9;hello" in out and "\x1b]777;notify;app;hello" in out


def test_status_bar_render_skips_empty_fields() -> None:
    bar = StatusBar(fields=("model", "tokens", "note"), theme=CODEX)
    bar.set(model="x", note="y")  # tokens left blank
    rendered = bar.render()
    text = "".join(t for _, t in rendered)
    assert "x" in text
    assert "y" in text
    # No double separators around an empty field
    assert CODEX.status_separator * 2 not in text


def test_status_bar_is_empty_when_all_blank() -> None:
    bar = StatusBar(fields=("a", "b"), theme=CODEX)
    assert bar.is_empty()
    bar.set(a="x")
    assert not bar.is_empty()
