"""
Security + behaviour tests for user-defined commands (commands.yaml).

Importable on any platform (only stdlib + PyYAML); does NOT construct the full
CommandProcessor, so it runs in CI. The security boundary under test: config can
bind ONLY to whitelisted safe actions, and phrases are regex-escaped.
"""
import tempfile
from pathlib import Path

from command_processor import load_custom_commands, _CUSTOM_SAFE_ACTIONS


def _write(text: str) -> Path:
    d = tempfile.mkdtemp()
    p = Path(d) / "commands.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def main():
    fails = 0

    # 1. A safe command loads and its phrase matches (case-insensitive).
    p = _write(
        "commands:\n"
        "  - phrase: fire up my editor\n"
        "    action: open_app\n"
        "    args: { app_name: code }\n")
    cmds = load_custom_commands(p)
    ok = (len(cmds) == 1 and cmds[0][1] == "open_app"
          and cmds[0][2] == {"app_name": "code"}
          and cmds[0][0].match("Fire Up My Editor"))
    fails += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] safe command loads + matches")

    # 2. Unsafe/destructive actions are REFUSED (the key security boundary).
    p = _write(
        "commands:\n"
        "  - phrase: nuke it\n"
        "    action: shutdown\n"
        "  - phrase: wipe it\n"
        "    action: empty_recycle_bin\n"
        "  - phrase: trash my file\n"
        "    action: delete_file\n"
        "    args: { path: C:/important.txt }\n")
    cmds = load_custom_commands(p)
    ok = len(cmds) == 0
    fails += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] destructive actions refused ({len(cmds)} loaded, want 0)")

    # 3. Mixed file: safe kept, unsafe dropped.
    p = _write(
        "commands:\n"
        "  - phrase: good one\n"
        "    action: take_note\n"
        "    args: { text: hi }\n"
        "  - phrase: bad one\n"
        "    action: restart\n")
    cmds = load_custom_commands(p)
    ok = len(cmds) == 1 and cmds[0][1] == "take_note"
    fails += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] mixed file keeps only the safe command")

    # 4. Phrase is regex-escaped (no injection via special chars).
    p = _write(
        "commands:\n"
        "  - phrase: .*\n"
        "    action: tell_time\n")
    cmds = load_custom_commands(p)
    # '.*' must match the literal string '.*', NOT match arbitrary input.
    ok = len(cmds) == 1 and cmds[0][0].match(".*") and not cmds[0][0].match("anything else")
    fails += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] phrases are regex-escaped (no wildcard injection)")

    # 5. Missing file → empty list, no crash.
    ok = load_custom_commands(Path(tempfile.gettempdir()) / "nope_missing.yaml") == []
    fails += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] missing file returns []")

    # 6. Every whitelisted action is non-destructive (sanity on the set).
    forbidden = {"shutdown", "restart", "sleep", "empty_recycle_bin",
                 "delete_file", "close_app", "move_file", "whatsapp_with_message"}
    ok = forbidden.isdisjoint(_CUSTOM_SAFE_ACTIONS)
    fails += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] whitelist excludes all destructive actions")

    print(f"\n{6 - fails}/6 custom-command tests passed")
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
