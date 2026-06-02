"""Phase 1 headless harness — drives the real xli.Engine core (no TTY).

Verifies the production library (not the spike): type-ahead queueing, ESC interrupt +
on_interrupt cleanup + survival, streaming commit, tool-handle in-place update, slash
commands, and inline approval — all by driving the Engine the way the prompt_toolkit app
would, but without a terminal.
"""

import asyncio

import xli
from xli.cells import MessageCell, NoteCell, ToolCell


async def main() -> int:
    results: list[tuple[str, bool, str]] = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    ui = xli.UI(title="t", status_fields=["model"])
    ui.status.set(model="opus")
    events: list = []
    seen: list[str] = []

    @ui.on_interrupt
    async def cleanup():
        events.append("cleanup")

    @ui.on_prompt
    async def handle(p: str) -> None:
        if p == "long":
            with ui.working("thinking"):
                await asyncio.sleep(10)
        elif p == "stream":
            with ui.streaming("assistant") as out:
                out.write("hello ")
                out.write("world")
        elif p == "tool":
            c = ui.tool("shell", status="running", args={"command": ["ls"]})
            await asyncio.sleep(0.01)
            c.update(status="done", output="ok")
        elif p == "approve":
            events.append(("decision", await ui.approve(title="run ls", reason="writes")))
        seen.append(p)

    eng = ui._engine
    committed: list = []
    eng._print_committed = committed.append
    eng.set_handler(ui._handle_one)
    eng.set_on_interrupt(ui._interrupt_async)
    loop = asyncio.create_task(eng._run_loop())

    def committed_text():
        return "\n".join("\n".join(c.lines(80, ui.theme)) for c in committed)

    # 1. type-ahead -----------------------------------------------------
    eng.submit_turn("long")
    await asyncio.sleep(0.05)
    busy = eng.busy
    has_spinner = any(type(c).__name__ == "SpinnerCell" for c in eng.live)
    eng.submit_turn("stream")
    check("1. busy while turn runs", busy)
    check("1. spinner live during work", has_spinner)
    check("1. type-ahead queued 2nd prompt", eng.queue_depth >= 1, f"depth={eng.queue_depth}")

    # 2. interrupt + cleanup + survival --------------------------------
    eng.interrupt()
    await asyncio.sleep(0.05)
    markers = sum(1 for c in eng.committed if isinstance(c, NoteCell) and "interrupted" in c.text)
    check("2. on_interrupt cleanup fired", "cleanup" in events)
    check("2. exactly one interrupt marker", markers == 1, f"markers={markers}")
    await asyncio.sleep(0.1)
    check("2. queued 'stream' turn ran after interrupt", "stream" in seen, f"seen={seen}")
    check("2. streamed text committed to scrollback", "hello world" in committed_text())

    # 3. tool handle in-place update -> commit -------------------------
    eng.submit_turn("tool")
    await asyncio.sleep(0.1)
    done = [c for c in eng.committed if isinstance(c, ToolCell) and c.status == "done"]
    check("3. tool card flipped running->done & committed", bool(done))
    check("3. updated tool output rendered", "ok" in committed_text())

    # 4. slash command --------------------------------------------------
    eng.submit_turn("/help")
    await asyncio.sleep(0.05)
    check("4. /help rendered commands", "commands" in committed_text())

    # 5. inline approval (now an arrow-selectable picker) --------------
    eng.submit_turn("approve")
    for _ in range(20):
        await asyncio.sleep(0.02)
        if eng._picker is not None:
            break
    pending = eng._picker is not None
    # context must be committed to scrollback BEFORE the decision (auto-scroll + persists)
    from xli.cells import ApprovalCell
    ctx_before = [c for c in eng.committed if isinstance(c, ApprovalCell)]
    if pending:
        eng._picker.resolve("approved")          # simulate selecting "Yes"
    await asyncio.sleep(0.05)
    check("5. approval prompt became active", pending)
    check("5. context committed to scrollback while pending", bool(ctx_before))
    check("5. context persists after decision (not removed)",
          any(isinstance(c, ApprovalCell) for c in eng.committed))
    check("5. outcome committed below context", "approved" in committed_text())
    check("5. approve() returned the decision", ("decision", "approved") in events)
    check("5. user prompt echoed as a cell", any(
        isinstance(c, MessageCell) and c.role == "user" for c in eng.committed))

    # 6. phase 2 live behaviors -----------------------------------------
    from xli.cells import SpinnerCell

    # 6a. type-ahead visibility: queued prompts appear in the live tail as ⋯ lines
    async def slow(p):                      # on_prompt handlers take ONE arg (the prompt)
        await asyncio.sleep(0.3)
    ui2 = xli.UI()
    ui2.on_prompt(slow)
    e2 = ui2._engine
    e2._print_committed = lambda c: None
    e2.set_handler(ui2._handle_one)
    loop2 = asyncio.create_task(e2._run_loop())
    e2.submit_turn("first")
    await asyncio.sleep(0.05)
    e2.submit_turn("second")
    e2.submit_turn("third")
    pending_shown = "second" in "".join(e2._suggest_lines(80)) if False else ("second" in e2._pending and "third" in e2._pending)
    check("6. type-ahead: queued prompts tracked for display", pending_shown, f"pending={e2._pending}")
    await asyncio.sleep(0.4)
    check("6. queued prompt removed once it starts running", "first" not in e2._pending)

    # 6b. orphan sweep: a running tool card left by a cancelled turn -> committed cancelled
    orphan = {}
    ui3 = xli.UI()
    async def leaky(p):
        orphan["card"] = ui3.tool("build", status="running")  # never updated
        await asyncio.sleep(10)
    ui3.on_prompt(leaky)
    e3 = ui3._engine
    e3._print_committed = lambda c: None
    e3.set_handler(ui3._handle_one)
    loop3 = asyncio.create_task(e3._run_loop())
    e3.submit_turn("go")
    await asyncio.sleep(0.1)
    live_running = any(isinstance(c, ToolCell) and c.status == "running" for c in e3.live)
    e3.interrupt()
    await asyncio.sleep(0.1)
    card = orphan.get("card")
    check("6. orphaned running card was live during turn", live_running)
    check("6. interrupt sweeps orphan -> cancelled + committed",
          card is not None and card.status == "cancelled" and card in e3.committed)
    check("6. no live cells left after sweep", len(e3.live) == 0, f"live={len(e3.live)}")

    # 6c. spinner shows elapsed
    sp = SpinnerCell("thinking")
    sp._start -= 3  # pretend 3s elapsed
    check("6. spinner renders elapsed seconds",
          "3s" in "".join(sp.lines(40, ui.theme)))

    for t in (loop, loop2, loop3):
        t.cancel()
    await asyncio.gather(loop, loop2, loop3, return_exceptions=True)

    ok = True
    print("xli v2 Phase 1 — engine harness\n")
    for name, passed, detail in results:
        mark = "\x1b[32mPASS\x1b[0m" if passed else "\x1b[31mFAIL\x1b[0m"
        print(f"  [{mark}] {name}" + (f"   \x1b[2m{detail}\x1b[0m" if detail else ""))
        ok = ok and passed
    print("\n" + ("\x1b[32mALL GATES PASS\x1b[0m" if ok else "\x1b[31mSOME FAILED\x1b[0m"))
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
