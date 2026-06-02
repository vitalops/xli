<div align="center">

# xli

**Build polished, transcript-style terminal UIs for chat, agent, and REPL apps — in ~20 lines of Python.** ✨

[![PyPI](https://img.shields.io/pypi/v/python-xli.svg)](https://pypi.org/project/python-xli/)
[![Python](https://img.shields.io/pypi/pyversions/python-xli.svg)](https://pypi.org/project/python-xli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Built on rich + prompt_toolkit](https://img.shields.io/badge/built%20on-rich%20%2B%20prompt__toolkit-8a2be2.svg)](#-credits)

</div>

<div align="center">

<img src="https://github.com/user-attachments/assets/fefe0758-2d18-4fb2-82b8-8a7d8cc83e17" alt="demo" width="100%"/>

</div>

## 🚀 Getting Started

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

That little snippet gets you: markdown-rendered **streaming** responses, slash-command
autocomplete, `@file` mentions, multi-line input (Enter sends, Alt+Enter for newlines),
persistent history, a themed status bar, arrow-selectable prompts, inline approvals — and a
terminal that *feels right*. 🪄

And the best part: the transcript flows into your terminal's **normal scrollback**, so text stays
**selectable, scrollable, and searchable** with your terminal's own tools. xli doesn't take over
the screen.

---

<table>
<tr>
<td align="center"><img src="https://github.com/user-attachments/assets/32f7fa23-2ea2-4fac-9bda-0af404023f6f" width="700"/><br/><br/><b>Streaming transcript</b></td>
<td align="center"><img src="https://github.com/user-attachments/assets/9c48cec0-cf75-41e6-91af-6529019f8f0a" width="700"/><br/><br/><b>Slash commands</b></td>
<td align="center"><img src="https://github.com/user-attachments/assets/17f99fa2-2739-4da2-865d-230de25ff4e3" width="700"/><br/><br/><b><code>@</code> file picker</b></td>
<td align="center"><img src="https://github.com/user-attachments/assets/1bd447e2-b3d2-43cf-8fa5-dbd3c066a380" width="700"/><br/><br/><b>Inline approval</b></td>
<td align="center"><img src="https://github.com/user-attachments/assets/37acc10e-7e40-4671-9517-2405f0bb3c27" width="700"/><br/><br/><b><code>ui.pick()</code></b></td>
<td align="center"><img src="https://github.com/user-attachments/assets/7a5038ec-9b1d-44fa-ad82-425eb3f82f76" width="700"/><br/><br/><b>Live tool card</b></td>
</tr>
</table>

## ✨ Highlights

- 📜 **Real scrollback, not a screen takeover.** Finalized output is printed into your terminal's
  native scrollback — select, scroll, and find all work the way they always do.
- 🌊 **Streaming markdown** that appears token-by-token, then settles into properly-rendered text.
- 🃏 **Mutable cards.** A tool call flips from `running` → `done` *in place*; a plan's checkboxes
  tick off live — via a handle you hold and update from anywhere.
- ⌨️ **A real composer.** Multi-line input, slash-command autocomplete, `@file` mentions, history,
  and paste handling out of the box.
- ✅ **Inline approvals, pickers & wizards** — arrow-selectable, no modal screen-takeover, and they
  block your agent until the user answers.
- ⏸️ **Type-ahead & ESC-to-interrupt** while the agent is working, with cooperative `asyncio`
  cancellation.
- 🎨 **Themeable** via plain dataclasses — minimal/glyph-driven by default, boxed if you insist.
- 🪶 **Tiny surface, two deps.** Wraps [rich](https://github.com/Textualize/rich) for rendering and
  [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) for input. No build steps.

## 🤔 What it is

A small, opinionated library for **one specific job**: interactive agent / chat-style terminal apps
where output is a *flowing transcript*, not an app screen.

The pattern xli handles:

- A scrolling transcript of structured cards — user messages, assistant messages, tool calls,
  diffs, plans, reasoning, images — committed to real scrollback.
- Streaming markdown that appears as it arrives, then settles into rendered scrollback.
- A persistent multi-line composer at the bottom with autocomplete, `@file` mentions, and history.
- **Mutable cards** — a tool card that flips `running` → `done` in place, a plan whose checkboxes
  update — via a handle you hold.
- Inline, arrow-selectable approvals / pickers / wizards that block until resolved.
- A subtle status bar, an animated "working" spinner, type-ahead, and ESC-to-interrupt.

## 🚫 What it is NOT

| Not… | Because |
|---|---|
| A TUI framework | No widget tree, no CSS, no focus model, no mouse panes. Reach for [Textual](https://github.com/Textualize/textual) when you want a full app screen. |
| A "richer `print`" | xli is interactive — it owns the event loop. For one-shot static rendering, use [rich](https://github.com/Textualize/rich) directly. |
| A full-screen app | It renders **inline** so your terminal keeps native scroll / select / find. That's the whole point. |
| Tied to any LLM / agent framework | It knows nothing about providers. It renders the events *you* emit — OpenAI, Anthropic, LangChain, your own loop, whatever. |
| A REPL builder | It runs *your* code in response to prompts. For a Python REPL, use [ptpython](https://github.com/prompt-toolkit/ptpython). |

## ⚖️ How it compares

xli lives in the gap between "low-level rendering toolkit" and "full-screen app framework." If your
output is a **conversation that scrolls**, that gap is exactly where you want to be.

| | xli | [Textual](https://github.com/Textualize/textual) | [rich](https://github.com/Textualize/rich) | [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) | [questionary](https://github.com/tmbo/questionary) |
|---|---|---|---|---|---|
| **Shape** | Flowing transcript | Full-screen app | Print / render | Input / REPL | Prompts only |
| **Native scrollback** | ✅ keeps it | ❌ takes over screen | ✅ (it just prints) | ⚠️ partial | ✅ |
| **Streaming + mutable cards** | ✅ built-in | ✅ (you wire widgets) | ❌ DIY | ❌ DIY | ❌ |
| **Composer (multiline, history, `@`, `/`)** | ✅ built-in | 🔧 build from widgets | ❌ | 🔧 primitives | ❌ |
| **Inline approvals / pickers / wizards** | ✅ built-in | 🔧 build from widgets | ❌ | 🔧 primitives | ✅ (pickers) |
| **Best for** | Chat / agent transcripts | Dashboards, IDEs, full apps | Static output | Custom REPLs & input | One-off questionnaires |

**In short:** Textual gives you a canvas to build *any* app and asks you to design the whole screen.
xli gives you *one* app shape — the agent/chat transcript — already assembled, and hands the
scrollback back to your terminal. If you've been gluing rich + prompt_toolkit together to make a
chat loop, xli *is* that glue, done well. 🙂

## 📦 Install

```sh
pip install python-xli
```

Optional extras:

- `python-xli[markdown]` — `pygments` for code-block syntax highlighting in messages (recommended).
- `python-xli[images]` — `pillow`, for inline images (`ui.image(...)`).

Two core dependencies (rich, prompt_toolkit). No build steps. Requires Python **3.11+**.

## 🚀 Quickstart

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

    card = ui.tool("think", status="running")        # live, mutable card
    with ui.working("thinking"):
        await asyncio.sleep(0.5)
    card.update(status="done", output="ok")          # commits to scrollback

    with ui.streaming("assistant") as out:
        for token in f"You said: **{prompt}**".split():
            out.write(token + " ")
            await asyncio.sleep(0.04)

ui.run()
```

> 💡 Want to see everything at once? `examples/demo.py` exercises every feature in one file.

## 📖 The vocabulary

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

## 🧠 The one design decision

xli renders **inline**, not full-screen. Finalized cells are *printed into your terminal's normal
scrollback* — so selection, scrolling, and find all come from the terminal itself. Only a small
**live region** at the bottom (the composer, status bar, an in-progress stream, a running tool
card, a spinner, a picker) is redrawn.

A cell is **mutable while it's live** at the bottom; once it finalizes it **commits to scrollback**
and becomes immutable (but selectable). That two-tier model is what lets xli have both editable,
animated cards *and* native, selectable scrollback — the thing full-screen TUIs give up.

## 🃏 Mutable cards

The transcript methods return a handle. Hold it, mutate it from anywhere (including across `await`s
and from other tasks) — it re-renders in place while live, then commits to scrollback once it's
finalized:

```python
card = ui.tool("shell", status="running", args={"command": ["pytest", "-q"]})
result = await run_shell(...)
card.update(status="done", output=result)        # ✓ shell … and the output, committed
```

A `ui.tool(...)` **without** a `status` is a one-shot card (committed immediately). With
`status="running"` it stays live and mutable until you update it to `done` / `error` / `cancelled`.

## ⌨️ Slash commands & @file mentions

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

Typing `/` opens a command list **below** the composer (arrow to navigate, Tab to fill, Enter to
run). `/help`, `/quit`, and `/clear` are built in (override freely). Typing `@` opens a **file
picker** from the working directory; Tab/Enter inserts the path — handy for letting users reference
files for your agent.

## ✅ Approvals, pickers, wizards

All are inline and arrow-selectable (no modal screen-takeover). The request commits to scrollback so
it scrolls into view and persists; the choices appear in the live region; the outcome is recorded
below.

```python
decision = await ui.approve(
    title="apply patch to README.md",
    body="add a one-liner about xli",
    reason="writes outside the workspace root",
)   # -> "approved" | "approved_for_session" | "denied" | "aborted"
```

`↑/↓` move the highlight, `1`-`9` quick-select, `Enter` confirms, `Esc` cancels.

## ⏸️ Interrupts

The composer stays live while your handler runs — users can **type ahead** (queued prompts show as
muted `⋯` lines) and press **ESC to interrupt** the current turn. Interrupt is cooperative `asyncio`
cancellation; register cleanup with `@ui.on_interrupt`:

```python
@ui.on_interrupt
async def cleanup():
    await release_resources()       # don't write to the transcript here
```

A running tool card left behind by an interrupted turn is automatically marked `cancelled`.

## 🎨 Themes

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

Themes are dataclasses — override fields, don't subclass. The default leans "light": chrome is font
color + thin rules, never solid background blocks. See [`docs/theme.md`](docs/theme.md) for the
design guide you can hand to a coding agent.

## 🔌 Plugging into an agent

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

For token-by-token output, wrap a `with ui.streaming("assistant") as out:` block and call
`out.write(delta)` as deltas arrive. Have your own event stream? Register a custom renderer:

```python
@ui.renderer("benchmark")
def render_benchmark(ui, event):
    ui.print(make_bar_chart(event["data"]))

ui.dispatch({"type": "benchmark", "data": [...]})
```

## ⌨️ Keys

```
enter                send  (or run highlighted command / select picker option / accept input)
alt+enter ⋅ ctrl+j   newline
↑ / ↓                history · navigate the command/file list · move picker selection
tab                  accept the highlighted completion / insert @file path
1–9                  quick-select a picker option
esc                  cancel a picker/modal or close the list — otherwise interrupt the turn
ctrl+c               interrupt          ctrl+d  quit
```

## 🛠️ Contributing

Contributions, bug reports, and ideas are very welcome! 🙌

```sh
git clone https://github.com/farizrahman4u/xli
cd xli
pip install -e ".[dev,markdown,images]"
pytest            # run the tests
ruff check .      # lint
mypy xli          # type-check
```

Found a rough edge or have a use case xli doesn't cover cleanly? Open an
[issue](https://github.com/farizrahman4u/xli/issues) — the API is small on purpose, so design
conversations matter.

## 📍 Status

**Pre-1.0** (currently `0.2.0`). The API is stable enough to build on; versions are bumped
thoughtfully if anything user-facing changes.

## 🙏 Credits

xli stands on the shoulders of two excellent libraries:

- [**rich**](https://github.com/Textualize/rich) — all the rendering.
- [**prompt_toolkit**](https://github.com/prompt-toolkit/python-prompt-toolkit) — all the input.

xli's contribution is the *composition*: the API you'd actually want to write a chat/agent terminal
app in.

## 📄 License

[MIT](LICENSE) © xli contributors
