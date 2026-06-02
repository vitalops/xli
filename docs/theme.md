# xli design guide — the "light terminal" look

> **Paste-ready.** If you're using a coding agent to build an app with `xli`, drop this
> whole file into your prompt. It tells the agent the visual language to follow so the
> result feels like a *native terminal tool* — light, quiet, text-first — and not a
> repainted desktop GUI stuffed into a terminal.

## The intent in one line

Make it look like it belongs next to `git`, `ssh`, and `vim` — a flowing transcript of
text you can select and scroll, with quiet structure shown by **font color, weight, glyphs,
and thin rules** — **never** by filling regions with solid background color.

## Why this matters

The fastest way to make a terminal app feel wrong is to paint solid background blocks
(reversed status bars, filled panels, boxed cards everywhere). It reads as a heavy GUI
chrome bolted onto a terminal, it fights the user's own color scheme, it photographs badly
in CI logs and screenshots, and it stops text from feeling selectable. The Codex/Claude/aider
aesthetic is the opposite: mostly the terminal's own background, sparse ink, structure from
*type* not *fills*.

## Core principles

1. **No solid backgrounds for chrome.** Status bars, footers, headers, and separators carry
   their meaning in **foreground color + weight**, not a filled bar. Let the terminal's
   background show through everywhere.
2. **Separate with lines and space, not boxes.** A single thin rule (`─`) or a vertical
   gutter (`│`), plus a blank line of breathing room between items, does the job. Reserve
   full borders/boxes for the rare case the user explicitly wants them.
3. **Color is semantic, not decorative.** Spend color where it means something — role
   (you / assistant / system), state (working / idle / error), diff (add / del). Everything
   else stays in a muted grey. Bold/bright = "this matters", not "this is a heading".
4. **Glyph gutters over labels-in-boxes.** A leading glyph (`▸`, `│`, `✓`, `⚠`) in an accent
   color marks a card's kind. No surrounding frame needed.
5. **Respect the user's palette.** Prefer the terminal's default foreground and the 16 ANSI
   colors (or restrained 256/truecolor greys) so the app adapts to light *and* dark themes.
   Don't hard-pin a background.
6. **Keep text selectable and scrollable.** Don't take over the whole screen with a redraw
   loop; let finalized content live in normal scrollback. (xli's inline model does this for
   you — don't fight it.)
7. **Animation is a whisper.** A small spinner or a shimmer is fine; bouncing bars and
   flashing color are not. Motion should signal "working", then get out of the way.

## DO / DON'T

| Do | Don't |
|---|---|
| Status bar in dim grey foreground text | Status bar as a `reverse`/filled colored bar |
| A `─` rule between transcript and input | A full box drawn around the input |
| `▸ shell` with a colored glyph | `[ TOOL: shell ]` in a filled tag |
| One blank line between cells | Tight, wall-to-wall text with no breathing room |
| Muted grey for 90% of chrome | A different bright color for every element |
| Bold only for the one thing that matters | Bold everywhere "for emphasis" |
| Let the terminal bg show | `bg:#1e1e1e` hard-coded anywhere |
| Color-code state words (amber/green/red) | Color-code by filling their background |

## Color budget (a good default)

- **Chrome / hints / secondary text:** one muted grey (`grey50` / `#808080` / `ansibrightblack`).
- **Separators / rules:** an even dimmer grey (`#3a3a3a` / `ansibrightblack`).
- **Roles:** you = cyan, assistant = green/default, system = grey.
- **State:** working = amber/yellow (often bold), idle = green, error = red, warning = yellow.
- **Diffs:** add = green, del = red, hunk header = magenta/dim.
- **Accent (prompt glyph, links):** a single soft accent (e.g. soft cyan), used sparingly.

That's ~6 colors total, most of them grey. If you're reaching for a seventh, ask whether it
carries meaning.

## How to express this in xli

xli's `Theme` is a dataclass — set fields, don't subclass. The defaults already follow this
guide (no borders, glyph gutters, muted greys). Keep it that way:

```python
import xli

ui = xli.UI(
    theme=xli.Theme(
        # roles
        user_color="cyan",
        assistant_color="green",
        system_color="grey50",
        # structure by glyph, not box
        tool_glyph="▸", tool_color="blue",
        reasoning_glyph="│", reasoning_color="grey50",
        # quiet chrome
        muted_color="grey50",
        status_color="grey50",          # foreground only — no background field is set
        # keep it borderless and airy
        use_borders=False,
        item_spacing=1,                  # one blank line between cells
        # prompt: a glyph in a soft accent, NOT a filled block
        prompt_glyph=">", prompt_color="cyan", prompt_bg="",   # empty bg => no solid block
    ),
)
```

Rules of thumb when wiring a custom theme or rendering:

- **Never set a background** (`bg:` / `prompt_bg` / `style="reverse"`) on chrome. Leave it empty.
- For a status line / footer: render it as plain foreground fragments in `muted_color`, and
  color *only* the state token (e.g. amber when working).
- For separation between the transcript and the composer, use a one-row rule of `─` in a dim
  grey rather than a panel or a reversed bar.
- If you must group something visually, prefer a left gutter glyph + indent over a full border.
- Reach for `xli.Theme(use_borders=True)` (the `boxed` preset) *only* when the user explicitly
  asks for boxes.

## Quick checklist before you ship a screen

- [ ] No `reverse` and no `bg:` on any status/header/footer/separator.
- [ ] At most ~6 colors, and each one means something.
- [ ] Structure reads even in monochrome (glyphs + spacing + rules carry it).
- [ ] One blank line of breathing room between transcript items.
- [ ] Bold/bright used only for genuinely important tokens.
- [ ] Text is selectable; nothing takes over the full screen unnecessarily.
- [ ] It looks at home beside `git status` output — not like a popup dialog.
