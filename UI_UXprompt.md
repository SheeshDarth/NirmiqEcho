# Nirmiq Echo Design Summary  
**Purpose:** A compact, floating, dark-themed Windows app for on-device voice dictation and live transcription. It stays on top, listens on a hotkey, detects silence, and instantly types out speech-to-text via Whisper locally.  

**Goals:** Seamless local-first voice typing with no cloud dependence; real-time feedback; auto-paste text anywhere; user-friendly, accessible UI; instant start/stop (hotkey and button); transcript management (copy/save); minimal latency.  

**Key Principles:** Hands-free speech capture, high contrast for dark mode, clear state indicators (Idle/Listening/Transcribing/Error), and thread-safe performance. All design decisions follow accessibility guidelines (WCAG contrast, UI feedback for speech)【48†L91-L99】【50†L153-L161】.

---

## Project Goals  
- **Local-First:** Use on-device Whisper (no APIs or internet).  
- **Real-Time:** Continuous listen, silence detection, immediate transcription.  
- **User-Friendly:** One-click or hotkey to start/stop, live transcript display, auto-type output.  
- **Lightweight:** Minimal CPU/GPU load, threaded audio processing to avoid UI hangs【52†L618-L622】.  
- **Accessible & Scalable:** Dark theme with high contrast text, resizable layout, keyboard navigation, localization-ready.

---

## Target Users  
- **Writers & Students:** Need to dictate notes or essays quickly.  
- **Developers/Power Users:** People coding with RSI or seeking hands-free input for prompts (voice coding)【22†L91-L99】.  
- **Multitaskers:** Users wanting voice notes while working.  
- **Privacy-Conscious AI Users:** Preferring offline transcription (no data sent to cloud).  

---

## Primary User Flows  
1. **Startup:** User launches Nirmiq Echo; window appears (default Idle).  
2. **Activation:** User presses **F9** or clicks *Start* → app enters *Listening* state【48†L91-L99】.  
3. **Speech Input:** User speaks; VU meter animates to show audio level (provide immediate feedback【48†L91-L99】).  
4. **Silence Detected:** After ~1 second of silence, app stops recording and enters *Transcribing* state (silence cutoff threshold per webrtcvad).  
5. **Transcription:** Whisper processes audio chunk; live transcript text appears in the window and is *immediately auto-typed* into the active app. (User can also *Copy* the text or *Save* to file.)  
6. **Repeat or Stop:** Return to *Idle* state. User may repeat voice capture or click *Stop* to disable listening.  

The flow below outlines the cycle from user action to auto-typing:

```mermaid
flowchart LR
  U([User]) -->|F9 / Click Start| A(Trigger Start)
  A --> B[Listening State<br>(Microphone On, VU meter animates)]
  B --> C[Silence Detected (1s)]
  C --> D[Transcribing<br>(Whisper processes audio)]
  D --> E[Update transcript UI & Auto-type text] 
  E --> U
  E -->|Save/Copy| F[Manage Transcript]
```

**Flow Notes:**  
- Pressing **F9** toggles listening (on/off). Mouse click on Start/Stop does the same.  
- A “Stop” or silence returns to *Idle*. (By design, long silence indicates end of utterance【48†L107-L109】.)  
- If user speaks again (within a short interval), flow repeats.  
- *Copy* or *Save* can be used at any time to capture text.  

---

## Screen States & UI Feedback  
The UI window has these modes:  

- **Idle (Ready):** Microphone off, status “Click ▶ or press F9 to start.” Buttons *Start* enabled. (Use a muted mic icon.)  
- **Listening:** Microphone on, status “Listening…”. Show live VU meter (pulsing bars or waveform). *Start* toggles to *Stop*. (Mic icon glowing.)  
- **Transcribing:** Greyed out *Start*, status “Transcribing…”. Transcript area shows text as it arrives (or final result). Visual loader (spinner or progress bar) optional for long segments.  
- **Error:** If mic unavailable or model fails, show error icon/text (red) and disabled listening. E.g. “Microphone not found” or “Model load failed.” Provide **Retry** action.  

