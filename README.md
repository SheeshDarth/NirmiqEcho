# NirmiqEcho

A local-first **JARVIS-style voice assistant** for Windows. Speak, and it acts —
opening apps, messaging on WhatsApp, playing music, finding files, doing math,
controlling the system. Runs in your system tray. Your voice never leaves your
machine.

![CI](https://github.com/SheeshDarth/NirmiqEcho/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Offline](https://img.shields.io/badge/cloud-none-success)
![Platform](https://img.shields.io/badge/platform-Windows-0078D6)

<!-- DEMO: record a 15–20s clip (e.g. ScreenToGif / OBS) of a few neutral
     commands — "open calculator", "what is 12 times 8", "tell me a joke" —
     save it as docs/demo.gif, then uncomment the next line:
![NirmiqEcho demo](docs/demo.gif)
-->

## Why it's different

Most "build Jarvis in Python" projects are *either* brittle keyword-matching
*or* a thin wrapper around a cloud LLM. NirmiqEcho is neither:

- 🧠 **Hybrid intelligence, 100% offline** — instant offline pattern engine for
  known commands **+** a *local* Ollama LLM fallback that understands free-form
  phrasing, with graceful degradation when the LLM is off. No cloud, no API key.
- 🔒 **Privacy by construction** — speech-to-text (faster-whisper) and TTS run
  on-device; nothing is sent anywhere. See [SECURITY.md](SECURITY.md).
- 🛡️ **Hardened OS automation** — no `shell=True`, whitelist-validated app names,
  and destructive actions (shutdown / delete) require spoken confirmation.
- 🎙️ **Production resilience** — self-healing mic (auto-unmute, dead-device
  scan), GPU/CPU auto-selection with a fallback ladder, hallucination filtering.
- ✅ **Tested & CI'd** — offline logic suites + a security guard run on every push.

## Run it

```
start.bat
```

A mic icon appears in your system tray. Press **F9** to start/stop listening
(or enable "Hello Echo" wake word). Then just talk:

> "open chrome" · "play despacito" · "message Rahul saying running late"
> "what's 47 times 19" · "set a timer for 10 minutes" · "find my resume"
> "take a screenshot" · "volume up" · "what time is it"
> "who is Einstein" · "what is photosynthesis" · "tell me a joke"
> "remember that my locker code is 4821" · "what do you remember" · "cpu usage"

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
   working with the built-in commands. It also carries **one turn of context**,
   so follow-ups resolve — "what is the Eiffel Tower" → "how tall is it".

To enable the fallback: install [Ollama](https://ollama.com), `ollama pull
qwen3.5:4b`, and keep it running. Configure in `.env` (see `.env.example`).

```mermaid
flowchart LR
    M[🎤 Mic] --> V[VAD + noise reduction]
    V --> W[faster-whisper<br/>GPU large-v3 / CPU small.en]
    W --> P{Command engine}
    P -->|exact match| R[Regex / math / units<br/>~instant]
    P -->|no match| C[commands.yaml<br/>your custom phrases]
    P -->|still no match| L[Local Ollama<br/>rewrite → known command]
    R --> X[Validate → confirm if risky → execute]
    C --> X
    L --> X
    X --> T[🔊 Spoken reply]
```

## Add your own commands

Drop a `commands.yaml` next to `start.bat` (copy `commands.example.yaml`) and map
any spoken phrase to a built-in action — no code, fully offline:

```yaml
commands:
  - phrase: "fire up my editor"
    action: open_app
    args: { app_name: code }
  - phrase: "focus mode"
    action: play_spotify
    args: { query: lofi focus beats }
```

For safety, phrases can only bind to **non-destructive** actions (open / play /
search / type / info) — never shutdown, delete, or message-send — and each one
still runs through the same validation as a built-in command.

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

Voice-driven OS automation, hardened (full threat model in [SECURITY.md](SECURITY.md)):

- Voice-derived text **never reaches a shell** — no `shell=True`, no `eval`;
  app/process names are whitelist-validated, protocol launches are allow-listed.
- **Destructive actions require spoken confirmation** — `shutdown`, `restart`,
  `sleep`, `empty recycle bin`, and file delete all ask "say yes to confirm"
  first, so a misheard command can't halt or wipe the machine.
- The **LLM fallback only *rewrites*** into the same whitelisted commands — it
  never executes free-form model output.
- **Offline by default** — a loud warning fires if `OLLAMA_URL` is pointed off
  the machine. Every command is recorded to a local, gitignored audit log.

---
*Part of the Nirmiq umbrella. Built by Siddharth.*
