# Changelog

All notable changes to NirmiqEcho are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com); this project uses semantic versioning.

## [0.1.0] - 2026-07-08

First public release — a **100% offline, JARVIS-style voice command assistant for Windows**
that runs in the system tray. Your voice never leaves the machine.

### Added
- **Offline voice pipeline:** mic → hybrid VAD (webrtcvad + adaptive energy gate, mic
  auto-rescue) → faster-whisper STT (GPU/CPU auto-select with a degradation ladder) →
  command engine → offline TTS + tray UI.
- **~94 built-in voice commands:** apps (open/close/focus), media (Spotify/YouTube/local,
  volume, media keys), WhatsApp send-flow, files (find/open/move/trash), window &
  navigation control, system info (time/date/battery/CPU/status), timers, screenshots,
  spoken Q&A, jokes, remember/recall.
- **Optional local-LLM "understand anything" fallback** (Ollama) — rewrites novel phrasing
  into known commands; carries one turn of context; never executes raw model output.
- **User-defined commands** via `commands.yaml` (sandboxed to non-destructive actions).
- **"Hello Echo" wake word** (Whisper tiny) and **F9** push-to-talk.
- **int8 model quantization** control (`WHISPER_COMPUTE`) for a lighter footprint
  (small.en int8 ≈ 0.5 GB vs large-v3 ≈ 2.9 GB).

### Security
- No `shell=True` / `os.system` / `eval` / `exec` anywhere; whitelist-validated app/process
  names; URI-scheme blocklist (`javascript:`/`file:`/… rejected before launch).
- Destructive actions (shutdown/restart/sleep/empty-bin/delete) require **spoken
  confirmation**; file delete goes to the Recycle Bin.
- Offline-first with a loud privacy warning if Ollama is pointed off-machine; local
  gitignored audit log.

### Hardened (architecture review remediation)
- `RLock` on listening-state transitions (start/stop race).
- Safe numeric coercion for voice-derived `set_volume`/`set_timer`/`scroll`.
- URI-scheme allow/blocklist in app launching; feedback-timer debounce; logged the
  previously-silent error paths.

### Quality & tooling
- 15 pytest tests (green), `ruff` lint, and a shell/eval CI guard on every push.
- Pinned dependencies; **verified clean-clone install**.

### Docs
- `README`, `SECURITY`, `DEPLOY`, `CODEBASE_MAP`, and a complete `HANDBOOK`.
