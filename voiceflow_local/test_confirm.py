"""Destructive commands must require spoken confirmation (no instant misfire)."""
import time
import command_processor as m


def main():
    cp = m.CommandProcessor()
    time.sleep(1.5)  # let subsystems (conv state) initialise
    fails = 0

    for cmd in ("shutdown", "restart", "sleep", "empty the recycle bin"):
        r = cp.process(cmd)
        cp.execute(r)                      # should ARM confirmation, NOT act
        armed = cp._conv is not None and not cp._conv.is_idle
        # cancel it so the next case starts clean and nothing executes
        cancelled = cp.process("cancel")
        ok = r.is_command and armed
        fails += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {cmd!r:24} -> command={r.is_command} "
              f"armed_confirmation={armed}")

    # lock screen stays instant (non-destructive) — should NOT arm a confirm
    r = cp.process("lock screen")
    print(f"  [info] 'lock screen' -> action={r.action} (instant, no confirm by design)")

    print(f"\n{4 - fails}/4 destructive commands correctly gated")
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
