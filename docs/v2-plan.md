# xli v2 — Codex-parity transcript UI

> Goal: full feature parity with the Codex CLI TUI, with **zero "we can't do THAT"
> walls**, and a public API that stays clean, intuitive, and Pythonic.

## Locked decisions

| Decision | Choice |
|---|---|
| Runtime | **Owned frame loop** on the alternate screen (not scrollback-REPL) |
| Engine (Layer 1) | **prompt_toolkit full-screen `Application`**, pure Python |
| Multimedia | **Parity required** — solved in Python (extra deps allowed), not skipped |
| Cell mutation API | **Handle objects** — `card = ui.tool(...)`; `card.update(...)` from anywhere |
| Interrupt (ESC) | **Cooperative cancellation + `@ui.on_interrupt` cleanup hook** |

## Why this shape (the Textual lesson)

Textual technically has the features but fights a borderless flowing transcript because
its design center is widget-tree + CSS + focus model, and it hides the primitives. The
rule for v2: **own the frame loop on a foundation that exposes raw primitives (draw lines,
read keys/mouse, emit escapes) and imposes no widget/CSS/focus model.** prompt_toolkit's
full-screen `Application` is immediate-mode enough — we drive the layout, it never imposes
chrome — and we already depend on it.

## Layered architecture (engine never leaks into the API)

```
Layer 4  PUBLIC API   decorators / context managers / awaitables / Cell handles.
                      Frozen contract. Never exposes a prompt_toolkit or rich type.
Layer 3  SCENE        Transcript(list[Cell]) + Composer + StatusBar + FloatStack.
                      Cells are mutable + dirty-tracked. Mutate + invalidate() to redraw.
Layer 2  RENDER       rich renderable -> ANSI/FormattedText, cached per cell
                      (key = content-hash + width). Only dirty + visible cells re-render.
Layer 1  ENGINE       prompt_toolkit Application: owns screen, frame loop, key/mouse/paste,
                      and the image-placement post-render hook (see below). Swappable.
```

If the engine bet ever proves wrong, we re-do Layer 1 only — Layer 4 (the contract you
care about) is insulated.

## Engine design (Layer 1 / 2)

**Rendering model: INLINE, not full-screen** (corrected by the Phase 0 spike — see findings
below). This is how Codex/Claude actually work, and it's what makes text natively selectable.

- **Non-full-screen** `Application` (`full_screen=False`) run under `patch_stdout(raw=True)`.
- Two tiers:
  - **Committed scrollback** — finalized cells are `print()`ed into the terminal's *normal*
    scrollback. Natively **selectable + scrollable**, immutable. (You never mutate old cells.)
  - **Live tail** — a small redrawing region at the bottom holding only what's *active*:
    in-progress streaming, a running tool card, spinners, status line, composer. Mutable + animated.
  - A cell is mutable while live; reaching a terminal state (e.g. tool `done`) graduates it to
    scrollback via the commit step.
- **Mouse OFF by default** so native click-drag selection works; enabled transiently only inside
  mouse-driven overlays if any are built.
- Layout (live region only): `FloatContainer(HSplit([live_tail, status_line, composer]), floats=[...])`.
  - **live_tail**: a `UIControl` rendering just the live cells, pulling cached ANSI lines per cell.
  - **status_line**: a real one-row `Window` (replaces today's dead `bottom_toolbar`; see
    note in `composer.py:51` — `ui.status.set()` currently updates state nothing renders).
  - **composer**: prompt_toolkit `BufferControl`, dynamic height, the existing multiline /
    history / paste / slash-completion behavior, kept.
  - **floats**: modals, pickers, wizards, mention/slash popups. The pager / transcript-search
    overlay (Ctrl-T) is the one place we *do* enter the alternate screen, transiently.
- **rich -> prompt_toolkit bridge**: render each cell's rich renderable to an ANSI string at
  the current width, wrap in `prompt_toolkit.formatted_text.ANSI`. rich keeps doing markdown,
  syntax highlighting, tables, and diffs for free. Cache keyed by `(hash, width)`; invalidate
  on resize.
- **Concurrency**: composer submissions land on an `asyncio.Queue`; a dispatcher task runs
  one handler at a time as a task. The app keeps processing input meanwhile -> type-ahead /
  queueing falls out for free. `app.invalidate()` triggers redraws; a frame ticker drives
  animations independently of handler logic.

