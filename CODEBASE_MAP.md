# NirmiqEcho — Codebase Map

A complete map of the **NirmiqEcho** voice assistant: what's active, what's dead,
how data flows, and where it could go wrong. NirmiqEcho is a local-first, offline
Python/Windows tray app — **there is no database, no web API, and no UI framework**,
so this map describes a *voice pipeline*, not a request/response web stack.

> Inventory source: `git ls-files` (the gitignored `.venv/`, `models/`, `.env`,
> `Test*.m4a`, and `assets/*.json|txt` runtime data are excluded by design).

---

## 1. Active surface — entry points & modules that work

### Entry points
| File | Role |
|------|------|
| `start.bat` | **Canonical launcher.** First run: `pip install -r voiceflow_local/requirements.txt` (guarded by `.deps_ok`), copies `.env.example` → `.env`, then `cd voiceflow_local && python main.py`. |
| `start_silent.vbs` + `install_autostart.bat` | Optional silent launch at Windows login (Startup-folder shortcut). |
| `.github/workflows/ci.yml` | CI: byte-compiles every module, runs offline logic tests, and a guard that fails on `shell=True`/`os.system`/`eval`/`exec`. |
| `voiceflow_local/main.py` | **App orchestrator** — `NirmiqEchoApp` wires every subsystem, owns the `_on_result(text)` pipeline, the F9 hotkey, the wake word, and the tray lifecycle. This is the real program entry. |

### Core modules (all live, all imported by `main.py` / `command_processor.py`)
| Module | Responsibility |
|--------|----------------|
| `audio_handler.py` | Mic capture (sounddevice) · hybrid VAD (webrtcvad + adaptive energy gate) · noise reduction · **mic auto-rescue** (Windows un-mute, dead-device scan, spin-up skip). |
| `transcription.py` | faster-whisper STT · GPU `large-v3` / CPU `small.en` auto-select with a degradation ladder · model-cache reuse. |
| `wake_word.py` | "Hello Echo" wake-word detector (Whisper tiny). |
| `post_processor.py` | Transcript cleanup + Whisper hallucination filter. |
| `accent_profile.py` | Builds an accent-tuned `initial_prompt` from the owner's voice samples. |
| `command_processor.py` | **The engine.** ~94 regex patterns, custom-command loader, math/units routing, LLM-fallback wiring, confirmation gate, audit log, multi-turn context, and ~all handlers. |
| `calculator.py` · `units.py` | Offline math (restricted-AST eval) and unit/date conversions. |
| `knowledge.py` | Spoken Q&A — Wikipedia REST summary → local Ollama → web-search fallback. |
| `llm_fallback.py` | Optional local **Ollama** fallback (`map_to_command`, `ask`), health cache, multi-turn context, egress/privacy guard. |
| `conversation_state.py` | Multi-step intent FSM (WhatsApp flow, generic yes/no confirmation). |
| `file_assistant.py` | File find / open / move / delete (Recycle Bin). |
| `app_discovery.py` | Windows app discovery (registry + Start Menu + protocol URIs). |
| `tts_engine.py` | Offline TTS (pyttsx3 / Windows SAPI, with COM init). |
| `typer.py` | Clipboard / keystroke text injection into the focused window. |
| `ui.py` | tkinter + **pystray** system-tray UI (transcript, status, controls). |
| `utils.py` | Logging setup, `HotkeyManager`, system-info probes. |
| `mic_check.py` | Standalone mic diagnostic (`python mic_check.py`). |

### Command surface (what actually works when you speak)
Resolved inside `command_processor.process()` in priority order: **conversation state →
math → units → ~94 built-in regex patterns → user `commands.yaml` → local-LLM
fallback**. Covers: apps (open/close/focus), files, WhatsApp send-flow, Spotify/media,
window & system control, volume/brightness, timers, math & unit conversions, spoken
Q&A, jokes, remember/recall, CPU/system status, screenshots, and user-defined custom
commands. Destructive commands (`shutdown`/`restart`/`sleep`/`empty recycle bin`) are
gated behind spoken confirmation.