Each state is clearly labeled and color-coded (green for ready, blue for listening, yellow for processing, red for errors) to meet accessibility. For example, a small microphone icon changes color (gray → green) to reflect Idle vs. Listening【48†L91-L99】. The VU meter (see Components below) provides immediate speech feedback.  

**State Transitions:** Keyboard/mouse actions update states. The UI should animate smoothly (see Animations section).  

---

## Floating Window Layout  
- **Dimensions:** Default ~400px wide × 300px high. Minimum width 320px (for readability), minimum height 200px. The window is resizable by user (20px margin grip). On high-DPI, scale uniformly (e.g. 125%/150% multiplies sizes).  
- **Position:** Initially center of screen or last position. Always-on-top flag set (stay above other windows). A “always-on-top” pushpin toggle may be included.  
- **Layout:**  
  - **Titlebar (30px height):** Small app icon + “Nirmiq Echo” title (Segoe UI Bold 12pt). Contains a **Settings (⚙️)** button at far right. Titlebar color slightly lighter (#31354B) than body (#242423).  
  - **Toolbar (below title, 40px height):**  
    - **Start/Stop button:** Large green (for Start) or red (for Stop) circle icon (24px) with label.  
    - **Copy, Save, Clear buttons:** Medium icons (16–20px) labeled *Copy*, *Save*, *Clear* respectively.  
    - Buttons spaced 8px apart, with 12px padding.  
  - **Status line (20px):** Under toolbar, shows current status text (“Listening…”) in Segoe UI 10pt, accessible color (#ECEFF8 on dark).  
  - **VU Meter (20px):** To the right of status or integrated under it: horizontal bars that light up to indicate audio level in real time【48†L95-L99】.  
  - **Transcript Area (remaining space):** Large text box with dark background (#1F1F1F) and light text. This is the main scrolling area where transcribed text appears. It uses a fixed-width font (for alignment) or system UI font (e.g. Segoe UI 11pt).  
    - Padding: 12px inside edges.  
    - Scrollbar style: thin, track #3F4140, thumb #6F7591 (blue accent from [5]), meets 3:1 against background for dimension elements【50†L174-L179】.  
- **Overall Styling:** Dark gray backgrounds (#242423, #31354B) with subtle accents (#6F7591, #0DB9D7) and primarily white text (#ECEFF8) for max contrast (contrast ratio ~13:1【48†L91-L99】). See color palette below.  

```mermaid
flowchart TB
    subgraph Window [Nirmiq Echo Window (dark floating)]
        T[Titlebar: App Icon + "Nirmiq Echo" (Segoe UI Bold 12pt)]
        TB[Toolbar: Start/Stop ●, Copy ✎, Save 💾, Clear 🗑️ (Segoe UI 10pt)]
        ST[Status Text ("Idle"/"Listening…"/"Transcribing…")]
        VM[VU Meter (animated level bars)]
        TA[Transcript Area (scrollable, Segoe UI 11pt)]
    end
    Window --> T
    Window --> TB
    Window --> ST
    Window --> VM
    Window --> TA
```

**Dimensions & Spacing:** 12–16px margins around sections, 8px internal spacing between buttons/icons. Typography sizes as above ensure readability (text ≥10pt). Dark gray backgrounds reduce eye strain【50†L153-L161】. Icons should be vector/SVG for sharpness.

---

## Color Palette & Typography  

| Element             | Color (Hex) | Use / Role                | Contrast vs Background      |
|---------------------|-------------|---------------------------|-----------------------------|
| **Window Background**  | #121212      | App main background      | —                           |
| **Panel Background**   | #242423      | Toolbar, footers         | —                           |
| **Secondary Panel**    | #31354B      | Transcript area header   | —                           |
| **Primary Text**       | #ECEFF8      | Status, transcript text  | 13.5:1 (on #242423)【48†L91-L94】 |
| **Secondary Text**     | #9EA1AC      | Inactive labels, hints  | 5.8:1 (on #242423)          |
| **Accent (Blue)**      | #6F7591      | Buttons hover, highlights| 3.4:1 (on #242423; for non-text elements) |
| **Accent (Teal)**      | #0DB9D7      | Start button, VU bars   | 6.6:1 (on #242423)          |
| **Error (Red)**        | #F44336      | Error messages           | 7.2:1 (on #121212)          |

- **Typography:** Use a modern sans-serif (Segoe UI on Windows, fallbacks: Helvetica, Arial) for text.  
  - *Titlebar:* Segoe UI Bold, 12pt (16px).  
  - *Toolbar Buttons/Labels:* Segoe UI Regular, 10pt.  
  - *Transcript:* Segoe UI 11pt regular.  
  - *Status text:* Segoe UI Italic 10pt.  
- **Contrast:** All text meets WCAG AA (≥4.5:1) or AAA (≥7:1) wherever possible. Teal (#0DB9D7) on dark (#242423) is ~6.6:1 (AA), accent usage is sparing (on buttons and UI indicators, not body text). Avoid pure black (#000) on white or vice versa to soften reading【50†L155-L163】.

---

## Iconography & Assets  
- **Icons:** Use simple, flat SVG icons for: Microphone (idle/listening states), Stop, Copy, Save, Clear (trash), Settings (gear), and VU meter bars. Sizes: 16–24px to maintain clarity.  
- **Custom Icons:** A colored mic icon (white mic on teal circle for listening), a neutral mic (gray) for idle. VU meter bars fill with teal as sound volume increases.  
- **SVG Specifications:** Each icon should be vector (SVG with viewBox) sized for 24×24px view. Provide both filled and outline versions where needed. For example, a filled gear vs. outline gear.  
- **Hover States:** On hover, buttons brighten (e.g. toolbar button background #3F4140) and icon color inverts for emphasis. Focused elements have a subtle glowing outline (rgba(93,195,246,0.4) border) for accessibility.  
- **Example CSS (Qt/QSS):**  
```css
/* Dark window background */
QWidget { background: #121212; color: #ECEFF8; font-family: "Segoe UI", sans-serif; }
/* Toolbar buttons */
QPushButton {
  background: #242423; color: #ECEFF8;
  border: 1px solid #ECEFF8; border-radius: 4px; padding: 4px 12px;
}
QPushButton:hover { background: #31354B; }
QPushButton:pressed { background: #1F1F1F; }
```
This ensures buttons stand out and meet contrast guidelines【50†L174-L179】.

---

## Component List & Behaviors  
- **Start/Stop Button:** Toggles listening. 48px circular button with microphone icon. *Idle:* teal outline with black fill; *Listening:* red square-stop icon. Hover glows. Disabled state if no mic.  
- **Copy Button:** Copies current transcript to clipboard. Grayed out if no text. Shortcut: **Ctrl+C**.  
- **Save Button:** Saves transcript to `.txt`. Opens file dialog. Grayed out if empty. Shortcut: **Ctrl+S**.  
- **Clear Button:** Clears transcript buffer. Confirm if needed. Shortcut: **Ctrl+L**.  
- **VU Meter (Audio Level):** 5–10 vertical bars that animate to audio level (non-clickable). Smooth decay.  
- **Transcript Area:** Multi-line text pane (read-only by user; only app writes). Automatically scrolls as text grows. Users can select text.  
- **Settings (Modal):** Gear icon opens a modal dialog for preferences: • Microphone sensitivity slider (range 0.1–1.0) • Language selection (en, other models) • Hotkey customization (default F9) • Toggle on-start auto-run • About info. Modal uses same dark styling; fields are labeled clearly.  
- **Tooltip/Help:** Hover on icons shows tooltip (e.g., “Start Listening (F9)”).  
- **Behaviors:**  
  - **Hover:** Button backplates lighten; tooltips appear after 0.5s delay.  
  - **Focus (keyboard):** Highlight outline on focused element (for Tab navigation).  
  - **Disabled:** Buttons disabled appear semi-transparent (#565556) with no pointer.  
  - **Feedback:** Clicking buttons produces a quick ripple or fade (100–200ms ease-out). Pressing Start plays a brief “ding” sound (optional) for confirmation.  
  - **Error Messages:** Appear in status line (e.g. red text “Mic not found”), possibly as a transient popover if errors persist.

---

## Keyboard Shortcuts  
| Shortcut       | Action                           | Notes                            |
|----------------|----------------------------------|----------------------------------|
| **F9**         | Start/Stop Listening             | Toggle voice capture             |
| **Ctrl+C**     | Copy Transcript                  | (standard copy)                  |
| **Ctrl+S**     | Save Transcript (to `.txt`)      | Opens save dialog                |
| **Ctrl+L**     | Clear Transcript                | Prompts “Are you sure?”          |
| **Esc**        | Stop Listening (same as F9)     | When in Listening/Transcribing  |
| **Ctrl+Q**     | Quit App                         | Minimize to tray or exit         |

All shortcuts appear in tooltips and Settings. Use standard conventions to avoid conflicts. The Hotkey (F9) can be changed in Settings.

---

## Animations & Timing  
- **State Transitions:** Fade and slide transitions for status changes (~150ms ease-in-out).  
- **Listening Feedback:** Microphone icon pulses (scale 1.0→1.2) on the beat of detected speech (e.g. every 300ms, ease-out).  
- **VU Meter:** Bars animate with ~50ms per update (smooth, ease-in).  
- **Transcript Output:** New lines fade in (opacity 0→100%) over ~200ms for readability.  
- **Buttons:** On hover (100ms ease-in), on press (50ms fade).  
- **Modal Popup:** Settings dialog fades & slides from top (200ms).  
- **General Easing:** Use “ease-out” for ending (0.2s) on interactive feedback, “ease-in-out” for state changes (0.15–0.2s). 

Animations should be subtle to avoid distraction, and they should be optional (can be disabled for performance or accessibility).

---

## Responsive & Windows Integration  
- **Scaling:** UI scales with Windows DPI settings (Font sizes and icon sizes multiply accordingly). Use vector icons so no pixelation.  
- **Always-On-Top:** Window flag `Qt.WindowStaysOnTopHint` (or OS equivalent) ensures it floats above other apps. A toggle pin icon can allow users to toggle this behavior.  
- **System Tray:** On minimize or close (click X), app minimizes to tray icon (with context menu: *Show/Hide*, *Settings*, *Exit*). Clicking the tray icon restores window. This follows the pattern in PyQt: on minimize event, hide window and show a `QSystemTrayIcon`; on tray activation, show window【55†L148-L154】.  
- **Startup:** Optionally start with Windows (via shortcut).  
- **Localization:** All UI text externalized (e.g. using .resx or gettext) for easy translation. Layout allows up to ~30% longer text (e.g. German) without clipping.  
- **Accessibility:** Ensure button labels and icons have accessible names (e.g. `aria-label="Start Listening"`). All controls reachable by keyboard. Use `Alt` underlines if implementing menus in future.

---

## Template/Design Inspirations Comparison  

| Inspiration                    | Source     | Key Features                                 | Borrowed Elements               |
|--------------------------------|------------|----------------------------------------------|---------------------------------|
| **VoiceFlow (desktop app)**    | Reddit / [VoiceFlow](https://voiceflow.example) | Dark theme with neon accent; simple hero screen with voice waveform and “hold to talk” cues【22†L91-L99】. Local dictation focus. | Dark background with bright accent (teal/green); one-click start (hotkey); minimal text UI. |
| **Orbix AI Call Assistant (mobile)** | Dribbble [Orbix UI](https://dribbble.com/shots/26556995) | Clean dark call UI with live transcript pane and call controls【40†L88-L97】. Uses high contrast text on dark. | Live scrolling transcript area; status header; dark gray panels with white text; clear action buttons. |
| **Nova Voice Assistant UI (Web)** | Blink (template) | Futuristic dark web UI with glowing feedback and chat bubbles. Emphasizes “listening” state with visual effects. | Dark palette with neon highlights; animated “speaking” indicators; responsive design hints. |

**Table Note:** These references provided design cues. For instance, **VoiceFlow**’s simple dark splash with waveform inspired our floating window simplicity【22†L91-L99】. **Orbix’s mobile UI** confirmed use of dark gray panels and clear transcript text【40†L88-L97】. We prioritize those elements that fit a compact desktop widget: dark grays, luminous accents, live transcript, and a prominent mic control.

---

## SVG Assets & Code Snippets  

- **SVG Specs:** Provide icons at 24×24px baseline, with scalable vector paths. For stateful icons (microphone), prepare two SVGs: `mic_off.svg` (gray) and `mic_on.svg` (teal). Export accent color (#0DB9D7) elements in SVG.  
- **CSS/QSS Snippets:** As above, sample styles to ensure dark mode. (Also include `:disabled { opacity: 0.5; }` and `:focus { outline: 2px solid #5DC3F6; }`.)  
- **Sample PyQt Style:**  
```python
window.setStyleSheet("""
    QWidget { background-color: #121212; color: #ECEFF8; }
    QPushButton { background-color: #242423; color: #ECEFF8; }
    QPushButton:hover { background-color: #31354B; }
    QPushButton:disabled { background-color: #565556; color: #868686; }
""")
```
- **Example Tkinter Mockup (Python):** The following PyQt snippet creates the floating window and a start button:  
```python
import sys
from PyQt6.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout
from PyQt6.QtCore import Qt

app = QApplication(sys.argv)
window = QWidget()
window.setWindowTitle("Nirmiq Echo")
window.setWindowFlags(window.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
window.setFixedSize(400, 300)
window.setStyleSheet("background-color: #121212; color: #ECEFF8;")
start_btn = QPushButton("Start Listening")
start_btn.setStyleSheet("font: 11pt 'Segoe UI'; padding: 6px;")
layout = QVBoxLayout(window)
layout.addWidget(start_btn)
window.setLayout(layout)
window.show()
sys.exit(app.exec())
```  
This stub shows the window stays on top and uses our color scheme. Actual implementation would wire the start button to the voice handler.

---

## Accessibility & Performance Notes  
- **Contrast & Readability:** Follow WCAG AA standards for text. Dark gray (#121212) instead of pure black prevents “halos” and eye fatigue【50†L155-L164】.  
- **Keyboard Navigation:** All controls labeled and tabbable. Tooltips provide hints. Ensure focus ring visible.  
- **Localization:** UI text externalized. Right-to-left language support by mirroring layout if needed.  
- **Performance:** Audio capture and transcription run in a background thread (e.g. using `QThread`/`QThreadPool`【52†L618-L622】). UI updates via thread-safe signals (Qt signals/slots are thread-safe【52†L618-L622】). This avoids UI freezes during model processing.  
- **Resource Usage:** Keep CPU load low by batching audio and using optimized Whisper (e.g. quantized mode). If GPU present, use float16 for model to speed up【52†L618-L622】.  
- **Error Handling:** Gracefully handle lack of microphone (show error and disable Listen). Catch model load failures with user alert. Provide logging to console for debugging.  

---

**Conclusion:** The above spec provides a detailed, production-ready UI design for **Nirmiq Echo**. It aligns with modern dark-mode trends, Windows UX patterns, and voice UI best practices【48†L91-L99】【50†L153-L161】, while ensuring high accuracy and responsiveness locally.