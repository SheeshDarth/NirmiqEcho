# VoiceFlow Local - Project Context & State Tracker

This file serves as the definitive central registry, project directory, and history tracker for **VoiceFlow Local**. Any agent or system iterating on this codebase must scan this file first to understand current progress, state, and goals.

---

## 📅 Project History & Iteration Logs

### Iteration 1 — 2026-05-30
*   **Goal**: Create a fully functioning local, offline, voice typing desktop application matching WhisperFlow features.
*   **Accomplishments**: 
    *   Designed a multi-threaded Python architecture with separate threads for audio streaming, VAD analysis, transcription, and typing.
    *   Wrote the core implementation files (`main.py`, `audio_handler.py`, `transcription.py`, `typer.py`, `ui.py`, `utils.py`).
    *   Created `requirements.txt` listing necessary offline dependencies (`faster-whisper`, `webrtcvad`, `sounddevice`, `numpy`, `pyperclip`, `pyautogui`, `keyboard`).
    *   Developed a double-clickable Windows setup script (`setup.bat`).
    *   Verified all core files passed syntax and structure audits successfully.

### Iteration 5 — 2026-06-06 ✅ BUG FIXES
*   **Goal**: Fix all runtime bugs and ensure the project runs correctly.
*   **Accomplishments**:
    *   **Fixed `MicButton._pulse_tick` color bug**: The active (recording) pulse animation was incorrectly using `C["teal"]` ring fill/outline. Fixed to always use `C["red"]` so the pulsing button stays visually consistent with its active (red stop) state.
    *   **Fixed `_minimize` / `<Map>` guard**: Added `_iconified` flag to `NirmiqEchoUI` so `overrideredirect(True)` is only re-applied after an actual `iconify()` call, preventing the custom titlebar from being unexpectedly re-applied on any other `<Map>` event.
    *   **Fixed `shutdown()` null guard**: Added `and self.audio_handler` guard in `NirmiqEchoApp.shutdown()` to prevent `AttributeError` if `_listening=True` but `audio_handler=None`.
    *   **Added `run.bat`**: Easy double-click launcher for the app without needing a terminal.
    *   All 6 Python files re-validated with `py_compile` — zero syntax errors.
*   **Folder rename**: User opted to skip the folder rename (VSCode has it locked). Folder is still `Voice-text/` on disk but internally branded as NirmiqEcho.
*   **Next**: User to rename folder to `NirmiqEcho` when VSCode is closed.

### Iteration 4 — 2026-05-30 ✅ PHASE 2 COMPLETE
*   **Goal**: Implement full production UI per `UI_UXprompt.md` (Nirmiq Echo Design Summary).
*   **Design Source**: `UI_UXprompt.md` — 263 lines of detailed design spec.
*   **Accomplishments**:
    *   Installed `pystray` + `Pillow` for system tray support.
    *   Rewrote `ui.py` (812 insertions) with complete Phase 2 UI:
        *   **Custom titlebar**: `#31354B` draggable bar, settings ⚙ gear, 📌 pin toggle, minimize `─`, close `✕`.
        *   **MicButton**: 48px circular canvas button — teal ring + mic glyph (idle) → red fill + stop square (active) + pulse animation when speaking.
        *   **VU Meter**: 7 vertical bars with smooth per-bar decay, teal→orange colour shift above 75%.
        *   **Toolbar**: Icon buttons (Copy ⎘, Save 💾, Clear 🗑) with hover highlight and tooltips (500ms).
        *   **Status row**: Segoe UI Italic 10pt, WCAG-spec colours per state, model info right-aligned.
        *   **Transcript area**: `#1F1F1F` bg, `#ECEFF8` text, Segoe UI 11pt, styled scrollbar `#3F4140` track / `#6F7591` thumb.
        *   **SettingsModal**: VAD sensitivity slider, language entry, hotkey display, auto-run checkbox.
        *   **System tray**: Minimize-to-tray via `pystray`, restore on click, exit from tray menu. Graceful fallback if unavailable.
        *   **Keyboard shortcuts**: F9, Ctrl+C, Ctrl+S, Ctrl+L, Esc, Ctrl+Q all wired.
        *   **Resize grip**: Bottom-right corner drag resize with minimum dimensions 320×200.
        *   **Confirm on Clear**: `messagebox.askyesno` guard.
        *   **Window**: Starts centered on screen, `overrideredirect(True)` (custom titlebar), resizable.
    *   Patched `main.py`: Added `_autorun` flag wired to SettingsModal, exposed `audio_handler.sensitivity`.
    *   Updated `requirements.txt` with `pystray>=0.19.0` and `Pillow>=9.0.0`.
    *   All 6 Python files passed `py_compile` — zero syntax errors.
    *   **Git commit** `b467eca` — 3 files changed, pushed to `origin/master`.
*   **Next**: Phase 3 — to be defined (performance tuning, model download progress, etc.).

