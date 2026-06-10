# NirmiqEcho — codename **WRAITH**

> **W**indows **R**esident **A**ssistant — **I**ntelligent, **T**otally **H**eadless

**Every Command, Handled Offline.**

A Jarvis-grade voice assistant that lives in your system tray. 100% local,
100% offline, zero cloud. Your voice never leaves your laptop.

```
███╗   ██╗██╗██████╗ ███╗   ███╗██╗ ██████╗     ███████╗ ██████╗██╗  ██╗ ██████╗
████╗  ██║██║██╔══██╗████╗ ████║██║██╔═══██╗    ██╔════╝██╔════╝██║  ██║██╔═══██╗
██╔██╗ ██║██║██████╔╝██╔████╔██║██║██║   ██║    █████╗  ██║     ███████║██║   ██║
██║╚██╗██║██║██╔══██╗██║╚██╔╝██║██║██║▄▄ ██║    ██╔══╝  ██║     ██╔══██║██║   ██║
██║ ╚████║██║██║  ██║██║ ╚═╝ ██║██║╚██████╔╝    ███████╗╚██████╗██║  ██║╚██████╔╝
╚═╝  ╚═══╝╚═╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝ ╚══▀▀═╝     ╚══════╝ ╚═════╝╚═╝  ╚═╝ ╚═════╝
```

## Quick start

Double-click **`start.bat`**. That's it.

- First run installs dependencies automatically
- Whisper large-v3 loads from the local `models/` cache (no download)
- A mic icon appears in your **system tray** — Echo is alive
- Press **F9** to start/stop listening, or enable **Echo Mode** and just say
  **"Hello Echo"**

## What it can do

| Say | What happens |
|-----|--------------|
| "Open Chrome" / "Close Spotify" | Launches/kills any installed app (registry + Start Menu discovery) |
| "Message Rahul and say I'll be late" | Opens WhatsApp, finds Rahul, types + sends |
| "Play Shape of You" | Local file → Spotify → YouTube, in that order |
| "Find my resume" / "Open the budget file" | Fuzzy file search across Desktop/Documents/Downloads |
| "Set a timer for 10 minutes" | Timer with voice + popup alert |
| "What time is it" / "Battery" | Spoken answers |
| "Volume up" / "Set volume to 40" / "Brightness down" | System control |
| "Scroll down" / "New tab" / "Switch window" / "Snap left" | Navigation |
| "Take a screenshot" / "Lock screen" / "Empty recycle bin" | System actions |
| "Type [anything]" | Dictates into whatever app has focus |
| "What can you do?" | Echo introduces its abilities |
| "Who are you?" | Meet WRAITH |
| Anything else | Typed into the focused window (dictation mode) |

60+ command patterns. Multi-step conversations ("Message Rahul" → *"What
should I say?"* → speak your message → sent).

## Architecture (all local, all offline)

```
mic → webrtcvad (VAD, pre-boosted for quiet voices)
    → noisereduce (spectral subtraction, ambient noise profile)
    → gain normalisation
    → faster-whisper large-v3 (int8, ~98% accuracy, accent-tuned prompt)
    → PostProcessor (fillers, accent corrections, hallucination filter)
    → CommandProcessor (60+ regex patterns, conversation state machine)
    → execute │ dictate
    → pyttsx3 TTS (Windows SAPI — offline voice feedback)
```

| Component | Tech | RAM |
|-----------|------|-----|
| Transcription | faster-whisper large-v3, int8 | ~3 GB |
| Wake word | faster-whisper tiny.en | ~80 MB |
| TTS | Windows SAPI (pyttsx3) | ~3 MB |
| Tray + UI | pystray + tkinter | ~30 MB |

**Lighter machine?** Set `WHISPER_MODEL=medium.en` (~1.5 GB, 96%) or
`small.en` (~500 MB, 93%) in `.env`.

## Tuning (.env)

| Variable | Default | Notes |
|----------|---------|-------|
| `WHISPER_MODEL` | `large-v3` | Already downloaded in `models/` |
| `NOISE_REDUCE_STRENGTH` | `0.65` | Raise to 0.8 in very noisy rooms |
| `SPEECH_RMS_THRESHOLD` | `400` | Legacy prototype setting only |

In-app Settings (gear icon): VAD sensitivity 0–3, language, typing mode,
re-analyse voice samples.

## Verify accuracy on your own voice

```
cd voiceflow_local
python test_accuracy.py            # large-v3 (default)
python test_accuracy.py medium.en  # compare models
```

Transcribes the `Test*.m4a` samples through the exact production pipeline
and prints text + real-time factor.

## Project layout

```
Voice-text/
├── start.bat            ← double-click to launch
├── .env                 ← config (created on first run)
├── models/              ← Whisper models (gitignored, ~3 GB)
├── Test*.m4a            ← your voice samples (accent profiling)
├── voiceflow_local/     ← THE app (its own git repo, full history)
│   ├── main.py          ← entry point + app controller
│   ├── audio_handler.py ← mic, VAD, noise reduction
│   ├── transcription.py ← faster-whisper engine
│   ├── command_processor.py ← 60+ Jarvis commands
│   ├── ui.py            ← tray icon + floating window
│   ├── wake_word.py     ← "Hello Echo" detector
│   └── ...
└── legacy_prototype/    ← earlier root-level prototype (archived)
```

---
*NirmiqEcho is part of the Nirmiq umbrella. Built by Siddharth.*
