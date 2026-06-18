"""
conversation_state.py - Stateful multi-step conversation manager

Enables Jarvis-style sequential commands:
  "Open WhatsApp"       → state: AWAITING_CONTACT
  "Message Rahul"       → state: AWAITING_MESSAGE (contact = Rahul)
  "Hey how are you"     → sends "Hey how are you" to Rahul, state: IDLE

States:
  IDLE              - no active intent
  AWAITING_CONTACT  - we know the app, need a contact name
  AWAITING_MESSAGE  - we have contact, need the message text
  AWAITING_CONFIRM  - need yes/no confirmation (e.g. file delete)
  AWAITING_QUERY    - need a free-text query (e.g. "what to search?")

Timeout: each state auto-resets after TIMEOUT_SECONDS of inactivity.

Memory: pure Python dict + one threading.Timer — essentially zero overhead.
"""

import threading
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Any

logger = logging.getLogger(__name__)

# How long (seconds) to wait for the next step before resetting to IDLE
TIMEOUT_SECONDS = 15


# ─────────────────────────────────────────────────────────────────────
# State constants
# ─────────────────────────────────────────────────────────────────────

class State:
    IDLE             = "idle"
    AWAITING_CONTACT = "awaiting_contact"
    AWAITING_MESSAGE = "awaiting_message"
    AWAITING_CONFIRM = "awaiting_confirm"
    AWAITING_QUERY   = "awaiting_query"
    AWAITING_FILENAME= "awaiting_filename"


@dataclass
class ConversationContext:
    state:   str                    = State.IDLE
    intent:  str                    = ""           # e.g. "whatsapp", "file_delete"
    data:    dict                   = field(default_factory=dict)
    # callback to fire when the intent is fully resolved
    on_complete: Optional[Callable] = None
    # callback to fire on timeout
    on_timeout:  Optional[Callable] = None
    timestamp: float                = field(default_factory=time.time)


# ─────────────────────────────────────────────────────────────────────
# ConversationStateManager
# ─────────────────────────────────────────────────────────────────────