---

## 2. Dead files, duplicates & unused

| Finding | Evidence | Recommendation |
|---------|----------|----------------|
| `legacy_prototype/` (old root prototype) | **Already deleted** — 0 files on disk, 0 importers in `voiceflow_local/`. | ✅ Resolved — nothing to do. |
| **Duplicate launchers** `voiceflow_local/run.bat` + `voiceflow_local/setup.bat` | Both only `pip install` + `python main.py` — exactly what root `start.bat` already does. `run.bat` still says *"Voice Typing (Offline)"* (pre-rename branding). | Remove both, or keep one and document it as an in-folder alt-launcher. |
| **Stale planning/spec docs (9)** at repo root: `BACKEND_ARCHITECTURE.md`, `CODEX_IMPLEMENTATION.md`, `DEBUGGING.md`, `NIRMIQ_ECHO_CLAUDECODE_PROMPT.md`, `PRD.md`, `TRD.md`, `UI_UX.md`, `UI_UXprompt.md`, `context.md` | Pre-build planning artifacts; the live docs are `README.md`, `SECURITY.md`, `DEPLOY.md`. They bloat the root and blur "what's current." | Move to `docs/archive/` or delete. |
| **Scratch/one-off scripts** mixed with real tests | `test_e2e.py` *actually launches apps*; `test_launch.py` boots the full GUI; `test_accuracy.py` benchmarks models; `test_audio_path.py` needs `.m4a` + models; `test_fallback.py` needs a live Ollama. None are assertion suites. | Move to `scripts/` (or `tests/manual/`); keep them, but don't present them as the test suite. |
| **Repeatable test suites** (keep) | `test_safety`, `test_capabilities`, `test_conversational`, `test_calc_routing`, `test_knowledge`, `test_confirm`, `test_custom_commands`, `test_context` + `calculator.py`/`units.py` self-tests. | Consolidate into a `tests/` dir; CI currently runs only `calculator`, `units`, `test_custom_commands` (the rest need Windows/audio). |
| Unused exports | `utils.py` / helpers — no glaring orphans observed; modules are all reachable. | Low priority; a `vulture`/`ruff`-unused pass during cleanup would confirm. |

**No leaked secrets / stray artifacts in the repo:** `.env`, `models/`, `Test*.m4a`,
`assets/accent_profile.json`, `assets/memory.json`, `assets/command_log.txt`, and
`commands.yaml` are all gitignored — only `.env.example` and `commands.example.yaml`
(templates) are tracked.

---

## 3. Data & state flow

There is **no database and no API server** — "state" is the audio → intent → action
pipeline plus a few small local state stores.

```
Mic  (sounddevice, audio_handler.py)
   |   VAD (webrtcvad + energy gate) - noise reduction - mic auto-rescue
   v
 speech_queue --> transcription.py  (faster-whisper: GPU large-v3 / CPU small.en)
   |
   v   text
 main.py - NirmiqEchoApp._on_result(text)
   |   post_processor.clean()  (fillers + hallucination filter)
   v
 command_processor.process(text):
     1 conversation_state (multi-step / awaiting-confirm)
     2 calculator        (offline math)
     3 units             (conversions, dates)
     4 PATTERNS          (~94 built-in regex commands)
     5 commands.yaml     (user-defined custom phrases)
     6 llm_fallback      (local Ollama + multi-turn `_recent` context)
   |   -> CommandResult
   v
 command_processor.execute(result):
     - _audit(action, args)  --> assets/command_log.txt
     - update _recent        (for next turn's follow-up resolution)
     - dispatch -> handler effects:
         app_discovery + subprocess/os.startfile   (launch apps)
         file_assistant                            (find/open/move/trash files)
         pyautogui / keyboard                       (type, media keys, navigation)
         knowledge.answer                           (Q&A: Wikipedia -> Ollama)
         _require_confirm -> conversation_state      (destructive-action gate)
   v
 tts_engine (speak)   +   ui.py (tray transcript / status)
```

