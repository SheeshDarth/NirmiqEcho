# NirmiqEcho — Complete Project Handbook

> The single source of truth for **what NirmiqEcho is, how it works, how to run/fix/extend it,
> and where it's going.** Written to be self-sufficient: if something breaks or someone asks a
> question, the answer is in here. Pair with `README.md` (user intro), `CODEBASE_MAP.md`
> (static audit), `SECURITY.md` (threat model), `DEPLOY.md` (install).

---

## 1. Identity & metadata

| Field | Value |
|-------|-------|
| **Name** | NirmiqEcho ("Echo") |
| **What** | 100% offline, JARVIS-style **voice command assistant** for Windows, in the system tray |
| **Repo** | github.com/SheeshDarth/NirmiqEcho (public) |
| **Location** | `C:\Users\Siddharth\Desktop\NirmiqEcho` |
| **Language** | Python 3.11+ (tested on 3.12.10) |
| **Platform** | Windows 10/11 **only** (hard Win32 dependencies) |
| **License** | MIT |
| **Version** | 0.1.0 (release-candidate) |
| **Entry point** | `start.bat` → `voiceflow_local/main.py` |
| **Working branch** | `chore/revival-cleanup` (7 commits ahead of `master`) |
| **Not** | a web app, a cloud service, an LLM agent. It is a *command router* (see §14). |

**One-sentence description:** You speak → Whisper transcribes on-device → a regex/keyword engine
(with an optional local-LLM phrasing fallback) maps it to one of ~94 built-in commands → the
command runs real OS actions → Echo speaks back. Voice never leaves the machine.

---

## 2. Architecture — the pipeline

```
Mic (sounddevice)
   |  audio_handler.py : hybrid VAD (webrtcvad + adaptive energy gate),
   |  dead-mic rescue (pycaw auto-unmute + device rescan), pre-speech
   |  noise reference -> noisereduce (on a worker thread, not the audio callback)
   v
 speech_queue --> transcription.py : faster-whisper
   |            device/compute auto-select + degradation ladder
   |            (GPU large-v3 float16 -> GPU int8_float16 -> CPU small.en int8)
   v  text
 main.py : NirmiqEchoApp._on_result(text)
   |  post_processor.py : filler removal, hallucination filter, punctuation
   v
 command_processor.py :: process(text)  -> CommandResult   [see section 4]
   |  resolution order: conversation-state -> math -> units -> 94 regex
   |  -> commands.yaml -> local-LLM fallback (Ollama)
   v
 command_processor.py :: execute(result)
   |  _audit() -> command_log.txt ; update _recent ; dispatch dict -> handler
   |  destructive actions -> _require_confirm() -> conversation_state (spoken yes/no)
   v
 tts_engine.py (pyttsx3/SAPI, queue-serialized)  +  ui.py (tkinter+pystray tray)
```

**If it's NOT a command** → `_on_result` types the text into the focused window via `typer.py`
(dictation mode) and appends it to the transcript.

### Threading model (critical for debugging)
| Thread | Owns | Rule |
|--------|------|------|
| **Main** | tkinter UI loop (`ui.run()`) | All UI mutations happen here |
| **StartupLoader** | model load, accent analysis, Ollama prewarm | Background, one-shot |
| **Audio callback** (sounddevice) | VAD + frame state machine | Must stay cheap — no heavy DSP |
| **AudioPreprocess** | noisereduce + gain normalize | Off the audio thread on purpose |
| **TranscriptionWorker** | consumes `speech_queue`, runs Whisper | |
| **WakeWordDetector** | 2.5s chunks -> tiny Whisper -> phrase check | Pauses while main listening is active |
| **TTSWorker** | serialized speech (pyttsx3 not thread-safe) | All `speak()` calls queue here |
| **conversation_state Timer(s)** | intent timeouts (15s) | daemon |
| **command daemons** | WhatsApp send, timers, confirmations | spawned per-action |

**Cross-thread → UI** always goes through `ui.schedule(event, payload)` → queue → main-thread tick.
`self._listen_lock` (RLock) guards start/stop-listening transitions (added to fix a race).

---

## 3. Module map (`voiceflow_local/`)

