# Backend Architecture Document - VoiceFlow Local

This document specifies the multi-threaded backend architecture, queue-based communications, thread boundaries, locks, and synchronization routines that power **VoiceFlow Local**.

---

## 1. Multi-Threaded Topology

To prevent standard Tkinter interface freezing, VoiceFlow Local decouples high-compute and real-time operational workflows into four distinct, isolated thread layers:

```mermaid
graph TD
    subgraph UI Thread (Main)
        A[Tkinter Event Loop] <--> B[VoiceFlowUI]
        C[UI Command Queue] -->|Drains & Executes| A
    end

    subgraph Audio Capture Thread (PortAudio Native)
        D[sd.RawInputStream Callback] -->|VAD State Machine| E{Voice Detected?}
        E -->|Yes: Accumulate Chunks| F[PCM Frame Buffer]
        E -->|No / Silence Flush| G[Enqueue Segment]
    end

    subgraph Transcription Thread (CTranslate2 Worker)
        H[WhisperModel Inference] <--Polls-- I[Speech Queue]
        G -->|Push PCM| I
        H -->|Push Text Result| J[Typer Queue]
        H -->|Schedule UI Status| C
    end

    subgraph Keyboard Injection Thread (PyAutoGUI Worker)
        K[Clipboard/Keystroke simulation] <--Polls-- J
        K -->|Paste text to OS focus| L[Active Editor Window]
    end
```

### 1.1 Thread Layer Specifications

#### 1. Main Thread (UI Main Loop)
*   **Target Lifecycle**: Spawns standard Tkinter window, binds events, and holds control of coordinates.
*   **Execution**: Blocks on `root.mainloop()`.
*   **Routines**: Runs a recursive `after()` task every 50ms to drain and execute system operations from `_ui_queue`.
*   *Safety Constraint*: Under no circumstances should backend engines directly alter Tkinter labels or text grids from secondary threads. Doing so triggers native Win32/X11 drawing errors or instant thread deadlocks.

#### 2. Audio Capture Thread (High-Priority PortAudio Thread)
*   **Target Lifecycle**: Managed internally by the compiled PortAudio/sounddevice driver bindings.
*   **Execution**: Non-blocking audio buffer callback.
*   **Routines**:
    *   Computes RMS amplitude for the visualizer.
    *   Invokes compiled C-based `webrtcvad` bindings to evaluate frame activity.
    *   Drives the silence and speech frame counter state machine.
    *   Flushes complete utterance segments as `np.float32` arrays directly to `Speech Queue`.

#### 3. Transcription Thread (CTranslate2 Worker)
*   **Target Lifecycle**: Deployed as a background python `daemon` thread upon Whisper engine initialization.
*   **Execution**: Continuous queue polling block.
*   **Routines**:
    *   Polls `Speech Queue` with a 1.0s timeout.
    *   On block receipt, locks the core CTranslate2 runtime structure using `self._model_lock`.
    *   Executes localized acoustic speech-to-text inference.
    *   Dispatches text outputs to the Typer queue and schedules status resets via `_ui_queue`.

#### 4. Keyboard Injection Thread (PyAutoGUI / Clipboard Worker)
*   **Target Lifecycle**: Deployed as a background python `daemon` thread upon application setup.
*   **Execution**: Async keystroke queues.
*   **Routines**:
    *   Polls `typing_queue` with a 1.0s timeout.
    *   Copies output strings to system Clipboard buffer.
    *   Injects OS-level `Ctrl+V` keyboard paste events.
    *   Pauses briefly (~50ms) to allow OS focus frames to process before restoring the user's original clipboard memory.

---

## 2. Thread-Safe Communication Pipelines

The system avoids thread collisions by passing immutable data across threads using thread-safe, blocking Python queue channels:

### 2.1 Queue Specifications

1.  **`Speech Queue` (AudioHandler ➔ TranscriptionEngine)**:
    *   *Type*: `queue.Queue`
    *   *Payload*: `np.ndarray` (1D float32 array, normalized between -1.0 and 1.0).
    *   *Sentinel*: `None` (triggers shutdown).
2.  **`Typing Queue` (TranscriptionEngine ➔ TextTyper)**:
    *   *Type*: `queue.Queue`
    *   *Payload*: `str` (transcribed text string).
    *   *Sentinel*: `None` (triggers shutdown).
3.  **`UI Command Queue` (Any Backend Thread ➔ VoiceFlowUI)**:
    *   *Type*: `queue.Queue`
    *   *Payload*: `tuple[str, *args]` where the first element is the string key of the handler (e.g. `"set_status"` or `"append_transcript"`).

---

## 3. Synchronization & Thread-Lock Strategy

To prevent race conditions on shared memory (such as model structures, audio stream indicators, or global keyboard lists), three critical locks are maintained:

### 3.1 Core Thread Locks

*   **`self._model_lock` (transcription.py)**:
    *   *Object*: `threading.Lock`
    *   *Rationale*: Faster-whisper/CTranslate2 models are not naturally thread-safe for parallel inference queries. This lock protects the model during `_model.transcribe()` and during manual shutdowns.
*   **`self._lock` (audio_handler.py)**:
    *   *Object*: `threading.Lock`
    *   *Rationale*: Prevents concurrent stream initialization or deletion when user rapidly clicks the Start/Stop UI buttons or triggers F9 toggles in quick succession.
*   **`self._lock` (utils.py)**:
    *   *Object*: `threading.Lock`
    *   *Rationale*: Safely wraps standard `keyboard.add_hotkey` and `keyboard.remove_hotkey` routines to protect OS keyboard callback lists from overlapping registration attempts.
