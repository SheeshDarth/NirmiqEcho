"""
test_safety.py — command regression + shell-injection guard tests

Run: python test_safety.py
"""
import command_processor as cp_mod


def main():
    cp = cp_mod.CommandProcessor()

    # ── Regression: command patterns still work ───────────────────────
    tests = [
        ("Open Chrome!", True, "open_app"),
        ("What time is it?", True, "tell_time"),
        ("Play Shape of You.", True, "play_music"),
        ("Set volume to 40", True, "set_volume"),
        ("message Rahul and say hello there", True, "whatsapp_with_message"),
        ("Who are you?", True, "introduce"),
        ("What can you do?", True, "show_help"),
        ("Good morning", True, "greet"),
        ("type hello world", False, "force_type"),
        ("This is just normal dictation text", False, ""),
    ]
    fails = 0
    for text, want_cmd, want_action in tests:
        r = cp.process(text)
        ok = r.is_command == want_cmd and (not want_action or r.action == want_action)
        if not ok:
            fails += 1
            print(f"  FAIL {text!r} -> is_command={r.is_command} action={r.action}")
    print(f"COMMAND REGRESSION: {len(tests) - fails}/{len(tests)} pass")

    # ── Injection guard: shell metacharacters must be rejected ────────
    # (harmless placeholders — only the metacharacters matter)
    evil = ["calc&&beep", "a|b", "x;y", "a%b%c", "foo`bar",
            "a>b", "a<b", 'a"b', "a'b", "a\nb", "a$b"]
    blocked = 0
    for e in evil:
        if not cp_mod._SAFE_TOKEN_RE.match(e):
            blocked += 1
        else:
            try:
                cp_mod.CommandProcessor._launch_executable(e)
                print(f"  DANGER: launcher accepted {e!r}")
            except (ValueError, OSError):
                blocked += 1
    print(f"INJECTION BLOCK: {blocked}/{len(evil)} rejected")

    # ── Process-name guard for taskkill ───────────────────────────────
    assert cp_mod._SAFE_PROC_RE.match("chrome.exe")
    assert cp_mod._SAFE_PROC_RE.match("notepad++.exe")
    assert not cp_mod._SAFE_PROC_RE.match("chrome.exe & beep")
    assert not cp_mod._SAFE_PROC_RE.match("a;b.exe")
    assert not cp_mod._SAFE_PROC_RE.match("chrome")        # must end .exe
    print("PROC NAME GUARD OK")

    if fails or blocked != len(evil):
        raise SystemExit(1)
    print("ALL SAFETY TESTS PASS")


if __name__ == "__main__":
    main()
