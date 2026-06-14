# NirmiqEcho — Deployment

## A. Run it today (this machine)

```
cd C:\Users\Siddharth\Desktop\NirmiqEcho
start.bat
```

First run installs dependencies (a few minutes) and creates `.env`. A mic icon
appears in the system tray; it auto-starts listening. Press **F9** to toggle, or
just talk. The Whisper model is reused from `models/` (no download).

**Optional "understand anything" (already configured):** keep Ollama running so
novel phrasing is handled. If Ollama is off, Echo still works with all built-in
commands — it just skips the LLM rewrite.

```
ollama serve            # or the Ollama desktop app
ollama pull qwen3.5:4b  # one time (you already have it)
```

**Launch at login (optional):** run `install_autostart.bat` once.

## B. Verify it's healthy

```
cd voiceflow_local
python mic_check.py              # mic devices, mute state, live capture
python test_capabilities.py     # 26/26 command routing
python test_conversational.py   # 12/12 natural phrasing
python test_safety.py           # injection guards
```

## C. Push to GitHub (when ready)

The repo is now a single flat repo (no submodules) and privacy-safe — your
voice recordings (`*.m4a`) and `accent_profile.json` are gitignored and will
NOT upload. Models and `.env` are gitignored too.

```
cd C:\Users\Siddharth\Desktop\NirmiqEcho
gh repo create NirmiqEcho --private --source=. --remote=origin
git push -u origin master
```

Use `--private` unless you intend it public. Double-check before pushing:

```
git ls-files | findstr /I ".m4a .env accent_profile.json models"   # must be empty
```

## D. Ship to another Windows machine

1. Copy the folder (or `git clone` once pushed). `models/` is gitignored, so on
   a clone the Whisper model auto-downloads on first launch (~1.5 GB for
   small.en on CPU; large-v3 only if a CUDA GPU is present).
2. Install Python 3.11+ and run `start.bat`.
3. (Optional) install Ollama + `ollama pull qwen3.5:4b` for the LLM fallback.

## What's intentionally NOT included (kept lean / shippable)

- FastAPI server, WebSocket, browser dashboard, Electron — the LLM-OS prototype
  was cut; the tray app is the product. (History remains in git.)
- The standalone `nirmiq-echo` folder on the Desktop is now redundant — its
  useful part (the LLM fallback) lives in `voiceflow_local/llm_fallback.py`.
  Safe to delete once you're happy.

## Known limitations (honest)

- Multi-intent in one breath ("open Brave AND play a song") executes only the
  first recognised intent. Single-intent natural phrasing works well.
- Spotify "play X" cues the track reliably but can't always auto-press play
  (no public desktop shortcut); local music files play instantly.
- The LLM fallback needs Ollama running; without it, only built-in phrasings.
