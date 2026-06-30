# UI/UX Specification Document - VoiceFlow Local

This document specifies the design system, custom canvas widgets, interactive states, and floating window controls that govern the **VoiceFlow Local** user interface.

---

## 1. Minimal Modern Theme & Design Tokens

To achieve a premium, high-contrast, modern dark aesthetic, VoiceFlow Local implements a tailored, harmonious HSL-matched dark palette.

### 1.1 Color Palette

```text
Token Name    | Hex Value | Visual Role
--------------|-----------|-----------------------------------------------------
bg            | #0f0f11   | Deep-dark background of the main frame
surface       | #1a1a1f   | Secondary container background (status bar, text area)
surface2      | #242429   | Highlight container background (button track, sliders)
border        | #2e2e36   | Clean dividers, element borders, slider tracks
accent        | #7c6af7   | Royal purple brand color; Primary trigger buttons
accent_dim    | #4f46a0   | Deep purple for pressed states and selection overlays
accent_hover  | #9d8fff   | Vibrant violet for hover interactions
green         | #22c55e   | Active states, successful voice activity
red           | #ef4444   | Error flags, stop recording triggers
orange        | #f97316   | Model loading indicators, transcribing activities
text          | #e8e8f0   | Primary high-contrast text
text_muted    | #8888a0   | Secondary guidance text, word count labels
text_dim      | #555568   | Disabled labels, inactive indicators
```

### 1.2 Typography System

The application uses standard Windows fonts to guarantee instant loading without downloading external assets:
*   **Title Font**: `Segoe UI`, 13px, Bold
*   **Body Font**: `Segoe UI`, 10px, Normal
*   **Small Label Font**: `Segoe UI`, 9px, Normal
*   **Mono Console Font**: `Consolas`, 10px, Normal (used inside the live transcript box)
*   **Status Font**: `Segoe UI`, 9px, Bold
*   **Hotkey Font**: `Segoe UI`, 8px, Normal

---

## 2. Floating Overlay & Window Behaviors

### 2.1 Always-On-Top Toggle
*   A pin checkbutton (`📌`) in the top-right header controls whether the window floats persistently above all other application windows (`attributes("-topmost", True)`).
*   Allows the user to see live transcription progress while typing directly into a word processor or coding window behind the overlay.

### 2.2 Immersive Dark Title Bar Hack
To bypass the standard Windows light grey title bar that breaks dark theme immersion, VoiceFlow Local accesses the native Windows Desktop Window Manager (DWM) API via `ctypes`:

```python
import ctypes
hwnd = root.winfo_id()
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
ctypes.windll.dwmapi.DwmSetWindowAttribute(
    hwnd, 
    DWMWA_USE_IMMERSIVE_DARK_MODE,
    ctypes.byref(ctypes.c_int(1)), 
    ctypes.sizeof(ctypes.c_int)
)
```
*Result*: Darkens the standard system window frame to integrate with the `#0f0f11` background on Windows 10/11.

---

## 3. Custom Canvas-Based Widgets

Standard Tkinter buttons and progress bars do not support modern elements like rounded corners, smooth gradients, or custom active indicators without installing complex external packages. VoiceFlow Local builds these structures using highly optimized `tk.Canvas` elements.

### 3.1 StyledButton
*   **Rounded Corners**: Accomplished using a customized canvas smooth polygon drawing routine (`_round_rect`).
*   **Hover states**: Mouse `<Enter>` and `<Leave>` bindings automatically repaint the canvas with `#9d8fff` (hover) or `#7c6af7` (default) immediately.
*   **Click responses**: `<ButtonPress-1>` transitions to `#4f46a0` (active click), and `<ButtonRelease-1>` triggers the designated function callback.
*   **Zero Dependencies**: Written purely in standard python canvas, with no Pillow, PIL, or external graphic files.

### 3.2 LevelMeter (Microphone VU Visualizer)
*   Draws a sleek horizontal level track.
*   Converts the real-time RMS (Root Mean Square) volume level of the microphone input stream into a sliding fill percentage.
*   Uses HSL logic to shift color: green (`#22c55e`) for standard speaking levels, shifting to orange (`#f97316`) if audio clipping or high background noise is detected.

---

## 4. Application Status Indicators

The floating window communicates its current thread status using colored visual bulbs:

```text
Status Code      | Label Indicator          | Bulb Color         | Thread State
-----------------|--------------------------|--------------------|--------------------------------------------
idle             | ⬤  Idle                  | Gray (#555568)     | App ready, microphone closed
loading          | ⬤  Loading model…        | Orange (#f97316)   | Whisper loading in background thread
ready            | ⬤  Ready                 | Green (#22c55e)    | Model loaded, idle
listening        | ⬤  Listening             | Purple (#7c6af7)   | Mic open, VAD analyzing silences
listening_active | ◉  Speaking…             | Green (#22c55e)    | Active voice detected; recording
transcribing     | ⬤  Transcribing…         | Orange (#f97316)   | Model executing offline transcription
error            | ⬤  Error                 | Red (#ef4444)      | Audio driver or model loading failure
```

---

## 5. UI Layout Blueprint

```text
+--------------------------------------------------+
| 🎙 VoiceFlow Local                          📌   | <-- Header (Icon, Title, Model Info, Float Pin)
| Model Info: large-v3 | cuda | float16            |
+--------------------------------------------------+
| ⬤  Listening                         F9 to toggle| <-- Status Bar (Current State, Hotkey Reminder)
+--------------------------------------------------+
| MIC  [=======================>                 ] | <-- LevelMeter (VU Audio Volume Bar)
+--------------------------------------------------+
| TRANSCRIPT                                       | <-- Text Box (Consolas, scrollable, readonly)
| |----------------------------------------------| |
| | Hello world this is real time local voice    | |
| | typing built on Whisper.                     | |
| |----------------------------------------------| |
+--------------------------------------------------+
| +-------------------------+ +------------------+ |
| |        ▶ Start          | |      ■ Stop      | | <-- Primary Controls (Double-sized rounded btns)
| +-------------------------+ +------------------+ |
| +------------+  +------------+  +--------------+ |
| |  ⎘ Copy   |  |  💾 Save   |  |   🗑 Clear   | | <-- Utility Buttons
| +------------+  +------------+  +--------------+ |
|                                                  |
| VAD Sensitivity: 0 -------(2)------- 3           | <-- Sensitivity Slider
+--------------------------------------------------+
| 15 words                     100% offline · CPU  | <-- Footer (Word Counter, Offline Validation)
+--------------------------------------------------+
```