class ConversationStateManager:
    """
    Thread-safe multi-step conversation state machine.

    Usage:
        csm = ConversationStateManager(on_prompt=tts.speak)

        # Start a WhatsApp flow
        csm.begin_intent(
            intent="whatsapp",
            state=State.AWAITING_CONTACT,
            on_complete=my_send_function,
            prompt="Which contact should I message?",
        )

        # Next voice input routed here:
        handled = csm.handle_input("Rahul")
        # handled=True → consumed by state machine, don't type into app
    """

    def __init__(
        self,
        on_prompt: Optional[Callable[[str], None]] = None,
    ):
        self._ctx: ConversationContext = ConversationContext()
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._on_prompt = on_prompt or (lambda t: None)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def begin_intent(
        self,
        intent: str,
        state: str,
        on_complete: Callable,
        data: Optional[dict] = None,
        prompt: str = "",
        on_timeout: Optional[Callable] = None,
    ) -> None:
        """Start a new multi-step intent, replacing any existing one."""
        with self._lock:
            self._cancel_timer()
            self._ctx = ConversationContext(
                state=state,
                intent=intent,
                data=data or {},
                on_complete=on_complete,
                on_timeout=on_timeout,
                timestamp=time.time(),
            )
            self._start_timer()

        logger.info("ConvState: begin intent=%s state=%s", intent, state)
        if prompt:
            self._on_prompt(prompt)

    def handle_input(self, text: str) -> bool:
        """
        Attempt to handle text as part of an ongoing multi-step intent.

        Returns True  if the text was consumed by the state machine
                       (caller should NOT type it into the focused app).
        Returns False if no active intent — caller handles normally.
        """
        with self._lock:
            if self._ctx.state == State.IDLE:
                return False

            self._cancel_timer()
            consumed = self._advance(text)
            if self._ctx.state != State.IDLE:
                self._start_timer()
            return consumed

    def reset(self) -> None:
        """Reset to IDLE immediately (e.g. user says 'cancel')."""
        with self._lock:
            self._cancel_timer()
            self._ctx = ConversationContext()
        logger.info("ConvState: reset to IDLE")

    @property
    def state(self) -> str:
        return self._ctx.state

    @property
    def intent(self) -> str:
        return self._ctx.intent

    @property
    def is_idle(self) -> bool:
        return self._ctx.state == State.IDLE

    # ------------------------------------------------------------------
    # State machine transitions
    # ------------------------------------------------------------------

    def _advance(self, text: str) -> bool:
        """
        Move the state machine forward using the user's input.
        Must be called with self._lock held.
        Returns True if the input was consumed.
        """
        ctx = self._ctx
        text = text.strip()

        # ── Cancel / abort ──────────────────────────────────────────
        if text.lower() in ("cancel", "abort", "never mind", "stop", "exit"):
            logger.info("ConvState: user cancelled intent=%s", ctx.intent)
            self._ctx = ConversationContext()
            self._on_prompt("Okay, cancelled.")
            return True

        # ── WhatsApp flow ────────────────────────────────────────────
        if ctx.intent == "whatsapp":
            if ctx.state == State.AWAITING_CONTACT:
                ctx.data["contact"] = text
                ctx.state = State.AWAITING_MESSAGE
                self._on_prompt(f"What should I say to {text}?")
                logger.info("ConvState: contact=%s, now awaiting message", text)
                return True

            elif ctx.state == State.AWAITING_MESSAGE:
                ctx.data["message"] = text
                logger.info("ConvState: message=%r, completing", text[:40])
                fn = ctx.on_complete
                data = dict(ctx.data)
                self._ctx = ConversationContext()   # reset before calling
                if fn:
                    threading.Thread(
                        target=fn, kwargs=data, daemon=True
                    ).start()
                return True

        # ── File delete confirmation ─────────────────────────────────
        elif ctx.intent == "file_delete":
            if ctx.state == State.AWAITING_CONFIRM:
                if text.lower() in ("yes", "yeah", "confirm", "do it", "delete it", "sure"):
                    fn = ctx.on_complete
                    data = dict(ctx.data)
                    self._ctx = ConversationContext()
                    if fn:
                        threading.Thread(
                            target=fn, kwargs=data, daemon=True
                        ).start()
                    self._on_prompt("Deleted.")
                else:
                    self._ctx = ConversationContext()
                    self._on_prompt("Okay, not deleted.")
                return True

        # ── Generic confirmation (destructive system actions) ────────
        elif ctx.intent == "confirm_action" and ctx.state == State.AWAITING_CONFIRM:
            yes = text.lower() in ("yes", "yeah", "yep", "confirm", "do it",
                                   "go ahead", "sure", "proceed", "okay", "ok",
                                   "affirmative", "yes please")
            fn = ctx.on_complete
            cancel_msg = ctx.data.get("_cancel_msg", "Okay, cancelled.")
            self._ctx = ConversationContext()   # reset before acting
            if yes and fn:
                threading.Thread(target=fn, daemon=True).start()
            else:
                self._on_prompt(cancel_msg)
            return True

        # ── Generic awaiting query ───────────────────────────────────
        elif ctx.state == State.AWAITING_QUERY:
            ctx.data["query"] = text
            fn = ctx.on_complete
            data = dict(ctx.data)
            self._ctx = ConversationContext()
            if fn:
                threading.Thread(
                    target=fn, kwargs=data, daemon=True
                ).start()
            return True

        # Unknown / fallthrough — don't consume
        return False

    # ------------------------------------------------------------------
    # Timeout
    # ------------------------------------------------------------------

    def _start_timer(self) -> None:
        self._timer = threading.Timer(TIMEOUT_SECONDS, self._on_timeout)
        self._timer.daemon = True
        self._timer.start()

    def _cancel_timer(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _on_timeout(self) -> None:
        with self._lock:
            old_intent = self._ctx.intent
            cb = self._ctx.on_timeout
            self._ctx = ConversationContext()
            self._timer = None
        logger.info("ConvState: timeout — reset from intent=%s", old_intent)
        if cb:
            cb()
        else:
            self._on_prompt("No response received. Returning to standby.")


# ─────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import time
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    results = []

    def on_complete(contact="", message=""):
        results.append({"contact": contact, "message": message})
        print(f"  >> COMPLETE: send '{message}' to '{contact}'")

    csm = ConversationStateManager(on_prompt=lambda t: print(f"  [TTS] {t}"))

    print("Test 1: WhatsApp multi-step flow")
    csm.begin_intent(
        intent="whatsapp",
        state=State.AWAITING_CONTACT,
        on_complete=on_complete,
        prompt="Who do you want to message?",
    )
    assert not csm.is_idle
    consumed = csm.handle_input("Rahul")
    assert consumed
    assert csm.state == State.AWAITING_MESSAGE
    consumed = csm.handle_input("Hey bro what's up")
    assert consumed
    time.sleep(0.1)
    assert csm.is_idle
    assert results[0]["contact"] == "Rahul"
    assert results[0]["message"] == "Hey bro what's up"
    print("  PASS")

    print("Test 2: Cancel mid-flow")
    csm.begin_intent(
        intent="whatsapp",
        state=State.AWAITING_CONTACT,
        on_complete=on_complete,
        prompt="Who?",
    )
    csm.handle_input("cancel")
    assert csm.is_idle
    print("  PASS")

    print("All tests passed!")
