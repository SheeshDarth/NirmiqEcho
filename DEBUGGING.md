# Debugging & Troubleshooting Guide - VoiceFlow Local

This document provides definitive solutions for common obstacles encountered when setting up, compiling, or executing **VoiceFlow Local** on Windows environments.

---

## 1. Windows Audio Drivers & `sounddevice` / PortAudio Errors

`sounddevice` acts as a Python binding over the compiled PortAudio C library. Windows audio configuration can sometimes block PortAudio initialization.

### 1.1 "PortAudioError: Error querying device" or "No input devices found"
*   **Root Cause**: Windows microphone access is disabled at the OS privacy level, or the recording device is disabled in the Windows Control Panel.
*   **Resolutions**:
    1.  Open **Windows Settings** (Press `Win+I`).
    2.  Navigate to **Privacy & Security ➔ Microphone**.
    3.  Ensure **Microphone access** and **Let desktop apps access your microphone** are both toggled **ON**.
    4.  Right-click the speaker icon in the taskbar, select **Sound Settings ➔ More sound settings** (Control Panel style).
    5.  Go to the **Recording** tab, right-click and ensure your active microphone is enabled and set as the **Default Device**.

### 1.2 `webrtcvad.Vad` raises `ValueError: Error while processing frame`
*   **Root Cause**: Google WebRTC VAD has mathematically strict constraints. It *only* accepts audio frames that are exactly:
    *   **Sample Rates**: 8000Hz, 16000Hz, 32000Hz, or 48000Hz.
    *   **Frame Durations**: 10ms, 20ms, or 30ms.
*   **Resolution**:
    *   The application forces these settings in `audio_handler.py` (`VAD_SAMPLE_RATE = 16000`, `FRAME_DURATION_MS = 30`).
    *   If your physical microphone hardware is locked to a non-standard studio rate (e.g., 192,000Hz multi-channel) and does not support automatic downsampling, open Windows Sound Settings ➔ Microphone Properties ➔ **Advanced** tab, and set the Default Format to `2 channel, 16-bit, 48000 Hz (DVD Quality)` or `1 channel, 16-bit, 16000 Hz`.

---

## 2. CUDA cuDNN & GPU Allocation Failure

`faster-whisper` relies on the CTranslate2 backend, which performs extremely fast matrix math on GPUs but is very strict about Nvidia driver DLLs.

### 2.1 "Could not load library cublas64_11.dll" or "cudnn64_8.dll"
*   **Root Cause**: CTranslate2 requires the CUDA runtime DLLs and cuDNN libraries to be available in the system PATH or the python environment. Installing PyTorch does *not* automatically install these libraries.
*   **Resolution**:
    *   **The Easiest Fix (Virtual Environment Drop)**:
        1.  Locate your system CUDA version (default CUDA 12 or 11).
        2.  You can easily download cuDNN and CUDA libraries by running these pip commands inside your activated `.venv`:
            ```bat
            pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
            ```
        3.  Copy the missing `.dll` files from your Python site-packages directory:
            *   From: `.venv\Lib\site-packages\nvidia\cublas\lib\` and `.venv\Lib\site-packages\nvidia\cudnn\lib\`
            *   To: `.venv\Scripts\` (or any directory in your system PATH).
    *   **The Safe Fallback (CPU execution)**:
        *   If DLL structures remain complex, VoiceFlow Local automatically catches CUDA loading failures and falls back to `device="cpu"` using `int8` quantization. This fallback is highly optimized and executes Whisper `medium` in under 1 second.

---

## 3. Global Hotkey Hooks & Active Typing Permissions

On Windows, the operating system isolates processes running under different user permission sets to prevent unauthorized automation (User Account Control - UAC).

### 3.1 "Hotkey F9 does not work when IDE or Command Prompt is active"
*   **Root Cause**: If the window currently in focus (e.g. an Administrator Command Prompt, Task Manager, or an IDE running as Admin) holds higher privileges than the python process running VoiceFlow Local, the `keyboard` library is blocked from intercepting the keystroke event.
*   **Resolution**:
    *   Always launch VoiceFlow Local with matching permissions.
    *   To allow F9 overlay toggles on *all* focused apps, open your Command Prompt **as Administrator** before running the launcher:
        ```bat
        :: Right-click Command Prompt -> Run as Administrator
        cd "C:\Users\Siddharth\Desktop\Voice-text\voiceflow_local"
        .venv\Scripts\activate
        python main.py
        ```

### 3.2 "PyAutoGUI does not type anything into target editors"
*   **Root Cause**: PyAutoGUI simulates keystrokes at the OS level. If the target application holds elevated administrative rights, the keystrokes are ignored.
*   **Resolution**: Run VoiceFlow Local as Administrator.
*   *Note on Clipboard*: If you have `use_clipboard=True` configured in `typer.py`, the system relies on `Ctrl+V` commands. Ensure the target window accepts clipboard pasting (e.g., standard Windows consoles might require right-click pasting or `Shift+Insert` rather than `Ctrl+V`).

---

## 4. Voice Activity Detection (VAD) Sensitivity Tuning

VAD sensitivity acts as a gatekeeper. If misconfigured, the application might chop off sentences or record background typing noise.

```text
VAD Aggressiveness Setting (0 - 3)

[ 0 ] --- Least Aggressive: Collects everything. Best for quiet rooms, whispered voices,
          and slow speakers. Might capture background hums.
[ 1 ] --- Balanced Mode: Standard sensitivity.
[ 2 ] --- Default / WhisperFlow Match: Optimal noise filter. Discards typical keyboard clicks,
          acoustical fan whirs, and brief breathing sounds.
[ 3 ] --- Most Aggressive: Heavy filtering. Best for loud offices, cafes, or server rooms.
          Requires clear, loud speaking; might clip quiet sentence endings.
```

### 4.1 "VoiceFlow cuts off the end of my sentences"
*   **Troubleshooting**: Set VAD sensitivity to **1** or **0**. Speak closer to the microphone and avoid long pauses inside sentences.
*   **Code tweak**: In `audio_handler.py`, you can increase `SILENCE_THRESHOLD_FRAMES` from `20` (600ms) to `30` (900ms) to allow for longer pauses before triggering transcription.

### 4.2 "VoiceFlow types garbage characters when I type on my keyboard"
*   **Troubleshooting**: Set VAD sensitivity to **3**. Ensure your microphone is positioned away from your physical keyboard.
*   **Code tweak**: In `audio_handler.py`, increase `SPEECH_THRESHOLD_FRAMES` from `3` to `5` to require longer continuous vocalizations before starting recording.
