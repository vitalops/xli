"""xli master demo — every feature in one app.

Run it:

    python examples/demo.py

Then just type a message to see streaming markdown, or use a slash command to
show off a specific feature:

    /tools    a tool card that flips running -> done in place
    /diff     a syntax-colored diff
    /plan     a checklist plan
    /reason   a muted reasoning rail
    /image    an inline image (half-block; selectable like any text)
    /approve  an inline y/a/n approval prompt
    /ask      a pick -> confirm -> input modal flow
    /sleep    a long task — press ESC to interrupt it
    /help     list everything · /quit to exit

While anything is running you can keep typing (type-ahead), and ESC interrupts the
current turn. Finalized output lives in normal scrollback — select and scroll it
like any terminal program. Chrome is font-color + a thin rule, no solid blocks.
"""

from __future__ import annotations

import asyncio

import xli

ui = xli.UI(title="xli demo", status_fields=["model", "tokens"], pet="cat")
ui.status.set(model="opus-4.8", tokens="0")
_tokens = 0


@ui.on_interrupt
async def cleanup() -> None:
    # Where you'd release resources / cancel inflight work. Don't write to the
    # transcript here — the library already prints one interrupt marker.
    await asyncio.sleep(0)


# --------------------------------------------------------------------------- chat
@ui.on_prompt
async def reply(prompt: str) -> None:
    global _tokens
    ui.reasoning("Reading the request and picking a shape for the answer…")
    with ui.working("thinking"):
        await asyncio.sleep(0.6)
    with ui.streaming("assistant") as out:
        for chunk in _fake_markdown(prompt):
            out.write(chunk)
            _tokens += len(chunk.split())
            ui.status.set(tokens=str(_tokens))
            await asyncio.sleep(0.03)


def _fake_markdown(prompt: str):
    yield f"You said **{prompt}**.\n\n"
    yield "Here's what xli can do, all in this one demo:\n\n"
    yield "- streaming *markdown* that settles into selectable scrollback\n"
    yield "- `tool cards` that update in place (`/tools`)\n"
    yield "- diffs, plans, reasoning, and inline images\n"
    yield "- inline approvals and modal flows (`/approve`, `/ask`)\n\n"
    yield "> Tip: start a `/sleep` and hit **ESC** to see cooperative interrupt.\n"


# --------------------------------------------------------------------------- features
@ui.command("tools", description="tool card running -> done")
async def cmd_tools(ui: xli.UI, args: str) -> None:
    card = ui.tool("shell", status="running", args={"command": ["pytest", "-q"]})
    with ui.working("running tests"):
        await asyncio.sleep(1.2)
    card.update(status="done", output="......................\n54 passed in 0.12s")


@ui.command("diff", description="a colored unified diff")
async def cmd_diff(ui: xli.UI, args: str) -> None:
    ui.diff(
        "--- a/greet.py\n+++ b/greet.py\n@@ -1,2 +1,2 @@\n"
        "-def greet(name):\n-    return 'hi ' + name\n"
        "+def greet(name: str) -> str:\n+    return f'hi {name}'\n",
        path="greet.py",
    )


@ui.command("plan", description="a checklist plan")
async def cmd_plan(ui: xli.UI, args: str) -> None:
    ui.plan([
        ("explore the codebase", "completed"),
        ("build the engine", "in_progress"),
        ("ship v2", "pending"),
    ])


@ui.command("reason", description="a reasoning rail")
async def cmd_reason(ui: xli.UI, args: str) -> None:
    ui.reasoning("First I'd check the inputs,\nthen weigh two approaches,\nthen commit to one.")


@ui.command("image", description="an inline image")
async def cmd_image(ui: xli.UI, args: str) -> None:
    try:
        from PIL import Image
    except ImportError:
        ui.note("install Pillow for images:  pip install pillow")
        return
    img = Image.new("RGB", (72, 36))
    px = img.load()
    for y in range(36):
        for x in range(72):
            px[x, y] = (int(255 * x / 72), int(255 * y / 36), 170)
    ui.image(img)


@ui.command("approve", description="inline approval prompt")
async def cmd_approve(ui: xli.UI, args: str) -> None:
    decision = await ui.approve(
        title="apply patch to README.md",
        body="add a one-line note about xli",
        reason="writes outside the workspace root",
    )
    ui.note(f"decision: {decision}")


@ui.command("ask", description="pick -> confirm -> input flow")
async def cmd_ask(ui: xli.UI, args: str) -> None:
    model = await ui.pick("Pick a model", ["opus", "sonnet", "haiku"])
    if model is None:
        ui.note("cancelled")
        return
    ui.status.set(model=model)
    if await ui.confirm("Enable telemetry?"):
        name = await ui.input("Your name?", default="dev")
        ui.message("system", f"thanks {name} — telemetry on, model set to {model}")
    else:
        ui.message("system", f"telemetry off, model set to {model}")


@ui.command("wizard", description="multi-step setup wizard")
async def cmd_wizard(ui: xli.UI, args: str) -> None:
    answers = await ui.wizard([
        ui.step.pick("Model", ["opus", "sonnet", "haiku"]),
        ui.step.pick("Reasoning", ["off", "low", "high"]),
        ui.step.confirm("Stream responses?"),
        ui.step.text("Project name", default="my-app"),
    ])
    if answers is None:
        ui.note("wizard cancelled")
        return
    if answers["Model"]:
        ui.status.set(model=answers["Model"])
    ui.message("system", f"configured: {answers}")


@ui.command("link", description="a clickable hyperlink (OSC 8)")
async def cmd_link(ui: xli.UI, args: str) -> None:
    ui.link("xli on GitHub →", "https://github.com/fariz/xli")


@ui.command("notify", description="fire a desktop notification (OSC 9)")
async def cmd_notify(ui: xli.UI, args: str) -> None:
    ui.notify("This is an xli notification")
    ui.note("sent a desktop notification (your terminal may or may not show it)")


@ui.command("sleep", description="long task — press ESC to interrupt")
async def cmd_sleep(ui: xli.UI, args: str) -> None:
    with ui.working("long task (press ESC)"):
        await asyncio.sleep(30)
    ui.note("finished sleeping")


if __name__ == "__main__":
    ui.run()