## The hard part: inline images inside prompt_toolkit

prompt_toolkit owns and diff-renders the screen, so we can't just print image escapes — they'd
be clobbered. This is also hard in Codex (ratatui has no image support; it hand-rolls sixel +
fallback). Plan:

1. **Detect** the terminal graphics protocol: kitty graphics, iTerm2 inline, sixel; else none.
   Use `term-image` + `Pillow` (pure-pip) for kitty/iTerm2 + block fallback; optional sixel lib.
2. **Reserve space**: an image cell emits *N blank rows* into `TranscriptControl` output so
   layout and scroll math are correct and prompt_toolkit treats those rows as empty.
3. **Place after flush**: a post-render hook computes each visible image cell's on-screen
   row/col, saves cursor, moves absolute, emits the graphics escape, restores. On scroll /
   resize / occlusion, re-emit (kitty) or delete-by-id + re-emit (kitty supports placement IDs;
   iTerm/sixel re-emit).
4. **Graceful fallback**: with no graphics protocol, render the image to colored half-block /
   quadrant Unicode (term-image / chafa). That's just styled text -> goes through the normal
   rich->FormattedText path with no special casing. So even the hard feature degrades into the
   easy path — exactly Codex's behavior.

Same machinery powers the ambient **pet** (animated sprite cell) and the **voice meter**
(braille-bar cell driven by the frame ticker).

## Public API (Layer 4) — preserved + extended

Everything good about today's API stays. New surfaces for the new capabilities:

```python
ui = xli.UI(title="echo", status=["model", "tokens"])

@ui.on_interrupt
async def cleanup():                          # fires when ESC cancels a turn
    await release_resources()

@ui.on_prompt
async def handle(prompt: str) -> None:
    with ui.working("thinking…"):             # auto-animated spinner + elapsed timer
        card = ui.tool("shell", status="running")   # -> Cell handle
        try:
            out = await run_shell(...)
            card.update(output=out, status="done")    # mutate a printed cell
        except asyncio.CancelledError:                # ESC -> cooperative cancel
            card.update(status="cancelled"); raise

    with ui.streaming("assistant") as out:    # unchanged
        async for tok in llm(prompt):
            out.write(tok)

    ui.image("plot.png")                       # multimedia, protocol-detected

    plan = await ui.wizard([                    # multi-step survey as a float
        ui.step.pick("model", ["opus", "sonnet"]),
        ui.step.confirm("enable telemetry?"),
        ui.step.text("project name"),
    ])
```

- `ui.tool/message/diff/plan/reasoning(...)` each return a `Cell` handle with
  `.update(**fields)` and `.remove()`. Handles are task-safe (mutate model + `invalidate()`).
- `with ui.streaming(...)` still yields its streaming handle (also a Cell).
- Type-ahead / queue: free, nothing for the user to do.
- `pick` / `confirm` / `input` rebuilt as in-screen floats (no more separate dialog screens),
  same awaitable signatures.
- `dispatch` / `@ui.renderer` escape hatch kept.

## Delivery phases

### Phase 0 — De-risk spike (DONE — passed, with one architecture correction)
Spike at `spikes/phase0.py`. Headless harness asserts all mechanics; interactive demo confirms
the visual behavior. **Outcome: bet holds.** Two findings from running it interactively:
- **Full-screen breaks native text selection.** Switched to the inline two-tier model above
  (committed scrollback + live tail). Selection + scrollback now native. This is the single
  most important correction and is reflected in "Engine design" above.
- **Interrupt must emit exactly one marker.** The library prints one `⦻ interrupted`; the
  `on_interrupt` hook is for resource cleanup only and must not write to the transcript.

Original gate list (all pass):
One throwaway prompt_toolkit full-screen app proving, **together**:
1. typing while a fake task runs (concurrent input),
2. ESC cancels it and the `on_interrupt` hook fires,
3. a tool card flips `running -> done` in place via `handle.update()`,
4. one inline image renders (kitty/iTerm) with half-block fallback.

Gate: all four work simultaneously. If anything fights us, we learn it in a day — this is the
direct answer to the Textual scar tissue. **No further building until this passes.**

### Phase 1 — Engine + text parity  (DONE)
Application skeleton, scene model, rich->pt render bridge with caching, transcript +
status + composer windows, the existing cards, streaming, slash autocomplete.
Built as real library code:
- `xli/render_bridge.py` — Rich renderable → cached ANSI lines.
- `xli/cells.py` — scene model: `Cell` base + handle (`.update()`/`.remove()`), Message/
  Tool/Diff/Plan/Reasoning/Note/Custom/Spinner/Streaming/Image cells; two-tier `final` rule.
