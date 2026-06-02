"""Shared fixtures for xli tests."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console


@pytest.fixture()
def capture_console() -> Console:
    """A Rich Console that writes to a StringIO so we can assert on output."""
    return Console(file=StringIO(), force_terminal=False, width=80, record=True)
