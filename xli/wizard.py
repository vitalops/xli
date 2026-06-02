"""Multi-step prompt flows — ``ui.wizard([...])``.

A wizard runs a sequence of steps (pick / confirm / text) and returns a dict of
answers keyed by each step's key (the prompt by default). Built on the same inline
picker + line-capture the standalone modals use, so a wizard looks like a natural
run of prompts in the transcript. Cancelling any step (esc) aborts the whole wizard
and returns ``None``.

    answers = await ui.wizard([
        ui.step.pick("Model", ["opus", "sonnet", "haiku"]),
        ui.step.confirm("Enable telemetry?"),
        ui.step.text("Project name", default="app"),
    ])
    # -> {"Model": "opus", "Enable telemetry?": True, "Project name": "myapp"}
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Step:
    kind: str  # "pick" | "confirm" | "text"
    prompt: str
    key: str
    options: list = field(default_factory=list)
    default: str = ""


class _StepFactory:
    """The ``ui.step`` namespace for building wizard steps."""

    def pick(
        self, prompt: str, options: Sequence[Any], *, key: str | None = None
    ) -> Step:
        return Step("pick", prompt, key or prompt, options=list(options))

    def confirm(self, prompt: str, *, key: str | None = None) -> Step:
        return Step("confirm", prompt, key or prompt)

    def text(self, prompt: str, *, default: str = "", key: str | None = None) -> Step:
        return Step("text", prompt, key or prompt, default=default)


step = _StepFactory()
