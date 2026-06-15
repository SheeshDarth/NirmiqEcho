"""Routing test for the video-inspired additions (Q&A, jokes, memory, CPU)."""
import time
import command_processor as m


def main():
    cp = m.CommandProcessor()
    time.sleep(1)
    cases = [
        # new spoken Q&A
        ("who is Albert Einstein", "answer_question"),
        ("what is photosynthesis", "answer_question"),
        ("tell me about Mars", "answer_question"),
        ("what's a black hole", "answer_question"),
        # jokes
        ("tell me a joke", "tell_joke"),
        ("make me laugh", "tell_joke"),
        # remember / recall
        ("remember that my wifi password is hunter2", "remember"),
        ("what do you remember", "recall"),
        ("forget everything", "forget_all"),
        # system
        ("cpu usage", "tell_cpu"),
        ("system status", "system_status"),
        # ── CRITICAL regressions: these must NOT become answer_question ──
        ("what is 47 times 19", "calculate"),
        ("what is the time", "tell_time"),
        ("what's the battery", "tell_battery"),
        ("search for python tutorials", "search_web"),
        ("open chrome", "open_app"),
        ("play despacito", "play_music"),
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
