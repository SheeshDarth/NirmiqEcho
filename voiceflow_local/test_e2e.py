"""
test_e2e.py — headless end-to-end integration test for NirmiqEcho

Wires the REAL subsystems exactly like main.py (minus tkinter UI and mic),
then pushes transcripts through the full path:
    text -> PostProcessor -> CommandProcessor.process -> execute

Proves whether a spoken command actually performs work. Pass a transcript
on the command line to fire a single real command:
    python test_e2e.py "open notepad"
Otherwise runs a dry-run matrix that classifies (but does not execute)
side-effecting commands.
"""
import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)-18s %(message)s")
log = logging.getLogger("e2e")


def build_stack():
    """Instantiate the same subsystems main.py wires, without UI/audio."""
    from post_processor import PostProcessor
    from command_processor import CommandProcessor

    feedback = []
    pp = PostProcessor()
    cp = CommandProcessor(on_feedback=lambda m: feedback.append(m))

    # Give the background subsystem thread a moment (TTS, conv state, discovery)
    for _ in range(40):
        if cp._conv is not None and cp._discovery is not None:
            break
        time.sleep(0.1)

    log.info("subsystems ready: conv=%s discovery=%s tts=%s file=%s",
             cp._conv is not None, cp._discovery is not None,
             cp._tts is not None, cp._file_assistant is not None)
    return pp, cp, feedback


def run_one(pp, cp, feedback, raw_text, execute=True):
    """Mirror NirmiqEchoApp._on_result for a single transcript."""
    feedback.clear()
    cleaned = pp.clean(raw_text)
    if not cleaned:
        print(f"  {raw_text!r} -> dropped by post-processor (hallucination/empty)")
        return
    result = cp.process(cleaned)
    tag = "CMD" if result.is_command else "TYPE"
    line = f"  {raw_text!r} -> clean={cleaned!r} -> [{tag}] action={result.action!r}"
    if result.feedback:
        line += f" feedback={result.feedback!r}"
    print(line)
    if execute and result.is_command:
        cp.execute(result)
        time.sleep(0.3)
        if feedback:
            print(f"        executed; feedback: {feedback}")


# Commands that are safe to actually run during a single-arg live test
SAFE_TO_EXECUTE = True


def main():
    pp, cp, feedback = build_stack()

    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
        print(f"\n=== LIVE EXECUTION: {text!r} ===")
        run_one(pp, cp, feedback, text, execute=True)
        time.sleep(1.0)
        return

    print("\n=== DRY-RUN CLASSIFICATION MATRIX (no execution) ===")
    matrix = [
        "open notepad", "what time is it", "what's the battery",
        "search for python tutorials", "play despacito",
        "message mom and say running late", "set a timer for 5 minutes",
        "volume up", "scroll down", "take a screenshot",
        "who are you", "what can you do", "good morning",
        "lock screen", "find my resume", "open downloads",
        "this is just some dictation text", "thanks for watching",
    ]
    cmd_count = 0
    for t in matrix:
        feedback.clear()
        cleaned = pp.clean(t)
        if not cleaned:
            print(f"  {t!r} -> dropped (hallucination filter)")
            continue
        r = cp.process(cleaned)
        if r.is_command:
            cmd_count += 1
        tag = "CMD " if r.is_command else "TYPE"
        print(f"  [{tag}] {t!r} -> {r.action}")
    print(f"\n{cmd_count}/{len(matrix)} classified as commands")


if __name__ == "__main__":
    main()