- `xli/engine.py` — inline runtime: live-tail + separator + composer + status layout under
  `patch_stdout`, dispatcher/queue (type-ahead), cooperative interrupt + `on_interrupt`,
  commit-to-scrollback, working spinner, slash completer float, inline approval/confirm/pick.
- `xli/ui.py` — public facade (decorators, handle-returning transcript API, `working()`,
  `image()`, awaitable modals). `xli/approval.py` slimmed to the `Decision` type.
- Removed v1 `composer.py` + `modals.py` (folded into the engine). Status bar now actually
  renders (fixes the v1 dead-code bug).
Verified: 54 pytest pass; `spikes/phase1_harness.py` drives the real engine headlessly and
passes 13 gates (type-ahead, interrupt+cleanup+survival, streaming commit, tool-handle
update, slash, inline approval, user echo); `_build_app()` constructs the pt app cleanly.
Interactive polish (visual confirmation, multiline composer feel) pending a real-terminal run.

### Phase 2 — Live behaviors  (DONE)
Core mechanics (handles + `.update`, `working()` spinner, type-ahead queue, cooperative
interrupt + `@ui.on_interrupt`) landed with the Phase 1 engine. Phase 2 made them Codex-grade:
- **Spinner elapsed timer** — `⠋ thinking… 4s` (`SpinnerCell` tracks start time; ticker redraws).
- **Type-ahead made visible** — queued prompts render as muted `⋯ <text>` lines in the live
  tail (replaced the bare `queued:N` status count).
- **Orphaned live-cell sweep** — on turn end/interrupt, leftover live cells are finalized
  (`running` tool cards → `cancelled` on interrupt) so nothing gets stuck live (`_finalize_orphans`).
- **Inline-modal context fix** (carried over): approve/confirm/pick commit context+choices+
  outcome to scrollback so they auto-scroll and persist (no floating live prompt).
- **Custom command list** below the composer (replaced the pt popup) + recognized-`/command`
  color cue + show/hide on type/backspace.
- **Shutdown/interrupt correctness** — `_run_loop` uses `current_task().cancelling()` to tell a
  turn interrupt from a loop-task cancel (the `.cancelled()` check swallowed shutdown cancels →
  hang); `_main` now gathers cancelled tasks. Fixes a latent exit-during-turn hang.
Verified: 58 pytest pass; `spikes/phase1_harness.py` passes all gates incl. the Phase 2 set and
exits cleanly (0).

### Phase 3 — Overlays & input richness  (IN PROGRESS)
Scope decisions, given the inline/selectable-text architecture:
- **Mouse: dropped.** Mouse capture breaks native text selection (a non-negotiable); native
  scroll already works via real scrollback.
- **Pager/transcript-search overlay: deferred.** Native scrollback covers scroll+select; only
  search is unique value (complex alternate-screen work) — revisit on request.

Done:
- **Unified arrow-selectable inline picker** (`_Picker`) — ↑/↓ · 1-9 quick-select · enter ·
  esc — rendered in the live region, powering `approve` / `confirm` / `pick` (replaced the
  keyboard y/n/numbers). Context commits to scrollback, picker shows choices, outcome commits.
- **`ui.wizard([...])`** + `ui.step.pick/.confirm/.text` (`xli/wizard.py`) — sequential flow
  returning `{key: answer}`, None on cancel.

- **`@file` mentions** (DONE) — typing `@token` anywhere shows a file-suggestion list (same
  inline list as `/`, via `_completion_context` detecting the active trigger + replace span).
  Tab/Enter inserts `@path` and keeps composing; cwd walk is cached, ignores `.git`/`venv`/etc.

Phase 3 DONE (mouse dropped, pager/search deferred by design). 64 pytest pass; harness clean.

### Misc / hardening (pre-Phase 4)
- **Streaming perf** (DONE) — `StreamingCell` commits finalized content to scrollback at safe
  markdown boundaries (blank lines outside code fences via `_safe_boundary`); only the live
  tail re-renders each frame (was re-rendering the whole growing message → O(n²)). Label rides
  the first chunk; continuations commit unlabelled (`render_message(label=False)`).
