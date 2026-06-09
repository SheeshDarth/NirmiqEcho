# Technical Requirements Document (TRD) - VoiceFlow Local

This document specifies the technical requirements, library designs, core algorithms, and audio parameters for **VoiceFlow Local**.

---

## 1. Technical Stack & Core Dependencies

The application relies strictly on standard python libraries and a select group of low-level compiled C-bindings to run entirely offline:

```text
Dependency         | Version | Primary Function
-------------------|---------|---------------------------------------------
sounddevice        | >=0.4.6 | Standard PortAudio bindings for microphone input
numpy              | >=1.20  | High-speed array structures for raw audio
webrtcvad          | >=2.0.10| C-based Google WebRTC VAD wrapper
faster-whisper     | >=0.10  | CTranslate2-wrapped Whisper model (low memory)
pyperclip          | >=1.8.2 | Clipboard injection utility
pyautogui          | >=0.9   | OS keypress injection fallback
keyboard           | >=0.13  | Native Windows global keyboard hook manager
tkinter            | Native  | Standard python GUI engine
```

---

## 2. Low-Level Audio Architecture

To align with the requirements of the WebRTC Voice Activity Detector, the system implements a strict audio pipeline:

```text
Parameter           | Value              | Rationale
--------------------|--------------------|------------------------------------------
Sample Rate         | 16,000 Hz          | WebRTC VAD standard (16kHz preferred)
Channels            | 1 (Mono)           | Whisper only processes mono files
Data Type / Format  | 16-bit Signed PCM  | Required for binary VAD evaluation
Frame Duration      | 30 ms              | Balance between latency and speech capture
Samples per Frame   | 480 samples        | Calculated: (16000 * 30) / 1000
```

### 2.1 Audio Capture Thread
*   Captured via `sounddevice.RawInputStream` to bypass the high overhead of NumPy wrapper classes during stream delivery.
*   The raw buffer is fed instantly to the C-based VAD frame analyzer on a low-priority thread managed directly by PortAudio.

---

## 3. Voice Activity Detection (VAD) State Machine

The VAD module acts as a state machine that separates active speech segments from silent gaps without recording fixed-length chunks.

```
                  +--------------------------+
                  |           IDLE           | <--------------------+
                  +--------------------------+                      |
                       | (Start Recording)                          |
                       v                                            |
                  +--------------------------+                      |
                  |        LISTENING         |                      |
                  +--------------------------+                      |
                       |                                            |
                       | [3 voiced frames (90ms)]                   |
                       v                                            |
                  +--------------------------+                      |
                  |     SPEAKING (ACTIVE)    |                      |
                  +--------------------------+                      |
                       |                                            |
                       | [20 silent frames (600ms)]                 |
                       v                                            |
                  +--------------------------+                      |
                  |       TRANSCRIBING       | ---------------------+
                  +--------------------------+ (Sends Segment & Clears State)
```

### 3.1 Frame Status Counters
*   **SPEECH_THRESHOLD_FRAMES = 3** (90ms of continuous voiced frames): Required to trigger the transition from `Listening` to `Speaking`. Prevents random audio glitches, coughs, or room clicks from triggering transcription.
*   **SILENCE_THRESHOLD_FRAMES = 20** (600ms of consecutive silent frames): Silence time before finishing the segment, flushing the buffer, and dispatching the segment to the transcription queue.
*   **MIN_SPEECH_FRAMES = 5** (150ms of audio): Minimum segment size. Discards audio segments shorter than this threshold (e.g., brief keyboard clicks or desk bumps).
*   **MAX_UTTERANCE_SECONDS = 30**: Force-flush limit. Enforces a hard split if speech continues endlessly to prevent memory exhaustion.

---

## 4. Transcription Engine Specs

### 4.1 CUDA & Quantization Logic
The engine checks hardware capabilities dynamically via torch or CTranslate2 bindings:

```python
# System hardware detection map:
# If GPU with CUDA is found:
device = "cuda"
compute_type = "float16"
default_model = "large-v3"   # ~3.1 GB model (loaded inside CTranslate2 structures)

# If CPU-only:
device = "cpu"
compute_type = "int8"
default_model = "medium"     # ~769 MB model (optimized with int8 quantization)
```

### 4.2 Transcription Parameters
For maximum typing accuracy and low latency, parameters are passed to `WhisperModel.transcribe`:
*   `beam_size=5`: Standard balance between speed and precision.
*   `temperature=0.0`: Greedy search. Eliminates random word choices; returns consistent outputs.
*   `vad_filter=True`: Second-pass local VAD using Whisper's built-in Silero VAD to filter trailing noise.
*   `no_speech_threshold=0.6`: Discard segment if the probability of no-speech exceeds 60%.

---

## 5. Keystroke Injection & Thread Safety

### 5.1 Dual-Mode Typist
To paste text without freezing active application frames:
1.  **Clipboard Mode (Primary)**:
    *   Saves the user's current clipboard string.
    *   Copies the transcribed text into the clipboard.
    *   Simulates the `Ctrl+V` keypress.
    *   Pauses briefly (~50ms) to allow the OS to complete the paste.
    *   Restores the user's original clipboard string.
    *   *Result*: Instantaneous delivery of paragraphs, 100% Unicode accuracy.
2.  **PyAutoGUI Mode (Fallback)**:
    *   Simulates keypresses character-by-character using `pyautogui.write()`.
    *   Used only if `pyperclip` fails.
    *   *Result*: Safe for ASCII text, but slower for large chunks.

### 5.2 Thread Coordination Queue
*   **Audio Thread** captures audio and places raw chunks in an internal buffer.
*   **Transcription Thread** pulls completed PCM blocks from `speech_queue`, transcribes them asynchronously, and pushes the result to the main thread and typing thread.
*   **Typing Thread** pulls texts from a private queue and types them, shielding audio capture from system typing lags.
