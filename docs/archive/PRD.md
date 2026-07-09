# Product Requirements Document (PRD) - VoiceFlow Local

This document specifies the product requirements for **VoiceFlow Local**, a secure, local-first voice typing utility designed for high-performance, low-latency offline dictation.

---

## 1. Executive Summary & Goals

### 1.1 Core Vision
VoiceFlow Local is a lightweight, offline-only desktop overlay that continuously monitors microphone input, extracts speech segments using real-time Voice Activity Detection (VAD), transcribes them using local Whisper models, and immediately injects the text into the active user window as if it were typed.

### 1.2 Product Objectives
*   **100% Offline Security**: No remote servers, cloud calls, api keys, or third-party telemetries. Zero data leakage of sensitive voice recordings.
*   **Low Latency**: Provide near-instant text output matching the responsiveness of commercial tools like WhisperFlow.
*   **High Accuracy**: Leverage advanced Whisper architectures locally, optimizing parameter tuning (greedy decoding, built-in CTranslate2 filter) to minimize hallucination.
*   **Frictionless UX**: Simple dark floating status interface that remains on top of other windows, enabling seamless hands-free workflow activation via a global hotkey toggle.

---

## 2. Target Audience & Use Cases

### 2.1 Developer / Programmer
*   **Goal**: Rapid dictation of comments, notes, or long documentation blocks without taking hands off the keyboard or leaving the IDE.
*   **Constraint**: Accuracy of alphanumeric characters, punctuation spacing, and technical terminology.

### 2.2 Content Creator / Writer
*   **Goal**: Flow-of-consciousness writing and transcription of long sentences in Microsoft Word, Google Docs, or text editors.
*   **Constraint**: Needs long-form support, smart pause boundaries, and robust handling of continuous natural speech.

### 2.3 Accessibility / Ergonomics User
*   **Goal**: Complete hands-free keyboard-less input to alleviate repetitive strain injury (RSI) or physical typing limitations.
*   **Constraint**: Heavy reliance on global hotkey toggles and automated focus typing.

---

## 3. Product Functional Requirements (FR)

### 3.1 VAD & Audio Processing (FR-1)
*   **FR-1.1**: The system must continuously capture microphone input without storing large audio segments on the disk.
*   **FR-1.2**: It must execute real-time Voice Activity Detection (VAD) to identify frame-by-frame speech and filter out background noise (clicks, hums, fan whirs).
*   **FR-1.3**: The system must detect natural pauses in speech and automatically flush the accumulated audio segment for transcription immediately upon a designated silence duration (default: ~600ms).
*   **FR-1.4**: To protect memory, single continuous utterances must be auto-flushed if they exceed 30 seconds.

### 3.2 Offline AI Transcription (FR-2)
*   **FR-2.1**: Transcription must be done fully locally using the `faster-whisper` CTranslate2 backend.
*   **FR-2.2**: The application must automatically detect GPU availability via PyTorch/CTranslate2.
    *   If CUDA is found: Default to the `large-v3` model using `float16` precision for peak speed and accuracy.
    *   If CPU only is found: Fall back to the `medium` model using `int8` quantization to ensure fast runtimes on low-resource hardware.
*   **FR-2.3**: Users must have the ability to run transcription without manual model selection or complex configurations.

### 3.3 Active Window Injection (FR-3)
*   **FR-3.1**: Once transcription completes, the resulting text must be automatically typed into the application that currently holds keyboard focus.
*   **FR-3.2**: Keystroke simulation must handle complex Unicode symbols, non-ASCII punctuation, and formatting seamlessly.
*   **FR-3.3**: The typing engine must employ a dual-method system:
    *   Primary: Copy-Paste loop (clipboard injection using Pyperclip) to ensure instantaneous typing of large strings and complete Unicode safety.
    *   Fallback: Direct keystroke injection (PyAutoGUI direct write) if clipboard operations are locked by standard user routines.

### 3.4 Overlay Interface & Controls (FR-4)
*   **FR-4.1**: Provide a compact, premium floating dark window with an "always-on-top" toggle pin to keep it visible while working in other apps.
*   **FR-4.2**: Implement a global system hotkey (`F9`) that toggles the voice monitor on/off from anywhere on the OS, regardless of window focus.
*   **FR-4.3**: Provide primary control buttons: Start Listening, Stop Listening, Copy Transcript Buffer, Save Transcript to TXT file, and Clear.
*   **FR-4.4**: Provide a real-time sensitivity slider to easily adjust the WebRTC VAD threshold (0 to 3) to accommodate noisy environments.
*   **FR-4.5**: Include a live audio level meter (VU bar) showing instant input levels for visual validation of microphone activity.

---

## 4. Non-Functional Requirements (NFR)

### 4.1 Latency
*   Audio segment packaging: Immediate.
*   VAD decision lag: < 30ms.
*   Transcription turn-around: < 1.0s (medium model on 4-core CPU), < 0.3s (large-v3 on GPU).

### 4.2 Stability & Safety
*   Thread Isolation: Audio streaming, model inference, keystroke simulation, and Tkinter UI rendering must execute in isolated threads to prevent GUI freezing.
*   Graceful Failures: In the event of a missing microphone, CUDA crash, or administrative hook error, the system must display clear dialogue boxes instead of crashing standard operations.

### 4.3 Data Privacy
*   Strictly local operation. The application must operate perfectly with internet cables disconnected.

---

## 5. Out of Scope Features
*   Direct API integration with OpenAI, DeepL, or Google Cloud.
*   Real-time language-to-language translation overlay.
*   Voice-command execution (e.g., "delete line", "open browser").
