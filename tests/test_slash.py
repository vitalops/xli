"""SlashRegistry + completer."""

from __future__ import annotations

from prompt_toolkit.document import Document

from xli.slash import SlashCommand, SlashCompleter, SlashRegistry


async def _noop(ui, args):
    pass


def test_register_and_get() -> None:
    reg = SlashRegistry()
    reg.register(SlashCommand("model", _noop, description="switch model"))
    assert reg.get("model") is not None
    assert reg.get("nope") is None


def test_aliases_resolve_to_same_command() -> None:
    reg = SlashRegistry()
    reg.register(SlashCommand("quit", _noop, aliases=("q", "exit")))
    assert reg.get("q") is reg.get("quit")
    assert reg.get("exit") is reg.get("quit")


def test_all_dedupes_aliases() -> None:
    reg = SlashRegistry()
    reg.register(SlashCommand("quit", _noop, aliases=("q", "exit")))
    names = [c.name for c in reg.all()]
    assert names == ["quit"]


def test_unregister_removes_aliases_too() -> None:
    reg = SlashRegistry()
    reg.register(SlashCommand("quit", _noop, aliases=("q",)))
    reg.unregister("quit")
    assert reg.get("quit") is None
    assert reg.get("q") is None


def test_match_prefix() -> None:
    reg = SlashRegistry()
    reg.register(SlashCommand("model", _noop))
    reg.register(SlashCommand("memory", _noop))
    reg.register(SlashCommand("quit", _noop))
    matches = [c.name for c in reg.match("/me")]
    assert matches == ["memory"]


def test_match_alias_appears() -> None:
    reg = SlashRegistry()
    reg.register(SlashCommand("quit", _noop, aliases=("q",)))
    names = [c.name for c in reg.match("/q")]
    assert "quit" in names


def test_match_empty_returns_all() -> None:
    reg = SlashRegistry()
    reg.register(SlashCommand("a", _noop))
    reg.register(SlashCommand("b", _noop))
    matches = reg.match("/")
    assert [c.name for c in matches] == ["a", "b"]


def test_parse() -> None:
    reg = SlashRegistry()
    reg.register(SlashCommand("model", _noop))
    cmd, args = reg.parse("/model gpt-4o")
    assert cmd is not None and cmd.name == "model"
    assert args == "gpt-4o"


def test_parse_unknown() -> None:
    reg = SlashRegistry()
    cmd, args = reg.parse("/nope arg")
    assert cmd is None


def test_parse_non_slash() -> None:
    reg = SlashRegistry()
    cmd, args = reg.parse("hello world")
    assert cmd is None
    assert args == "hello world"


# ---------------------------------------------------------------------------
# SlashCompleter behavior
# ---------------------------------------------------------------------------


def test_completer_only_activates_for_leading_slash() -> None:
    reg = SlashRegistry()
    reg.register(SlashCommand("model", _noop))
    comp = SlashCompleter(reg)
    # Plain text → no completions
    completions = list(comp.get_completions(Document("hello"), None))  # type: ignore[arg-type]
    assert completions == []


def test_completer_does_not_match_after_space() -> None:
    reg = SlashRegistry()
    reg.register(SlashCommand("model", _noop))
    comp = SlashCompleter(reg)
    # User typed past the command name → don't suggest others
    completions = list(comp.get_completions(Document("/model gpt"), None))  # type: ignore[arg-type]
    assert completions == []


def test_completer_yields_matches() -> None:
    reg = SlashRegistry()
    reg.register(SlashCommand("model", _noop, description="switch model"))
    reg.register(SlashCommand("memory", _noop, description="show memory"))
    comp = SlashCompleter(reg)
    completions = list(comp.get_completions(Document("/me"), None))  # type: ignore[arg-type]
    texts = [c.text for c in completions]
    assert "memory" in texts