| File | Responsibility | Key names |
|------|----------------|-----------|
| `main.py` | Orchestrator; wires subsystems; the `_on_result` pipeline; F9 hotkey; echo-mode; shutdown | `NirmiqEchoApp` |
| `command_processor.py` | **The engine** — patterns, routing, dispatch, all handlers, confirm gate, audit | `CommandProcessor`, `PATTERNS`, `process`, `execute`, `_build_result` |
| `audio_handler.py` | Mic capture, hybrid VAD, mic rescue, denoise | `AudioHandler`, `_resolve_input_device`, `_ensure_mic_unmuted` |
| `transcription.py` | faster-whisper STT, device/compute select, load ladder | `TranscriptionEngine`, `load_model`, `_detect_compute_device` |
| `wake_word.py` | "Hello Echo" detector (Whisper tiny, 2.5s polling) | `WakeWordDetector`, `WAKE_PHRASES` |
| `post_processor.py` | Clean transcript, drop hallucinations | `PostProcessor.clean` |
| `accent_profile.py` | Build accent-tuned `initial_prompt` from voice samples | `AccentProfiler` |
| `conversation_state.py` | Multi-step intent FSM (WhatsApp, confirmations) | `ConversationStateManager`, `State` |
| `llm_fallback.py` | Optional local-Ollama "understand anything" | `map_to_command`, `ask`, `is_available`, `_CANONICAL` |
| `knowledge.py` | Spoken Q&A (Wikipedia -> Ollama) | `answer` |
| `calculator.py` / `units.py` | Offline math / unit+date conversions | `calculate`, `convert`, `date_query` |
| `app_discovery.py` | Windows app discovery (static map + registry + Start Menu + fuzzy) | `AppDiscovery`, `STATIC_MAP`, `PROCESS_ALIASES` |
| `file_assistant.py` | Find/open/move/trash files | |
| `tts_engine.py` | Offline TTS, single worker thread, COM init | `TTSEngine.speak` |
| `typer.py` | Clipboard + keystroke text injection | `TextTyper` |
| `ui.py` | tkinter + pystray tray UI | `NirmiqEchoUI`, `schedule` |
| `utils.py` | Logging, `HotkeyManager`, system info | |
| `mic_check.py` | Standalone mic diagnostic | run `python mic_check.py` |
| `tests/` | pytest layer (wraps the legacy suites) | `test_suites.py`, `test_hardening.py`, `conftest.py` |
| `tests/manual/` | side-effecting scripts (launch apps, benchmarks) — never in CI | |

---

## 4. The command engine — how a command resolves

`CommandProcessor.process(text)` tries, **in order** (first match wins):
1. **Conversation state** — if mid-flow (e.g. awaiting a WhatsApp message or a yes/no), consume it.
2. Strip conversational wrappers ("hey can you … please" -> "…").
3. **Math** (`calculator.calculate`) — only if numbers+operator present.
4. **Units / date** (`units.convert` / `date_query`).
5. **`PATTERNS`** — ~94 regexes, priority-ordered, -> `_build_result(action, arg, …)`.
6. **`commands.yaml`** — user phrases bound to whitelisted safe actions.
7. **LLM fallback** — if enabled + Ollama reachable + <=12 words + default mode: rewrite phrasing
   into one canonical command and **re-run `process()`** on it (never executes raw model text).
8. Else -> `is_command=False` (dictation).

`execute(result)` then: audits it -> updates `_recent` (for follow-up context) -> looks up the action
in the **dispatch dict** (`action -> lambda`) -> runs the handler. Destructive actions call
`_require_confirm()` first.

### How to ADD a new command (no AI needed)
**Code way** (new capability):
1. Add a `(_p(r"…"), "my_action")` tuple to `PATTERNS` in `command_processor.py` (mind priority — put specific patterns before greedy ones like `open_app`).
2. If it captures arguments, add an `elif action == "my_action":` branch in `_build_result` to package `args`.
3. Add the handler method `def _my_handler(self, …)` and wire it in the `dispatch` dict inside `execute()`.
4. If destructive, wrap: `"my_action": lambda: self._require_confirm(self._do_myaction, "Prompt?")`.
5. Add the canonical form to `llm_fallback._CANONICAL` so the LLM can map to it.
6. Verify: `python -m pytest -q` and a manual `process()` check.

