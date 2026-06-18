# Security model — NirmiqEcho

NirmiqEcho executes real OS actions from spoken input, so it is built defensively.
This documents the threat model and the controls in place. Found a hole? Open an
issue (or email the owner) rather than filing it publicly.

## Threat model

| Asset | Threat | Why it matters |
|-------|--------|----------------|
| The OS / shell | Voice → command injection | A crafted utterance could try to run arbitrary commands |
| User files | Accidental / malicious deletion | A misheard command could destroy data |
| The machine | Disruptive actions (shutdown, sleep) | A misfire could lose unsaved work |
| User privacy | Audio / transcripts leaving the device | The whole point is "voice never leaves your machine" |
| Local services | A web page reaching a local port | Browser-driven requests to localhost |

## Controls

### 1. No shell injection from voice
- **No `shell=True`, no `os.system`, no `eval`/`exec`** anywhere in the codebase.
- All process launches use **argument lists** (`subprocess.Popen([exe, *args], shell=False)`).
- App and process names derived from speech are **whitelist-validated**
  (`^[\w.+\- ()]+$`) and protocol launches are restricted to an allowlist
  (`http(s):`, `ms-…:`, `spotify:`, `whatsapp:`). A bare name containing `:` is
  rejected, so `javascript:` / `file://` can't reach `os.startfile`.
- The only PowerShell scripts interpolate **clamped integers** (volume,
  brightness) or a **regex-sanitised** process name (quotes/metacharacters
  stripped) — never raw transcript text.

### 2. The LLM never executes — it only *rewrites*
The optional local-LLM fallback maps a novel phrasing to **one canonical
command string**, which is then **re-matched against the same validated command
grammar**. The model's output is never executed directly; it can only trigger
commands that already exist and are already validated. Prompt-injection of the
model therefore can't exceed the assistant's normal capabilities.

### 3. Destructive / disruptive actions require spoken confirmation
`shutdown`, `restart`, `sleep`, and `empty recycle bin` do **not** run on a
single match. They arm a confirmation ("Say yes to confirm") and execute only on
an explicit affirmative — a misheard command cannot wipe or halt the machine.
File deletion goes to the **Recycle Bin** (never a permanent delete) and also
confirms first.

### 4. Privacy — offline by default
- Transcription (faster-whisper) and TTS (Windows SAPI) run **entirely on-device**.
- The LLM fallback talks to **`localhost:11434`** (Ollama). If `OLLAMA_URL` is
  pointed off-machine, the app **logs a loud PRIVACY warning** at startup, since
  transcripts would then leave the device. Set `LLM_FALLBACK=0` to disable it.
- No telemetry, no analytics, no cloud API keys.

### 5. Secrets & personal data never leave the repo
Gitignored and never committed: `.env`, voice samples (`*.m4a`/`*.wav`), the
accent profile, the local **audit log**, **remembered facts** (`memory.json` —
may hold codes/passwords), and the multi-GB Whisper `models/` cache.

### 6. Local accountability
Every executed command is appended (timestamp · action · args) to a
size-capped local `command_log.txt`. It stays on the machine (gitignored) and
provides an after-the-fact trail of what the assistant did.

## Residual risks (by design, for a single-user local assistant)
- **No speaker authentication** — anyone within mic range can issue commands.
  Mitigations: optional "Hello Echo" wake word, and confirmation on destructive
  actions. Speaker verification is a possible future enhancement.
- **GUI automation is best-effort** — window focus / app automation depends on
  app state; failures are surfaced, never silently assumed successful.
