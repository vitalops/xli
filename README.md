# xli

**Build polished, transcript-style terminal interfaces for chat / agent / REPL-ish apps in 20 lines of Python.**

```python
import xli

ui = xli.UI(title="echo")

@ui.on_prompt
async def reply(prompt: str) -> None:
    with ui.streaming("assistant") as out:
        for token in f"You said: {prompt}".split():
            out.write(token + " ")

ui.run()
```

That gets you: markdown-rendered streaming responses, slash-command autocomplete, `@file`
mentions, multi-line input (Enter sends, Alt+Enter for newlines), persistent history, a themed
status bar, arrow-selectable prompts, inline approvals — and a terminal that *feels right*.

Crucially, the transcript flows into your terminal's **normal scrollback**, so text stays
**selectable, scrollable, and searchable** with your terminal's own tools. xli doesn't take
over the screen.

---

## What it is

A small, opinionated library for one specific job: **interactive agent / chat-style terminal
apps where output is a flowing transcript, not an app screen.**

The pattern xli handles:

- A scrolling transcript of structured cards (user messages, assistant messages, tool calls,
  diffs, plans, reasoning, images) committed to real scrollback.
- Streaming markdown that appears as it arrives, then settles into properly-rendered scrollback.
- A persistent multi-line composer at the bottom with slash-command autocomplete, `@file`
  mentions, history, and paste handling.
- **Mutable cards** — a tool call that flips from `running` to `done` in place, a plan whose
  checkboxes update — via a handle you hold.
- Inline, arrow-selectable approvals / pickers / wizards that block the agent until resolved.
- A subtle status bar, an animated "working" spinner, type-ahead while the agent runs, and
  ESC-to-interrupt.

