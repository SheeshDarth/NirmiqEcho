"""Verify the LLM fallback + that regex commands still work, with and
without Ollama. Run from voiceflow_local: python test_fallback.py"""
import os
import time
import command_processor as cp_mod


def regression(cp):
    print("=== regex regression (no LLM needed) ===")
    cases = [("open chrome", "open_app"), ("what time is it", "tell_time"),
             ("play despacito", "play_music"), ("set volume to 40", "set_volume"),
             ("calculate 50 times 4", "calculate")]
    ok = 0
    for text, want in cases:
        r = cp.process(text)
        good = r.action == want
        ok += good
        print(f"  [{'PASS' if good else 'FAIL'}] {text!r:28} -> {r.action}")
    print(f"  {ok}/{len(cases)} regex commands intact\n")


def main():
    cp = cp_mod.CommandProcessor()
    time.sleep(1.5)
    regression(cp)

    import llm_fallback
    print(f"=== Ollama available: {llm_fallback.is_available()} ===")

    novel = ["fire up my browser",
             "I wanna hear some lofi beats",
             "what's forty seven times nineteen",
             "the weather is really nice today"]   # last = dictation, expect NONE
    print("=== novel phrasings through full process() ===")
    for text in novel:
        t0 = time.monotonic()
        r = cp.process(text)
        dt = time.monotonic() - t0
        tag = f"COMMAND={r.action}" if r.is_command else "dictation (typed)"
        print(f"  {text!r:42} -> {tag}   ({dt:.1f}s)")


if __name__ == "__main__":
    main()
