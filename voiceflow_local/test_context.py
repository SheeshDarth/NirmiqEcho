"""
Multi-turn context: a follow-up's pronouns resolve against the previous request
by passing the last exchange to the LLM fallback. Deterministic — the fallback
is monkeypatched, so this needs neither Ollama nor any side effects.

Windows-only (constructs CommandProcessor, which touches winreg); run locally.
"""
import time

import command_processor as m
import llm_fallback


def main():
    cp = m.CommandProcessor()
    time.sleep(1)
    cp._mode = "default"
    fails = 0

    captured = {}
    llm_fallback.map_to_command = (
        lambda text, context="": (captured.update(text=text, context=context) or None))

    # Prior turn established the topic; follow-up uses a pronoun.
    cp._recent = "what is the eiffel tower"
    captured.clear()
    cp.process("how tall is it")     # regex misses -> fallback with context
    ok = (captured.get("text") == "how tall is it"
          and captured.get("context") == "what is the eiffel tower")
    fails += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] follow-up carries prior context to the LLM")

    # No prior turn -> empty context (still works, just no resolution).
    cp._recent = ""
    captured.clear()
    cp.process("zibble the wozzle")
    ok = captured.get("context") == ""
    fails += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] no prior turn -> empty context (graceful)")

    print(f"\n{2 - fails}/2 multi-turn context tests passed")
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
