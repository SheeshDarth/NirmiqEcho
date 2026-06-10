"""
NirmiqEcho — main entry point
══════════════════════════════════════════════════════════════════
Thread layout:
  main thread   → pystray (required by Windows)
  tray-overlay  → tkinter overlay window
  whisper-loader→ downloads / loads faster-whisper model
  nirmiq-listener → sounddevice capture + VAD + transcription
  nirmiq-tts    → pyttsx3 speech synthesis
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import tts
from overlay import EchoOverlay
from tray    import EchoTray
from voice   import VoiceListener, load_model, is_model_ready
from intent_parser import parse_intent_sync
from dispatcher    import execute


# ── state ─────────────────────────────────────────────────────────────
_overlay: EchoOverlay | None = None
_listener: VoiceListener | None = None
_tray: EchoTray | None = None


# ── voice pipeline ────────────────────────────────────────────────────

def on_transcript(text: str):
    """Called from listener thread when an utterance is complete."""
    print(f"[echo] heard: {text}")
    if _overlay:
        _overlay.set_transcript(text)
        _overlay.set_state("processing")

    intent  = parse_intent_sync(text)
    result  = execute(intent)

    print(f"[echo] → {intent['intent']} → {result}")
    if _overlay:
        _overlay.set_response(result)
        _overlay.set_state("idle")

    tts.speak(result)


def on_state_change(state: str):
    """Called from listener thread on VAD state changes."""
    if _overlay:
        _overlay.set_state(state)
    if _tray:
        _tray.set_state(state)


def on_model_ready():
    print("[echo] Whisper model ready.")
    tts.speak("Nirmiq Echo is ready. Listening.")
    on_state_change("idle")


# ── tray callbacks ────────────────────────────────────────────────────

def toggle_listen():
    if _listener:
        if _listener.muted:
            _listener.unmute()
            tts.speak("Listening resumed.")
        else:
            _listener.mute()
            tts.speak("Microphone muted.")


def toggle_mute():
    toggle_listen()


def show_overlay():
    if _overlay:
        _overlay.show()


def on_quit():
    print("[echo] Quitting.")
    if _listener:
        _listener.stop()
    tts.stop()
    sys.exit(0)


# ── startup ───────────────────────────────────────────────────────────

def _start_overlay():
    global _overlay
    _overlay = EchoOverlay(on_close_to_tray=lambda: None)
    _overlay.run()   # blocks this thread


def main():
    global _listener, _tray

    print("""
  ███╗   ██╗██╗██████╗ ███╗   ███╗██╗ ██████╗
  ████╗  ██║██║██╔══██╗████╗ ████║██║██╔═══██╗
  ██╔██╗ ██║██║██████╔╝██╔████╔██║██║██║   ██║
  ██║╚██╗██║██║██╔══██╗██║╚██╔╝██║██║██║▄▄ ██║
  ██║ ╚████║██║██║  ██║██║ ╚═╝ ██║██║╚██████╔╝
  ╚═╝  ╚═══╝╚═╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝ ╚══▀▀═╝
              E C H O  v1.0
    """)

    # ── start TTS first ───────────────────────────────────────────────
    tts.start()

    # ── launch overlay in its own thread ─────────────────────────────
    overlay_thread = threading.Thread(target=_start_overlay, daemon=True, name="overlay")
    overlay_thread.start()

    # ── start Whisper model load (background) ────────────────────────
    load_model(on_ready=on_model_ready)
    print("[echo] Loading Whisper model in background…")

    # ── start voice listener ─────────────────────────────────────────
    _listener = VoiceListener(
        on_transcript=on_transcript,
        on_state_change=on_state_change,
    )
    _listener.start()
    print("[echo] Microphone listener started.")

    # ── system tray (blocks main thread — required on Windows) ───────
    _tray = EchoTray(
        on_toggle_listen=toggle_listen,
        on_toggle_mute=toggle_mute,
        on_show_overlay=show_overlay,
        on_quit=on_quit,
    )
    _tray.set_state("loading")
    _tray.run()   # ← blocks here until quit


if __name__ == "__main__":
    main()
