# NirmiqEcho

A local-first **JARVIS-style voice assistant** for Windows. Speak, and it acts —
opening apps, messaging on WhatsApp, playing music, finding files, doing math,
controlling the system. Runs in your system tray. Your voice never leaves your
machine.

## Run it

```
start.bat
```

A mic icon appears in your system tray. Press **F9** to start/stop listening
(or enable "Hello Echo" wake word). Then just talk:

> "open chrome" · "play despacito" · "message Rahul saying running late"
> "what's 47 times 19" · "set a timer for 10 minutes" · "find my resume"
> "take a screenshot" · "volume up" · "what time is it"

First run installs dependencies and loads the Whisper model from `models/`.

## How it understands you

Two layers, so it's both **instant** and **flexible**:

1. **Offline command engine** — 90+ built-in patterns (apps, WhatsApp, Spotify,
   files, math, units, system control). Runs locally with faster-whisper, no
   internet, ~1-2s. This is the dependable core.
2. **Local-LLM fallback (optional)** — if you phrase something it doesn't
   recognise ("fire up my browser", "I wanna hear some lofi"), Echo asks a
   **local Ollama model** to map it to a known command. Fully offline (localhost,
   no API key). If Ollama isn't running, this is skipped instantly and Echo keeps
   working with the built-in commands.

To enable the fallback: install [Ollama](https://ollama.com), `ollama pull
qwen3.5:4b`, and keep it running. Configure in `.env` (see `.env.example`).

## Accuracy & mic

- Whisper auto-selects **large-v3 on GPU** (≈99% on the owner's voice) or
  **small.en on CPU**. Override with `WHISPER_MODEL` in `.env`.
- The mic is self-healing: it auto-unmutes a Windows-muted default mic, skips
  driver spin-up silence, and scans for a live device if the default is dead
  (e.g. idle Bluetooth buds). Diagnose anytime:
  `cd voiceflow_local && python mic_check.py`.

## Layout

```
NirmiqEcho/
├── start.bat              ← launch the assistant
├── voiceflow_local/       ← the app
│   ├── main.py            ← entry point / orchestrator
│   ├── audio_handler.py   ← mic capture + VAD + noise reduction
│   ├── transcription.py   ← faster-whisper (GPU/CPU auto)
│   ├── command_processor.py ← 90+ offline commands
│   ├── llm_fallback.py    ← optional local-Ollama "understand anything"
│   ├── calculator.py · units.py ← offline math / conversions
│   ├── wake_word.py · tts_engine.py · ui.py (tray) · ...
│   └── mic_check.py       ← mic diagnostic
├── models/                ← faster-whisper cache (gitignored)
├── Test*.m4a              ← your voice samples (accent profiling)
├── .env.example           ← copy to .env to configure
└── install_autostart.bat  ← optional: launch at login
```

## Safety

Voice-driven OS automation, hardened: voice-derived text never reaches a shell
(`shell=True` is never used; app/process names are whitelist-validated),
high-risk actions (file delete, etc.) confirm first, and the LLM fallback only
*rewrites* into the same whitelisted commands — it never executes free-form
output.

---
*Part of the Nirmiq umbrella. Built by Siddharth.*