xli wraps two excellent libraries — [**rich**](https://github.com/Textualize/rich) for
rendering, [**prompt_toolkit**](https://github.com/prompt-toolkit/python-prompt-toolkit) for
input — into the API you'd actually want to write this kind of program in.

## How it works (the one design decision)

xli renders **inline**, not full-screen. Finalized cells are *printed into your terminal's
normal scrollback* — so selection, scrolling, and find all come from the terminal itself. Only
a small **live region** at the bottom (the composer, status bar, an in-progress stream, a
running tool card, a spinner, a picker) is redrawn.

A cell is **mutable while it's live** at the bottom; once it finalizes it **commits to
scrollback** and becomes immutable (but selectable). That two-tier model is what lets xli have
both editable, animated cards *and* native, selectable scrollback — the thing full-screen TUIs
give up.

## Install

```sh
pip install xli
```

Optional extras:

- `xli[markdown]` — `pygments` for code-block syntax highlighting in messages (recommended).
- `xli[images]` — `pillow`, for inline images (`ui.image(...)`).

Two core dependencies (rich, prompt_toolkit). No build steps.

## Quickstart

A fuller echo agent — streaming, a status field, a tool card that updates in place, and a slash
command:

```python
import asyncio
import xli

ui = xli.UI(title="echo", status_fields=["turn"], pet="cat")
turn = 0

@ui.command("clear", description="clear the screen")
async def clear(ui, args):
    ui.clear_transcript()

@ui.on_prompt
async def handle(prompt: str) -> None:
    global turn
    turn += 1
    ui.status.set(turn=turn)

    card = ui.tool("think", status="running")      # live, mutable card
    with ui.working("thinking"):
        await asyncio.sleep(0.5)
    card.update(status="done", output="ok")          # commits to scrollback

    with ui.streaming("assistant") as out:
        for token in f"You said: **{prompt}**".split():
            out.write(token + " ")
            await asyncio.sleep(0.04)

ui.run()
```

## The vocabulary

`xli.UI` exposes a small set of methods you call from any handler. Transcript methods return a
**cell handle** you can mutate.

```python
# --- streaming + cards (return a Cell handle) ---
with ui.streaming(role) as out:   # streamed text; out.write(chunk); out.text
    ...
card = ui.tool(name, args=, output=, status="running")  # status="running" -> live + mutable
card.update(status="done", output=...)                  # mutate in place; commits when final
card.remove()                                           # drop a live cell

ui.message(role, text)            # one-shot message
ui.diff(diff, path=)              # syntax-colored unified diff
ui.plan([("step", "status"), …])  # checklist
ui.reasoning(summary)             # muted thought rail
ui.image("plot.png")              # inline image (kitty / iTerm2 / half-block fallback)
ui.link("label", "https://…")     # OSC 8 hyperlink
ui.note("…") / ui.header("…")     # muted status lines
ui.print(any_rich_renderable)     # escape hatch for custom rendering

# --- a spinner while you work ---
with ui.working("running tests"): ...     # animated, with an elapsed timer

# --- blocking prompts (await) ---
decision = await ui.approve(title=, body=, reason=)   # arrow-select Yes / Always / No
choice   = await ui.pick("Model", ["gpt-5", "claude-opus"])   # ↑/↓ · 1-9 · enter
yes      = await ui.confirm("Delete?")
name     = await ui.input("Name?", default="")
answers  = await ui.wizard([                          # multi-step flow -> dict
    ui.step.pick("Model", ["opus", "sonnet"]),
    ui.step.confirm("Stream responses?"),
    ui.step.text("Project name", default="app"),
])

# --- chrome + lifecycle ---
ui.status.set(model="gpt-5", tokens="3.2k/400k")   # bottom bar (declare fields up front)
ui.notify("response ready")                         # desktop notification (OSC 9)
ui.clear_transcript()
ui.exit()
```

## Mutable cards

The transcript methods return a handle. Hold it, mutate it from anywhere (including across
`await`s and from other tasks) — it re-renders in place while live, then commits to scrollback
once it's finalized:

```python
card = ui.tool("shell", status="running", args={"command": ["pytest", "-q"]})
result = await run_shell(...)
card.update(status="done", output=result)        # ✓ shell … and the output, committed
```

A `ui.tool(...)` **without** a `status` is a one-shot card (committed immediately). With
`status="running"` it stays live and mutable until you update it to `done` / `error` /
`cancelled`.

## Slash commands & @file mentions

```python
@ui.command("model", description="switch model")
async def cmd_model(ui, args):
    sel = await ui.pick("Model", ["gpt-5", "claude-opus"])
    if sel is not None:
        ui.status.set(model=sel)

@ui.command("quit", aliases=["q", "exit"])
async def cmd_quit(ui, args):
    ui.exit()
```

Typing `/` opens a command list **below** the composer (arrow to navigate, Tab to fill, Enter
to run). Once a command is fully typed it's recognized and recolored. `/help`, `/quit`, and
`/clear` are built in (override freely).

Typing `@` anywhere opens a **file picker** from the working directory; Tab/Enter inserts the
path into your message — handy for letting users reference files for your agent.

## Approvals, pickers, wizards

All are inline and arrow-selectable (no modal screen-takeover). The request commits to
scrollback so it scrolls into view and persists; the choices appear in the live region; the
outcome is recorded below.

```python
decision = await ui.approve(
    title="apply patch to README.md",
    body="add a one-liner about xli",
    reason="writes outside the workspace root",
)   # -> "approved" | "approved_for_session" | "denied" | "aborted"
```

`↑/↓` move the highlight, `1`-`9` quick-select, `Enter` confirms, `Esc` cancels.

## Interrupts

The composer stays live while your handler runs — users can **type ahead** (queued prompts
show as muted `⋯` lines) and press **ESC to interrupt** the current turn. Interrupt is
cooperative `asyncio` cancellation; register cleanup with `@ui.on_interrupt`:

```python
@ui.on_interrupt
async def cleanup():
    await release_resources()       # don't write to the transcript here
```

A running tool card left behind by an interrupted turn is automatically marked `cancelled`.

## Themes

```python
ui = xli.UI(theme="codex")        # default — minimal, glyph-driven, no borders, no solid bg
ui = xli.UI(theme="minimal")      # even more austere
ui = xli.UI(theme="boxed")        # rounded borders if you really want them
ui = xli.UI(theme=xli.Theme(      # custom — it's a dataclass; override fields
    user_color="cyan",
    tool_glyph="→",
    code_theme="monokai",
))
```

Themes are dataclasses — override fields, don't subclass. The default leans "light": chrome is
font color + thin rules, never solid background blocks. See `docs/theme.md` for the design guide
you can hand to a coding agent.

## Custom event renderers

When you have your own event stream and want one dispatch point:

```python
@ui.renderer("benchmark")
def render_benchmark(ui, event):
    ui.print(make_bar_chart(event["data"]))

ui.dispatch({"type": "benchmark", "data": [...]})
```

For most things you won't need this — just call `ui.streaming` / `ui.tool` / etc. directly.

## Plugging into an agent

xli renders the event types you give it. It doesn't care if those come from OpenAI, Anthropic,
LangChain, or your own framework:

```python
@ui.on_prompt
async def handle(prompt: str) -> None:
    cards = {}                                        # tool-call id -> live card handle
    async for event in my_agent.stream(prompt):
        if event.kind == "message":
            ui.message("assistant", event.text)
        elif event.kind == "tool_call":
            cards[event.id] = ui.tool(event.name, args=event.args, status="running")
        elif event.kind == "tool_result":
            cards[event.id].update(status="done", output=event.output)   # flips in place
        elif event.kind == "approval_request":
            decision = await ui.approve(title=event.title, body=event.body)
            my_agent.respond(event.id, decision)
```

(For token-by-token output, wrap a `with ui.streaming("assistant") as out:` block and call
`out.write(delta)` as deltas arrive.)

See `examples/demo.py` for one worked example that exercises every feature.

## Keys

```
enter            send  (or run highlighted command / select picker option / accept input)
alt+enter ⋅ ctrl+j   newline
↑ / ↓            history  ·  navigate the command/file list  ·  move picker selection
tab              accept the highlighted completion / insert @file path
1–9              quick-select a picker option
esc              cancel a picker/modal or close the list — otherwise interrupt the current turn
ctrl+c           interrupt        ctrl+d  quit
```

## What it is NOT

| Not | Because |
|---|---|
| A TUI framework | No widget tree, no CSS, no focus model, no mouse panes. Use [Textual](https://github.com/Textualize/textual) for that. |
| A "richer print" | xli is interactive — it owns the loop. For static rendering use [rich](https://github.com/Textualize/rich) directly. |
| A full-screen app | It renders inline so your terminal keeps native scroll / select / find. That's a feature, not a limitation. |
| Tied to any agent / LLM framework | It knows nothing about LLMs or providers. It renders the events you emit. |
| A REPL builder | It runs *your* code in response to prompts. For a Python REPL use [ptpython](https://github.com/prompt-toolkit/ptpython). |

## Status

Pre-1.0. The API is stable enough to build on; versions are bumped thoughtfully if anything
user-facing changes.

## License

MIT.