- **Composer history** (DONE) — wired the previously-dead `history_file` param to the Buffer
  (`FileHistory`/`InMemoryHistory`), `↑/↓` recall, `append_to_history()` on submit.
- **Pager + transcript search** — SKIPPED (user decision). The inline model commits everything
  to *real terminal scrollback*, so scroll, select, AND find (e.g. Ctrl+Shift+F) all come from
  the terminal for free. A custom pager would duplicate them and fight the terminal — the
  opposite of why we chose inline. This is a feature of the architecture, not a gap.

### Phase 4 — Multimedia & polish
- **Images** (DONE) — `xli/images.py`: env-based protocol detection (kitty / iTerm2 / else
  half-block; `XLI_IMAGE_PROTOCOL` override), hand-rolled kitty (chunked, `a=T,f=100,c,r`) and
  iTerm2 (OSC 1337) escapes, aspect-correct row sizing. `ImageCell.raw_emit()` returns the
  escape (graphics) or None (half-block); the engine commit-printer prints the escape as-is.
  No per-frame re-emission needed — committed once to scrollback. kitty/iTerm verified by
  escape-structure tests; visual confirmation needs a capable terminal (Windows Terminal here
  uses the half-block path, which is tested + working). Pillow lazy-imported.
- **Pet** (DONE) — `xli/pets.py`: opt-in ambient companion (`xli.UI(pet="cat")`, or custom
  frames), cycled by the ticker (~0.6s), parked bottom-right in the status line via a custom
  Status control. Muted, decorative.
- **Voice meter** — SKIPPED (user decision; voice input is a large audio-backend surface out of
  scope for a transcript UI).
- **OSC 8 hyperlinks** (DONE) — `ui.link(label, url)`; markdown links in messages also emit
  OSC 8 (rich does this through the render bridge — verified).
- **OSC 9 notifications** (DONE) — `ui.notify(message, title=)` emits OSC 9 + OSC 777; optional
  `UI(notify_after=<seconds>)` auto-fires when a turn exceeds the threshold.
- **Terminal title** (DONE) — window/tab title set via `output.set_title`, `● <title>` while a
  turn runs, `<title>` when idle.

**Phase 4 DONE** (voice meter skipped). 81 pytest pass; harness clean; demo exercises all of it.

---

## v2 status: feature-complete

All planned phases are done (Phase 0 spike → 4). The misc/hardening pass and Phase 3/4 scope
calls (mouse, pager, voice skipped — each because the inline/selectable-text architecture
already covers it or it's out of scope) are recorded above.

**README rewritten for v2** (every documented API call validated headlessly).

**QA pass done** — `ruff`, `mypy`, and `pytest -W error::DeprecationWarning` all clean; 84 tests.
Found + fixed in QA:
- **Real bug:** boxed theme passed an invalid `box_style=` kwarg to `rich.Panel` (string, not a
  Box) — would crash whenever `use_borders=True`. Now maps the theme name → `rich.box` (+regression test).
- **Real bug:** an empty `ui.pick(..., [])` opened a dead picker → ZeroDivisionError/IndexError on
  keypress. Now returns None.
- **UX:** missing Pillow showed a raw ImportError; now a friendly "install Pillow" hint.
- Type/lint hygiene: removed dead imports, modernized annotations, `Handler` → `Coroutine`,
  `current_task()` None-guard, `get_event_loop`→`get_running_loop`, pytest-asyncio loop-scope set.

Remaining: real-terminal visual verification of kitty/iTerm images + the live interactive feel
(Windows Terminal here exercises everything except graphics-protocol image pixels).

Each phase closes against a literal checklist derived from the 140-feature Codex inventory, so
"parity" is measured, not asserted.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| rich->ANSI per frame is slow on long transcripts | Per-cell cache `(hash,width)`; virtualize to visible window; only re-render dirty cells |
| Image placement under rapid scroll/occlusion | kitty placement-IDs (delete+redraw); re-emit on scroll for iTerm/sixel; prove in Phase 0 |
| OSC 8 hyperlink / OSC 9 passthrough may be stripped by pt | Verify in Phase 0; emit via raw output hook if needed |
| Mouse hit-testing is manual | Acceptable; scene owns hit regions per cell |

## New dependencies
`term-image` + `Pillow` (pure-pip, kitty/iTerm + block fallback). Optional sixel backend.
Everything else stays on the existing `rich` + `prompt_toolkit`.