### State stores
| Store | Lifetime | Holds |
|-------|----------|-------|
| `conversation_state.py` (`ConversationStateManager`) | in-memory (session) | multi-step intent (WhatsApp contact→message; yes/no confirmations) |
| `command_processor._recent` | in-memory (session) | last topic-bearing request → resolves follow-up pronouns ("how tall is *it*") |
| `assets/memory.json` | persistent (gitignored) | "remember / recall" facts (may be sensitive) |
| `assets/command_log.txt` | persistent (gitignored, size-capped) | audit trail of executed commands |
| `assets/accent_profile.json` | persistent (gitignored) | accent-tuned Whisper prompt |
| `.env` | persistent (gitignored) | config (Whisper model, mic device, Ollama URL, fallback on/off) |

The optional LLM path is the only thing that can leave the machine, and only if
`OLLAMA_URL` is pointed off-host — in which case `llm_fallback` logs a loud privacy
warning. Everything else is 100% on-device.

---

## 4. Where it's going wrong (issues & architecture review)

**Highest-value:**
1. **God module.** `command_processor.py` (~1,800 lines) holds the patterns, *every*
   handler, the custom-command loader, the audit log, the confirmation gate, and the
   WhatsApp/Spotify/file logic. It works and is tested, but it's the main maintenance
   risk. → Split handlers by domain (`handlers/apps.py`, `handlers/media.py`, …),
   keeping `process()`/`execute()` as the thin router. (Ironically, the deleted OS
   prototype already had this split.)
2. **Test sprawl + thin CI.** 13 `test_*.py` files sit beside source as standalone
   `main()` scripts (not pytest-discoverable); CI only runs 3 because the rest need
   Windows/audio/Ollama. → Move to `tests/`, convert to `test_*` functions, add a
   `conftest.py`, and skip-mark the Windows-only ones so `pytest` runs everything
   runnable.

**Medium:**
3. **Doc cruft.** 9 stale planning docs at root drown the 3 current ones; multiple
   `README.md` files (`/`, `voiceflow_local/`, `assets/`) risk drift. → Archive the
   stale set; keep one canonical README.
4. **Duplicate launchers.** `run.bat` / `setup.bat` vs `start.bat` (see §2).
5. **No packaging / fragile imports.** No `pyproject.toml`; modules import each other
   flatly and tests rely on cwd = `voiceflow_local/`. → A minimal `pyproject.toml` +
   package layout would make imports and `pytest` robust.

**Confirmed-good (record these — they're the portfolio strengths):**
- Security: **no `shell=True` / `os.system` / `eval`**; whitelist-validated app/process
  names; PowerShell scripts only interpolate clamped ints or sanitized names;
  destructive actions are confirmation-gated; LLM output is only ever *re-matched*
  against the validated command grammar, never executed. See `SECURITY.md`.
- Privacy: offline-first; `.env`, models, voice samples, remembered facts all
  gitignored; off-host Ollama triggers a warning.
- Resilience: mic auto-rescue, GPU/CPU degradation ladder, hallucination filtering.

### Suggested next steps (not done in this report)
1. Delete `run.bat` + `setup.bat`; move the 9 stale docs to `docs/archive/`.
2. Create `tests/`, convert the 8 assertion suites to pytest, skip-mark Windows-only
   ones, and broaden CI to run them.
3. Split `command_processor.py` handlers into a `handlers/` package.
4. Add a minimal `pyproject.toml`.

> These are **recommendations only** — this document changes nothing. Say the word
> and I'll execute any of them (each is small and reversible).

---
*Generated as a static snapshot of NirmiqEcho. Cross-references: `README.md`,
`SECURITY.md`, `DEPLOY.md`.*