**No-code way** (alias an existing action): drop into `commands.yaml`:
```yaml
commands:
  - phrase: "fire up my editor"
    action: open_app
    args: { app_name: code }
```
Only **non-destructive** actions are allowed here (enforced by `_CUSTOM_SAFE_ACTIONS`).

---

## 5. Configuration — every env var (`.env`, copied from `.env.example`)

| Variable | Default | Effect | Read in |
|----------|---------|--------|---------|
| `LLM_FALLBACK` | `1` | `0` disables the local-LLM "understand anything" fallback | `llm_fallback.py` |
| `OLLAMA_MODEL` | `qwen3.5:4b` | Which local model to use | `llm_fallback.py` |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint. **Non-local -> loud privacy warning** | `llm_fallback.py` |
| `WHISPER_MODEL` | *(blank=auto)* | Force `small.en`/`medium.en`/`large-v3` on any device | `transcription.py` |
| `WHISPER_COMPUTE` | *(blank=auto)* | Force `int8`/`int8_float16`/`float16` (footprint/RAM trade-off) | `transcription.py` |
| `INPUT_DEVICE` | *(blank=auto)* | Pin a mic by index or name substring | `audio_handler.py` |
| `NOISE_REDUCE_STRENGTH` | `0.65` | 0=off, 1=max spectral denoise | `audio_handler.py` |
| `AUTORUN` | `1` | Auto-start listening when model ready; `0` = press F9 first | `main.py` |
| `SPOTIFY_AUTOPLAY` | `1` | `0` = only cue the search, never auto-press play | `command_processor.py` |
| `SPOTIFY_PLAY_TABS` | `4` | Tab presses to reach the first result's play button | `command_processor.py` |
| `SPEECH_RMS_THRESHOLD` | `400` | *Documented in `.env.example` but VAD now uses an adaptive noise floor — treat as legacy* | — |

---

## 6. State & data stores (all in `voiceflow_local/assets/`, all gitignored)

| Store | Format | Lifetime | Sensitivity | Notes |
|-------|--------|----------|-------------|-------|
| `.env` (repo root) | key=value | persistent | config | copied from `.env.example` on first run |
| `assets/memory.json` | JSON list of strings | persistent | **HIGH** (may hold codes/passwords) | `remember`/`recall`/`forget everything` |
| `assets/command_log.txt` | `timestamp  action  args` lines | persistent, capped ~512 KB (trims to last 2000 lines) | medium | local audit trail; never sent anywhere |
| `assets/accent_profile.json` | JSON prompt | persistent | low | built from your `Test*.m4a` samples |
| `models/` (repo root) | faster-whisper CTranslate2 cache | persistent, multi-GB | none | small.en ~0.5 GB / large-v3 ~2.9 GB / tiny ~75 MB |
| `commands.yaml` (repo root) | YAML | persistent | low | user custom commands; template = `commands.example.yaml` |
| `Test*.m4a` (repo root) | audio | persistent | **HIGH** (your voice) | accent samples — gitignored |

**In-memory only (lost on restart):** timers, conversation state, wake-word cooldown, `_recent`
(one-turn context).

---

## 7. Security model (summary; full detail in `SECURITY.md`)

- **No shell injection:** no `shell=True`/`os.system`/`eval`/`exec`. All launches use arg lists
  (`subprocess.Popen([exe, …], shell=False)`). App/process names from speech are whitelist-validated
  (`^[\w.+\- ()]+$`); URI schemes are blocklisted (`javascript:`/`file:`/`vbscript:`/`data:`/… rejected).
  PowerShell only ever interpolates **clamped ints** (volume/brightness) or a sanitized process name.
- **LLM never executes** — it only rewrites into the existing validated command grammar.
- **Destructive actions confirm** — `shutdown`/`restart`/`sleep`/`empty recycle bin`/file-delete arm a
  spoken "say yes"; file delete goes to Recycle Bin, never permanent.
- **Offline by default** — STT + TTS on-device; only the optional Ollama path can leave the machine,
  and only if `OLLAMA_URL` is non-local (warned loudly).
- **CI enforces it** — a grep guard fails the build on `shell=True`/`os.system`/`eval`/`exec`.
- **Residual (by design):** no speaker auth (anyone in mic range can command it); GUI automation is
  best-effort.

---

## 8. Build · run · test (the verification gate)

