"""The approval decision type.

The inline approval *flow* (rendering the prompt + capturing y / a / n / esc) lives in
:mod:`xli.engine`, since it has to happen inside the running app's key loop. This module
just defines the four-value result so it can be imported without pulling in the engine.
"""

from __future__ import annotations

from typing import Literal

#: ``"approved"`` · ``"approved_for_session"`` (the "always" choice) · ``"denied"`` ·
#: ``"aborted"`` (esc / ctrl-c while the prompt is open).
Decision = Literal["approved", "approved_for_session", "denied", "aborted"]
