"""MS1 mode-backbone invariant: Dictation mode never runs a command.

The safety boundary that makes the Jarvis x Wispr-Flow mix safe is that in
Dictation mode speech is typed verbatim and is *never* interpreted as a
command. ``CommandProcessor.process(text, dictation=True)`` must therefore
short-circuit to a non-command result before touching conversation state,
patterns, or the LLM fallback.

Cross-platform on purpose: the dictation short-circuit is the first statement
in ``process()``, so we exercise it on a bare instance (no ``__init__``, hence
no Windows-only ``winreg`` / OS access) and it runs in CI beside the Linux
logic suites.
"""
import inspect

from command_processor import CommandProcessor, CommandResult


def _bare_processor() -> CommandProcessor:
    # Skip __init__ (touches Windows-only winreg); the dictation path returns
    # before any instance attribute is read, so a bare object is enough.
    return CommandProcessor.__new__(CommandProcessor)


def test_dictation_mode_never_returns_a_command():
    cp = _bare_processor()
    for text in ("open chrome", "shut down the computer", "delete my resume",
                 "empty the recycle bin", "what is 2 plus 2"):
        result = cp.process(text, dictation=True)
        assert isinstance(result, CommandResult)
        assert result.is_command is False, f"dictation leaked a command: {text!r}"
        assert result.action == ""
        assert result.raw_text == text


def test_dictation_defaults_off():
    # Opt-in only: normal command processing is unaffected unless dictation=True.
    default = inspect.signature(CommandProcessor.process).parameters["dictation"].default
    assert default is False
