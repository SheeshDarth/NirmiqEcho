"""
test_capabilities.py — routing proof for all NirmiqEcho intents.

Confirms every spoken phrase classifies to the right action WITHOUT
executing side effects. Run: python test_capabilities.py
"""
import time
import command_processor as m


def main():
    cp = m.CommandProcessor()
    time.sleep(2)  # let subsystems warm up

    cases = [
        # math (offline)
        ("add 45 and 30", "calculate"),
        ("what is 12 times 8", "calculate"),
        ("15 percent of 200", "calculate"),
        ("square root of 144", "calculate"),
        # units + dates (offline)
        ("convert 5 km to miles", "calculate"),
        ("100 fahrenheit to celsius", "calculate"),
        ("how many days until christmas", "calculate"),
        ("what's the date in 10 days", "calculate"),
        # apps
        ("open chrome", "open_app"),
        ("close spotify", "close_app"),
        ("switch to whatsapp", "focus_app"),
        # music
        ("play despacito", "play_music"),
        ("play shape of you on spotify", "play_spotify"),
        ("play lofi on youtube", "play_youtube_song"),
        # whatsapp
        ("message rahul and say running late", "whatsapp_with_message"),
        ("whatsapp mom", "whatsapp_contact"),
        # web + system + info
        ("search for python tutorials", "search_web"),
        ("what is the capital of France", "answer_question"),  # answered aloud now
        ("what time is it", "tell_time"),
        ("set a timer for 5 minutes", "set_timer"),
        ("volume up", "volume_up"),
        ("take a screenshot", "screenshot"),
        ("who are you", "introduce"),
        ("what can you do", "show_help"),
        ("type hello world", "force_type"),
        ("this is just dictation", ""),
    ]
    fails = 0
    for phrase, want in cases:
        r = cp.process(phrase)
        if want == "force_type":
            ok = r.action == "force_type"          # typed, not executed
        else:
            ok = r.is_command == bool(want) and (not want or r.action == want)
        fails += not ok
        flag = "PASS" if ok else "FAIL"
        extra = ""
        if r.action == "calculate":
            extra = f"= {r.args.get('result')}"
        print(f"  [{flag}] {phrase!r:42} -> {r.action or '(dictation)'} {extra}")
    print(f"\n{len(cases) - fails}/{len(cases)} routed correctly")
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
