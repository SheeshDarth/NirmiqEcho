"""Conversational-phrasing regression — natural wrappers must still route."""
import time
import command_processor as m


def main():
    cp = m.CommandProcessor()
    time.sleep(1)
    cases = [
        # (phrase, expected action)  — conversational wrappers
        ("Hi, can you open chrome please", "open_app"),
        ("hey echo open notepad", "open_app"),
        ("please play despacito", "play_music"),
        ("could you set a timer for 5 minutes", "set_timer"),
        ("i wanna open downloads", "open_folder"),
        ("go ahead and take a screenshot", "screenshot"),
        ("can you tell me the time", "tell_time"),
        # must NOT over-strip real commands:
        ("open chrome", "open_app"),
        ("play shape of you", "play_music"),
        ("what is 47 times 19", "calculate"),
        ("search for python tutorials", "search_web"),
        ("volume up", "volume_up"),
    ]
    fails = 0
    for phrase, want in cases:
        r = cp.process(phrase)
        ok = r.action == want
        fails += not ok
        flag = "PASS" if ok else "FAIL"
        print(f"  [{flag}] {phrase!r:42} -> {r.action or '(dictation)'}  (want {want})")
    print(f"\n{len(cases) - fails}/{len(cases)} routed correctly")
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