| Task | Command |
|------|---------|
| **Run** | `start.bat` (root) — first run installs deps + creates `.env`; then tray icon |
| Run (dev) | `cd voiceflow_local && python main.py` |
| **Byte-compile** | `python -m compileall voiceflow_local` |
| **Tests** | `python -m pytest -q` (15 tests; 3 cross-platform + 7 Windows-only + 5 hardening) |
| **Lint** | `python -m ruff check .` (E+F rules; import-sort intentionally off) |
| Mic diagnostic | `cd voiceflow_local && python mic_check.py` |

**Verification gate before any commit:** `compileall` -> `pytest` (green) -> `ruff check` (clean) ->
smoke-launch. **CI** (`.github/workflows/ci.yml`, ubuntu) runs compileall + pytest + ruff + the
shell/eval guard on every push. Windows-only suites skip on Linux (they construct `CommandProcessor`
which touches `winreg`).

**Two Python environments exist on this machine (important!):**
- **System Python** (`…\Python312\python.exe`) — has all app deps; this is what `start.bat` uses to run.
- **`.venv/`** — minimal (pytest + pyyaml only); used for fast, stdlib-only test runs. The app will
  **not** launch from `.venv` (missing sounddevice/faster-whisper/etc.).

---

## 9. Deployment (see `DEPLOY.md`)

1. Clone (or copy). `models/` is gitignored → Whisper auto-downloads on first launch.
2. Install Python 3.11+, run `start.bat`. Fresh-install of pinned `requirements.txt` is **verified** clean.
3. **Footprint tiers:** small.en int8 ~0.5 GB (CPU default, snappy) / large-v3 ~2.9 GB (accuracy, GPU).
   Set `WHISPER_COMPUTE=int8` for ~half the RAM on any machine; `WHISPER_MODEL=small.en` to pin light.
4. Optional: install Ollama + `ollama pull qwen3.5:4b` for the LLM fallback.
5. Optional autostart at login: `install_autostart.bat`.

---

## 10. Troubleshooting runbook (symptom → cause → fix)

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Tray icon up but **no response to voice** | mic dead/muted/wrong device; status shows `mic_dead` | auto-unmute (pycaw) runs automatically; run `python mic_check.py`; set `INPUT_DEVICE` in `.env`; check Windows -> Privacy -> Microphone |
| **"Error loading model"** at startup | faster-whisper missing, or no internet on first run, or GPU cuDNN/VRAM issue | ladder auto-falls to CPU small.en; `pip install -r voiceflow_local/requirements.txt`; set `WHISPER_MODEL=small.en` + `WHISPER_COMPUTE=int8` |
| **No spoken feedback** (silent) | pyttsx3 not installed or SAPI/COM init failed | `pip install pyttsx3`; check log line `TTSEngine`; app still works, just mute |
| **Spotify won't auto-play** | best-effort keystroke reach missed the play button | tune `SPOTIFY_PLAY_TABS`; `SPOTIFY_AUTOPLAY=0` to just cue; local music files play instantly |
| **WhatsApp send fails/wrong** | window-focus timing / focus stolen mid-flow | ensure WhatsApp **desktop** installed; don't touch keyboard/mouse during the flow; retry |
| **"understand anything" phrasing ignored** | Ollama not running | install Ollama, `ollama pull qwen3.5:4b`, keep it running (localhost:11434); it's a silent no-op when down |
| **Wrong command executed** | misheard transcript | check `assets/command_log.txt` for what it heard; rephrase; add a `commands.yaml` alias; re-record accent samples |
| **F9 does nothing** | global hotkey needs elevation on some setups | run `start.bat`/terminal **as Administrator** |
| **App won't launch by voice** | not in `STATIC_MAP` and registry/Start-Menu scan missed it | add it to `commands.yaml` (-> `open_app`) or to `STATIC_MAP` in `app_discovery.py` |
| **Destructive command "didn't run"** | by design — it's waiting for "yes" (15s) | say "yes"/"confirm" within 15s |
| **`pip install` fails on a clone** | wrong Python / missing build tools | Python 3.11+; `pip install -r voiceflow_local/requirements.txt`; `webrtcvad-wheels` supplies the VAD wheel |
| **Timers/state gone after restart** | in-memory by design | expected; re-issue them |
| **Q&A ("who is X") says nothing / web-searches** | no internet (Wikipedia) AND no Ollama | connect internet or run Ollama — there is **no fully-offline knowledge path** |
| CI red on push | pytest or ruff failure, or the shell/eval guard tripped | run `pytest` + `ruff check .` locally; never introduce `shell=True`/`eval` |

