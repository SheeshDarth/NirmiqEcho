# NirmiqEcho

A local-first voice assistant for Windows. Your speech, understood and acted on
entirely on your machine — no cloud.

This folder holds **two implementations** that share the same Whisper models and
voice samples. Pick the one you want to run:

| | What it is | Run it |
|---|---|---|
| **voiceflow_local/** | The shipping **tkinter Jarvis** — system-tray app, 90+ regex/offline commands (apps, WhatsApp, Spotify, files, math, units), faster-whisper, mic auto-rescue. Fast, fully offline, no LLM. | double-click **`start.bat`** |
| **core/ + ui/** | The newer **voice OS** — a local LLM (Ollama) plans your intent into verified tool steps, FastAPI + WebSocket backend, browser dashboard. "Understand anything" phrasing. | `pip install -e .` then `python -m core.main`, open http://127.0.0.1:8766 |

Both are NirmiqEcho. The tray app is the dependable daily driver; the OS is the
LLM-planner future. They were merged into one folder so they share `models/`
and the `Test*.m4a` accent samples.

## Quick start — tray Jarvis (no setup)

```
start.bat
```
Look for the mic icon in the system tray. Press F9 to listen. Say "open chrome",
"what is 50 times 4", "message Rahul saying running late", etc.

## Quick start — voice OS (needs Ollama)

```
pip install -e .
ollama serve              # keep this running — the planner needs it
python -m core.main       # backend + dashboard at http://127.0.0.1:8766
set NIRMIQ_VOICE=1 && python -m core.main   # also listen on the mic
```
Type or speak a command; watch it plan and execute live in the dashboard.
The OS reuses the `models/` cache here, so no multi-GB re-download.

## Layout

```
NirmiqEcho/
├── start.bat              ← launches the tray Jarvis
├── voiceflow_local/       ← tray Jarvis app (Python, tkinter, regex engine)
├── legacy_prototype/      ← archived early prototype
│
├── pyproject.toml         ← the voice OS package
├── setup.bat              ← installs the OS + runs its tests
├── core/                  ← OS backend: voice, engine (planner/executor),
│                            models (Ollama), tools (21), memory, api
├── ui/web/                ← OS dashboard (served by the backend)
├── tests/                 ← OS test suite (pytest)
├── plugins/ · config/     ← OS plugin interface + config
│
├── models/                ← shared faster-whisper cache (gitignored)
├── Test*.m4a              ← your voice samples (accent profiling)
└── assets/                ← accent profile, icons
```

## Security

The voice OS executes real actions, so it is hardened: tools self-verify
(never fake success), the planner only runs whitelisted tools with validated
args (never raw LLM output), HIGH-risk steps (delete, terminal) require explicit
confirmation, destructive shell commands are blocklisted, file writes to
system/startup locations are refused, the server binds to localhost and rejects
cross-origin browser requests, and the dashboard escapes all untrusted text.

---
*Part of the Nirmiq umbrella. Built by Siddharth.*
