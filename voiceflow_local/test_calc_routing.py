import time
import command_processor as m

cp = m.CommandProcessor()
time.sleep(2)
cases = [
    ("add 45 and 30", "calculate"),
    ("what is 12 times 8", "calculate"),
    ("15 percent of 200", "calculate"),
    ("square root of 144", "calculate"),
    ("what is the capital of France", "answer_question"),  # spoken answer now
    ("what time is it", "tell_time"),
    ("search for python tutorials", "search_web"),
    ("open chrome", "open_app"),
]
fails = 0
for phrase, want in cases:
    r = cp.process(phrase)
    extra = r.args.get("result") if r.action == "calculate" else ""
    ok = r.action == want
    fails += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {phrase!r:35} -> {r.action} {extra}")
print(f"\n{len(cases)-fails}/{len(cases)} routed correctly")