---

## 11. Capabilities at a glance (detail in the review notes)

- **Rock-solid:** math, units, time/date/battery/CPU/status, app launch (STATIC_MAP + registry + fuzzy),
  close/focus, media keys (volume/pause/next), timers, screenshots, window/nav hotkeys, destructive-action
  confirm gate, mic robustness, custom commands.
- **Best-effort / conditional:** Spotify play-button (keystroke reach), WhatsApp send (window automation),
  "who is X" Q&A (needs internet or Ollama), LLM phrasing fallback (needs Ollama), context-blind nav keys.
- **Not implemented:** multi-intent in one breath, real multi-turn conversation, structured/persistent
  memory, speaker ID, screen vision, cross-platform.

---

## 12. Git & release state

- **Branch:** `chore/revival-cleanup`, **7 commits ahead** of `master` (`b4e86ae`).
- **Pushed:** `5029c10` (CODEBASE_MAP), `65d12ac` (hygiene).
- **Local only (need push):** `c64c097` (pytest+CI), `045e9ed` (Sprint 1 hardening), `fee4c9e`
  (Sprint 2 robustness), `29d8dc3` (LICENSE/pins/quantization), `b3896ca` (ruff+docs+clean-install).
- **Remote:** github.com/SheeshDarth/NirmiqEcho (public). `models/` must stay gitignored (>100 MB kills the push).
- To ship: push branch -> open PR -> merge to `master` -> tag `v0.1.0`.

---

## 13. Roadmap — the next phase

### Immediate (finish v0.1.0 — do regardless of direction)
1. **Push** the 5 local commits; open PR; merge to `master`.
2. **Live voice test** (human-in-the-loop smoke): open app, math, volume, a destructive one (hear the gate), a Q&A.
3. **Tag `v0.1.0`** + a short `CHANGELOG.md`; record `docs/demo.gif`.
4. (Optional polish) Sprint 3 `handlers/` split / Sprint 4 more tests.

### Strategic fork — "what are we building?" (a real decision, not a task)
Echo is a **command router**, not an agent. To be *literally* JARVIS is an architecture change, not a
feature. Two honest paths:

- **A) Ship & polish the offline command assistant.** It's done, safe, portfolio-worthy. Finish the
  immediate list above and call it 1.0. Keep the "100% offline / light / deterministic" identity.
- **B) Agentic inversion (a v2 track).** Put a capable reasoning model at the center that *plans and
  composes tools*; demote the current regex+handlers to the fast/safe **tool layer** underneath. This
  requires: (1) tools defined with schemas + a planner->tool-call->observe loop, (2) a genuinely
  capable function-calling model — which forces a choice: **bigger local model (kills "light")** *or*
  **hybrid/cloud (kills "100% offline")**, (3) persistent structured memory, (4) real integrations
  instead of keystroke puppetry. This is a **new project** with the current app as its foundation.

**Recommendation:** ship **A as v0.1.0 now** (don't leave finished work unshipped), then start **B on a
new branch as "NirmiqEcho Agent"** — reusing this codebase as the offline tool layer. The single decision
that gates B is: *which constraint dies — "fully offline" or "light on memory"?* Nothing else can start
until that's answered.

---

## 14. Glossary / quick reference

- **Command router vs agent:** Echo matches speech to a fixed command list; an agent reasons about
  intent and chooses tools. Echo's LLM only *normalizes phrasing into existing commands*.
- **Degradation ladder:** `transcription.load_model` tries GPU->GPU-int8->CPU-small.en so it always boots.
- **Confirmation FSM:** `conversation_state` arms destructive actions behind a spoken yes/no (15s timeout).
- **`_recent`:** the one prior request, passed to the LLM so follow-ups resolve pronouns.
- **Verification gate:** `compileall -> pytest -> ruff -> smoke-launch`. Everything ships green.
- **Two Pythons:** system Python runs the app; `.venv` runs stdlib-only tests.

*Last updated: 2026-07-08 (Sprint 6). Keep this file current when the architecture changes.*
