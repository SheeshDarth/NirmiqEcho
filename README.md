# NirmiqEcho 🎙️

**A 100% offline, privacy-first voice typing desktop app for Windows.**

No API keys. No cloud. No subscriptions. Just Whisper AI running entirely on your machine.

---

## ✨ Features

| Feature | Details |
|---|---|
| 🔒 100% Offline | Zero network calls — works with internet disconnected |
| ⚡ Low Latency | WebRTC VAD streaming — transcribes on natural pauses |
| 🎯 High Accuracy | Whisper `medium` (CPU) or `large-v3` (GPU) |
| ⌨️ Auto-typing | Injects text directly into any active window |
| 🔥 Auto GPU/CPU | Detects CUDA automatically — `float16` on GPU, `int8` on CPU |
| 🎛️ Smart VAD | WebRTC VAD — ignores noise, detects real speech only |
| 📋 Transcript | Copy, Save, and Clear your full session transcript |
| ⌨️ F9 Hotkey | Global toggle — works even when the window is not focused |
| 🪟 Floating UI | Compact always-on-top dark overlay |

---

## 📁 Project Structure

```
NirmiqEcho/
├── main.py              # App controller and entry point
├── audio_handler.py     # Microphone capture + WebRTC VAD
├── transcription.py     # faster-whisper engine (CPU / GPU)
├── typer.py             # Auto-typing via clipboard + pyautogui
├── ui.py                # Minimal dark Tkinter GUI
├── utils.py             # Logging, hotkeys, system diagnostics
├── requirements.txt     # Python dependencies
├── setup.bat            # Windows one-click installer
└── .gitignore
```

---

## 🚀 Quick Start

### 1. Install Python 3.10+
Download from [python.org/downloads](https://python.org/downloads)
> ⚠️ Check **"Add Python to PATH"** during install.

### 2. Install dependencies
```bat
pip install -r requirements.txt
```

### 3. Run
```bat
python main.py
```

> **First run** downloads the Whisper model (~769 MB for `medium`). Cached permanently after that — fully offline from then on.

---

## 🖥️ GPU Setup (Optional — 3-5× faster)

```bat
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

NirmiqEcho auto-detects CUDA and switches to `large-v3` + `float16` automatically.

---

## 🎛️ How to Use

1. Launch: `python main.py`
2. Wait for model to load (status shows **● Ready**)
3. Click **▶ Start** or press **F9**
4. Speak — status shows **◉ Speaking** when your voice is detected
5. Pause — text is transcribed and typed into your active window
6. Click **■ Stop** or press **F9** again to stop

### Controls

| Button | Action |
|---|---|
| ▶ Start | Begin listening |
| ■ Stop | Stop listening |
| ⎘ Copy | Copy transcript to clipboard |
| 💾 Save | Save transcript to .txt file |
| 🗑 Clear | Clear the transcript panel |
| F9 | Global toggle hotkey |
| 📌 Pin | Toggle always-on-top |
| VAD slider | Adjust noise sensitivity (0–3) |

---

## ⚙️ Model Selection

| Hardware | Model | Compute | Approx. Speed |
|---|---|---|---|
| CPU | `medium` | `int8` | ~1–2s per utterance |
| NVIDIA GPU | `large-v3` | `float16` | ~0.2–0.5s per utterance |

To override: pass `model_size="small"` to `TranscriptionEngine` in `main.py`.

---

## 🔧 Troubleshooting

### `webrtcvad` install fails on Windows
```bat
pip install webrtcvad-wheels
```

### Hotkeys (F9) not working
Run Command Prompt as Administrator, then `python main.py`.

### Text not being typed
- Ensure `pyperclip` is installed: `pip install pyperclip`
- Click the target app first, then press F9

### Slow on CPU
Switch to `small` model in `transcription.py` for ~0.5s latency.

### CUDA out of memory
Switch to `medium` or `small` model, or set `device="cpu"` in `TranscriptionEngine`.

---

## 🛡️ Privacy

- Zero network traffic (verified — works with internet off)
- Audio never leaves your machine
- No accounts, no telemetry, no analytics
- MIT License — free for personal and commercial use
