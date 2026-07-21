# NirmiqEcho — pre-release smoke checklist

The manual gate that CI cannot cover: headless Windows runners have no
microphone, no audio device, and no interactive desktop, so the voice pipeline,
keystroke injection, and window automation can only be verified by a human on a
real machine. Run this before tagging a release. Target: **the frozen exe**, not
the source (the frozen build swaps the runtime — path/model-cache/hotkey
behavior only shows up there).

## 0. Build & launch
- [ ] Built from a clean venv (`packaging/README.md`), size sane (< ~1 GB onedir).
- [ ] `dist/NirmiqEcho/NirmiqEcho.exe` launches; tray icon appears; no crash.
- [ ] `%LOCALAPPDATA%\NirmiqEcho\logs\nirmiqecho.log` is being written.

## 1. Modes & hotkeys
- [ ] **F9** starts/stops listening (or tray-click if no admin).
- [ ] **F10** flips Command ⟷ Dictation (announced by voice + status line).

## 2. Command mode (Jarvis) — top 10
- [ ] "open notepad"  → app opens
- [ ] "what time is it" / "what's the date"  → spoken answer
- [ ] "what is 47 times 19"  → "= 893"
- [ ] "convert 10 km to miles"  → spoken answer
- [ ] "volume up" / "mute"  → system volume changes
- [ ] "take a screenshot"  → screenshot saved
- [ ] "set a timer for 1 minute"  → timer armed
- [ ] "cpu usage" / "system status"  → spoken status
- [ ] "who is Einstein" (needs internet or Ollama)  → spoken answer
- [ ] **Destructive gate:** "shut down the computer" → asks to confirm; say
      nothing → it does NOT shut down (15s timeout).

## 3. Dictation mode (Wispr Flow) — into 3 real apps
- [ ] Notepad: a rambly sentence types as clean, punctuated text.
- [ ] Browser address/search box: dictation lands in the field, not as a command.
- [ ] A chat app: "open the document and send it" is **typed**, never executed
      (the mode-split safety boundary).
- [ ] With Ollama OFF: dictation still types clean rules-cleaned text (no hang).

## 4. Resilience
- [ ] Unplug/mute the mic mid-session → app recovers or reports mic status, no crash.
- [ ] Force an error (e.g. bad model path) → crash is captured in the log file.
- [ ] Close from the tray → process exits cleanly (no orphaned python.exe).

## 5. First run (clean box)
- [ ] SmartScreen: "More info → Run anyway" launches it (documented in README).
- [ ] First launch seeds config and loads the bundled model **offline**.

Sign-off: build ______  ·  date ______  ·  result PASS / FAIL
