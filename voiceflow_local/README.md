# `voiceflow_local/` — NirmiqEcho application package

This folder is the NirmiqEcho app itself. **The canonical documentation lives at the
repository root** — start there:

- [`../README.md`](../README.md) — what NirmiqEcho is, how to run it, the command surface
- [`../SECURITY.md`](../SECURITY.md) — threat model and hardening
- [`../DEPLOY.md`](../DEPLOY.md) — deployment / first-run notes

## Run

From the repo root, double-click **`start.bat`** (installs deps on first run, then
launches the tray app). For development, from this directory:

```bat
python main.py
```

## Module map

| File | Responsibility |
|------|----------------|
| `main.py` | App orchestrator (`NirmiqEchoApp`) — wires subsystems, the `_on_result` pipeline, F9 hotkey, wake word, tray lifecycle |
| `audio_handler.py` | Mic capture + hybrid VAD + noise reduction + mic auto-rescue |
| `transcription.py` | faster-whisper STT (GPU `large-v3` / CPU `small.en`, auto-select) |
| `wake_word.py` | "Hello Echo" wake-word detector |
| `post_processor.py` | Transcript cleanup + hallucination filter |
| `accent_profile.py` | Accent-tuned Whisper `initial_prompt` from voice samples |
| `command_processor.py` | The command engine — patterns, routing, dispatch, confirmation gate, audit |
| `calculator.py` · `units.py` | Offline math (restricted-AST) and unit/date conversions |
| `knowledge.py` | Spoken Q&A (Wikipedia → local Ollama → web fallback) |
| `llm_fallback.py` | Optional local-Ollama "understand anything" fallback |
| `conversation_state.py` | Multi-step intent FSM (WhatsApp flow, confirmations) |
| `file_assistant.py` | File find / open / move / Recycle-Bin delete |
| `app_discovery.py` | Windows app discovery (registry + Start Menu + protocol URIs) |
| `tts_engine.py` | Offline TTS (pyttsx3 / SAPI) |
| `typer.py` | Clipboard / keystroke text injection |
| `ui.py` | tkinter + pystray system-tray UI |
| `utils.py` | Logging, `HotkeyManager`, system-info probes |
| `mic_check.py` | Standalone mic diagnostic (`python mic_check.py`) |

## Tests

Repeatable offline suites live alongside the modules (`calculator.py`, `units.py`,
`test_*.py`); manual / live-dependency scripts (full app launch, model benchmarks,
live-Ollama checks) live under [`tests/manual/`](tests/manual). CI runs the offline
logic + security suites on every push.