### Iteration 3 — 2026-05-30 ✅ PHASE 1 COMPLETE
*   **Goal**: Fix all files for Python 3.12 compatibility, rename project to **NirmiqEcho**, and push to GitHub.
*   **Accomplishments**:
    *   Installed all missing dependencies (`webrtcvad-wheels`, `faster-whisper 1.2.1`, `pyautogui`, `keyboard`, `pyperclip`).
    *   Rewrote all 6 Python files with Python 3.12 compatible type hints, NirmiqEcho branding, and clean architecture.
    *   Rewrote `ui.py` as a clean minimalist dark overlay (user requested simple UI; detailed UI to come later).
    *   Updated `requirements.txt` to use `webrtcvad-wheels` for Windows Python 3.12 compatibility.
    *   Updated `setup.bat` and `README.md` with NirmiqEcho branding.
    *   Created `.gitignore` (excludes `__pycache__`, `.venv`, `.cache`, model files).
    *   Ran syntax validation — all 6 Python files passed (`py_compile` — no errors).
    *   Initialized git repo in `voiceflow_local/`, connected remote to `https://github.com/SheeshDarth/NirmiqEcho.git`.
    *   Committed exactly 10 files (source + config + docs only — no caches, no models).
    *   **Successfully pushed to `origin/master`** — branch live at [github.com/SheeshDarth/NirmiqEcho](https://github.com/SheeshDarth/NirmiqEcho).
*   **Next**: Phase 2 — detailed custom UI design (user to provide specs).

### Iteration 2 — 2026-05-30
*   **Goal**: Design and deploy a complete production-grade documentation suite.
*   **Actions**:
    *   Create [context.md](file:///C:/Users/Siddharth/Desktop/Voice-text/context.md) (this file) to register current state.
    *   Generate [PRD.md](file:///C:/Users/Siddharth/Desktop/Voice-text/PRD.md) to detail product specifications and requirements.
    *   Generate [TRD.md](file:///C:/Users/Siddharth/Desktop/Voice-text/TRD.md) to capture low-level technical parameters and dependencies.
    *   Generate [UI_UX.md](file:///C:/Users/Siddharth/Desktop/Voice-text/UI_UX.md) to define visual colors, custom Canvas controls, and UX states.
    *   Generate [BACKEND_ARCHITECTURE.md](file:///C:/Users/Siddharth/Desktop/Voice-text/BACKEND_ARCHITECTURE.md) to clarify thread boundaries, queues, and locks with visual diagrams.
    *   Generate [CODEX_IMPLEMENTATION.md](file:///C:/Users/Siddharth/Desktop/Voice-text/CODEX_IMPLEMENTATION.md) to provide an annotated single-source repository for easy copy-paste.
    *   Generate [DEBUGGING.md](file:///C:/Users/Siddharth/Desktop/Voice-text/DEBUGGING.md) to address common Windows setup obstacles (sound drivers, admin privileges, CUDA DLLs).

---

## 📂 System Directory Structure

```text
voiceflow_local/
│
├── main.py                # Application controller and coordinator
├── audio_handler.py       # sounddevice stream capture + webrtcvad state machine
├── transcription.py       # faster-whisper GPU/CPU offline engine
├── typer.py               # pyautogui and pyperclip keystroke injector
├── ui.py                  # Tkinter floating dark-mode UI with custom widgets
├── utils.py               # global keyboard hotkey manager and system logs
├── requirements.txt       # package dependencies
├── setup.bat              # automated Windows setup shell script
├── README.md              # quickstart instructions for users
└── assets/                # directory for visual resources and logs
```

---

## ⚙️ Technologies & Libraries

*   **Core**: Python 3.11+
*   **Audio Capture**: `sounddevice` (cross-platform sound wrapper over PortAudio)
*   **Voice Activity Detection**: `webrtcvad` (C-based WebRTC VAD wrapped for Python, processes 16kHz mono audio in 10/20/30ms frames)
*   **Acoustic Processing**: `numpy` (array processing) & `scipy` (mathematical audio filters, optional fallback)
*   **AI Transcription**: `faster-whisper` (CTranslate2 integration of OpenAI's Whisper model, 4x faster with lower memory footprint)
*   **Simulated Input**: `pyautogui` (keystroke writing) & `pyperclip` (clipboard-based paste injection)
*   **Global Hotkey Hook**: `keyboard` (low-level OS Hook for monitoring keystrokes globally)
*   **Graphical Interface**: `tkinter` (native lightweight standard UI)

---

## 🔒 Offline Constraints & Safeguards
*   No internet access required post-installation and post-model-download (~769 MB download for `medium` model).
*   No API keys are requested, stored, or processed.
*   Zero cloud calls or telemetry. Audio and transcribed text never leave the local machine.

---

## 🎯 Current Operational Performance Targets
*   **Audio Sampling**: 16,000 Hz, 1 channel, 16-bit PCM.
*   **Frame processing**: 30ms window (480 samples).
*   **Silence threshold**: 600ms (20 consecutive silent frames) before transcription trigger.
*   **Speech start threshold**: 90ms (3 consecutive voiced frames) before speaking status indicator.
*   **Whisper latency**: < 1.0s on standard CPU, < 0.2s on CUDA-capable GPU.
