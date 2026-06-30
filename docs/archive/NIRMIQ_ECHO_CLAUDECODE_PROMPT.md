# NIRMIQ ECHO — CLAUDE CODE MASTER BUILD PROMPT
# For: Claude Opus 4.8 · Ultracode Mode · Single Session
# Target: Local-First Voice Operating System — Phase 1 Complete

---

## IDENTITY & MISSION

You are the sole engineer responsible for building **Nirmiq Echo** — a local-first voice operating
system that sits between a user and their computer. You are not building a chatbot. You are not
building a demo. You are building a professional, production-quality desktop application that will
become the primary voice interface layer for a power user's computer.

This session must produce a fully working Phase 1 system: installable, runnable, with real
voice input, real tool execution, and a professional UI — no stubs, no fake behavior, no placeholders
labeled "TODO: implement later."

Every piece of code you write must be real, typed, tested, and wired together.

---

## ABSOLUTE NON-NEGOTIABLES

- NEVER fake a completed action. If a tool fails, log it and surface the failure.
- NEVER execute raw LLM output. Always parse to a structured plan first.
- NEVER hallucinate success. Verify after every tool execution.
- ALL memory must be local. No cloud calls except to Ollama running locally.
- ALL actions must be logged with timestamp, status, and result.
- EVERY high-risk action (delete, send message, send email) requires explicit confirmation.
- ALWAYS prefer typed Python (Pydantic models everywhere).
- ALWAYS handle errors explicitly — no bare `except:` clauses.
- The UI must feel calm, professional, and fast — not flashy or gimmicky.

---

## TECH STACK — EXACT, NO SUBSTITUTIONS

### Backend (Python 3.11+)
```
faster-whisper==1.1.0          # Local STT — GPU-accelerated on RTX 4050
silero-vad==5.1                # Voice activity detection
sounddevice==0.5.0             # Cross-platform audio capture
openwakeword==0.6.0            # Local wake word detection (MIT license)
websockets==12.0               # IPC between backend and UI
fastapi==0.115.0               # REST + WebSocket server
uvicorn==0.30.0                # ASGI server
pydantic==2.7.0                # Data models and validation
sqlalchemy==2.0.35             # ORM for memory persistence
aiosqlite==0.20.0              # Async SQLite driver
ollama==0.3.3                  # Ollama Python client
pyautogui==0.9.54              # Desktop automation
psutil==6.0.0                  # Process management
python-dotenv==1.0.1           # Config management
structlog==24.1.0              # Structured logging
numpy==1.26.4                  # Audio processing
scipy==1.13.0                  # Signal processing
noisereduce==3.0.2             # Noise suppression
rich==13.7.1                   # Terminal output for dev mode
pytest==8.2.0                  # Testing
pytest-asyncio==0.23.7         # Async test support
```

### Frontend (Electron + React + TypeScript)
```
electron: 31.x
react: 18.x
typescript: 5.x
tailwindcss: 3.x
zustand: 4.x          # State management
lucide-react: 0.x     # Icons
framer-motion: 11.x   # Micro-animations (used sparingly)
```

### Local LLM
- **Ollama** must be running locally with `llama3.2:3b` (fast commands) or `llama3.1:8b` (planning)
- Model abstraction layer — never hardcode model names in business logic
- Graceful degradation if Ollama is not running

---

## PROJECT STRUCTURE — CREATE EXACTLY THIS

```
nirmiq-echo/
├── CLAUDE.md                          # This file (copied there)
├── README.md
├── pyproject.toml                     # Python deps + build config
├── package.json                       # Electron/React deps
├── electron.config.ts
├── tsconfig.json
├── tailwind.config.ts
├── vite.config.ts
│
├── core/                              # Python backend
│   ├── __init__.py
│   ├── main.py                        # Entry point — starts backend server
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py                # Pydantic Settings — all config here
│   │   └── defaults.yaml             # Default configuration values
│   │
│   ├── voice/
│   │   ├── __init__.py
│   │   ├── audio_capture.py           # sounddevice stream + ring buffer
│   │   ├── vad_engine.py              # Silero VAD integration
│   │   ├── wake_word.py               # openWakeWord integration
│   │   ├── transcriber.py             # faster-whisper with streaming
│   │   ├── noise_suppressor.py        # noisereduce integration
│   │   ├── microphone_profile.py      # Per-mic calibration + persistence
│   │   └── voice_pipeline.py         # Orchestrates the full audio→text pipeline
│   │
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── coordinator.py             # Master coordinator — receives intent, plans, dispatches
│   │   ├── planner.py                 # LLM-backed structured plan generator
│   │   ├── executor.py                # Executes plans step by step with verification
│   │   ├── verifier.py                # Post-execution verification
│   │   └── event_bus.py              # Internal pub/sub event bus
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base_model.py              # Abstract LLM backend interface
│   │   ├── ollama_backend.py          # Ollama implementation
│   │   ├── model_router.py            # Route to small/medium/large based on task
│   │   └── model_registry.py         # Available models, status, health check
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── registry.py                # Tool registry — discover, register, validate
│   │   ├── base_tool.py               # Abstract base class for all tools
│   │   ├── builtin/
│   │   │   ├── __init__.py
│   │   │   ├── app_launcher.py        # open_app, close_app, focus_app
│   │   │   ├── file_tools.py          # search_files, create_file, move_file, delete_file
│   │   │   ├── browser_tools.py       # open_url, search_web, navigate
│   │   │   ├── window_manager.py      # window_management, capture_screen
│   │   │   ├── clipboard_tools.py     # copy_text, paste_text, clipboard_manager
│   │   │   ├── system_tools.py        # volume_control, brightness_control
│   │   │   ├── terminal_tool.py       # terminal_executor (with safety guards)
│   │   │   ├── note_tool.py           # take_note, list_notes, search_notes
│   │   │   ├── timer_tool.py          # set_timer, schedule_reminder
│   │   │   └── pdf_tool.py            # pdf_reader, pdf_summarizer
│   │   └── permissions.py             # Tool permission manifest + enforcement
│   │
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── models.py                  # SQLAlchemy ORM models for all memory types
│   │   ├── store.py                   # Unified memory store interface
│   │   ├── short_term.py              # Session-scoped in-memory cache
│   │   ├── long_term.py               # SQLite-backed persistent memory
│   │   ├── project_memory.py          # Project-specific context and paths
│   │   ├── preference_memory.py       # User preferences and patterns
│   │   └── migrations/
│   │       └── 001_initial.sql
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base_agent.py              # Abstract agent interface
│   │   ├── planner_agent.py           # Decomposes intent into plans
│   │   ├── file_agent.py              # File system operations
│   │   ├── automation_agent.py        # Desktop automation tasks
│   │   ├── summarization_agent.py     # Text/document summarization
│   │   └── research_agent.py          # Web research and synthesis
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── server.py                  # FastAPI app + WebSocket endpoint
│   │   ├── routes/
│   │   │   ├── voice.py               # Voice control endpoints
│   │   │   ├── memory.py              # Memory CRUD endpoints
│   │   │   ├── tools.py               # Tool registry endpoints
│   │   │   └── system.py             # Health, status, config endpoints
│   │   └── schemas.py                 # Request/response Pydantic schemas
│   │
│   └── shared/
│       ├── __init__.py
│       ├── types.py                   # Shared type definitions
│       ├── exceptions.py              # Custom exception hierarchy
│       └── logger.py                  # Structured logging setup
│
├── ui/                                # Electron + React frontend
│   ├── electron/
│   │   ├── main.ts                    # Electron main process
│   │   ├── preload.ts                 # Secure IPC bridge
│   │   └── ipc.ts                     # IPC channel definitions
│   │
│   └── src/
│       ├── main.tsx                   # React entry point
│       ├── App.tsx                    # Root component + layout
│       ├── ws.ts                      # WebSocket client singleton
│       │
│       ├── stores/
│       │   ├── voice.store.ts         # Mic state, transcript, VAD status
│       │   ├── engine.store.ts        # Current plan, execution state
│       │   ├── memory.store.ts        # Recent commands, projects
│       │   └── ui.store.ts            # Mode, panel visibility, settings
│       │
│       ├── components/
│       │   ├── TopBar.tsx             # Mode indicator, mic status, model status
│       │   ├── BottomBar.tsx          # Listen/Stop/PTT/Dictation/Settings buttons
│       │   ├── SidePanel.tsx          # Memory, Commands, Projects, Tools, Logs
│       │   ├── LiveTranscript.tsx     # Streaming partial + final transcript
│       │   ├── ExecutionPlan.tsx      # Live plan visualization with step status
│       │   ├── TaskStatus.tsx         # Current executing task with progress
│       │   ├── AssistantResponse.tsx  # Final response with action confirmation
│       │   ├── ActivityFeed.tsx       # Timestamped event log
│       │   ├── ConfirmationModal.tsx  # High-risk action confirmation dialog
│       │   ├── MicVisualizer.tsx      # Minimal waveform/VAD indicator
│       │   └── StatusDot.tsx          # Reusable status indicator
│       │
│       └── styles/
│           ├── globals.css
│           └── design-tokens.css      # All CSS variables defined here
│
├── plugins/
│   ├── __init__.py
│   ├── base_plugin.py                 # Plugin interface contract
│   └── registry.py                    # Plugin discovery and loading
│
├── config/
│   ├── nirmiq.yaml                    # User configuration file
│   └── models.yaml                    # Model configuration
│
└── tests/
    ├── core/
    │   ├── test_voice_pipeline.py
    │   ├── test_planner.py
    │   ├── test_tool_registry.py
    │   ├── test_memory_store.py
    │   └── test_executor.py
    └── conftest.py
```

---

## DESIGN TOKENS — UI MUST USE THESE EXACTLY

```css
/* design-tokens.css */
:root {
  /* Surfaces */
  --surface-base:      #0d0f11;   /* App background */
  --surface-raised:    #13161a;   /* Panels, cards */
  --surface-overlay:  #1a1e24;   /* Modals, dropdowns */
  --surface-hover:     #1e2329;   /* Interactive hover */
  --surface-active:   #22272f;   /* Active/selected state */

  /* Borders */
  --border-subtle:    rgba(255,255,255,0.06);
  --border-default:   rgba(255,255,255,0.10);
  --border-strong:    rgba(255,255,255,0.18);

  /* Text */
  --text-primary:     #e8eaed;
  --text-secondary:   #9aa3b0;
  --text-muted:       #5c6470;
  --text-inverse:     #0d0f11;

  /* Accent — single, used sparingly */
  --accent:           #4a9eff;
  --accent-dim:       rgba(74,158,255,0.15);
  --accent-subtle:    rgba(74,158,255,0.08);

  /* Semantic status */
  --status-listening: #4a9eff;
  --status-thinking:  #a78bfa;
  --status-executing: #34d399;
  --status-warning:   #fbbf24;
  --status-error:     #f87171;
  --status-idle:      #5c6470;

  /* Typography */
  --font-ui:          'Inter', system-ui, sans-serif;
  --font-mono:        'JetBrains Mono', 'Fira Code', monospace;

  --text-xs:    11px;
  --text-sm:    12px;
  --text-base:  13px;
  --text-md:    14px;
  --text-lg:    16px;
  --text-xl:    18px;

  --weight-normal:   400;
  --weight-medium:   500;
  --weight-semibold: 600;

  /* Spacing */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;

  /* Radius */
  --radius-sm:  4px;
  --radius-md:  6px;
  --radius-lg:  8px;
  --radius-xl:  12px;

  /* Motion — all animations must be subtle */
  --duration-fast:    80ms;
  --duration-normal: 150ms;
  --duration-slow:   250ms;
  --ease-default:    cubic-bezier(0.2, 0, 0, 1);
}
```

---

## UI LAYOUT — IMPLEMENT EXACTLY THIS

```
┌──────────────────────────────────────────────────────────┐
│ TOP BAR (40px)                                            │
│  [●] Nirmiq Echo    [ASSISTANT MODE]    [●Mic] [●llama3] │
├──────────────────────────────────────────────────────────┤
│ MAIN PANEL                        │ SIDE PANEL (240px)   │
│                                   │                       │
│  LIVE TRANSCRIPT                  │  [Memory]             │
│  ─────────────────                │  [Recent Commands]    │
│  "Open VS Code and continue my    │  [Projects]           │
│   Agion project."                 │  [Tools]              │
│                                   │  [Agents]             │
│  EXECUTION PLAN                   │  [Logs]               │
│  ─────────────────                │                       │
│  ✓ 1. Detect project path         │  ── Recent ──         │
│  ⟳ 2. Launch VS Code              │  • Open Chrome        │
│  ○ 3. Open workspace              │  • Note: meeting 3pm  │
│                                   │  • Search AI news     │
│  RESPONSE                         │                       │
│  ─────────────────                │  ── Projects ──       │
│  Launching VS Code with your      │  • Agion              │
│  Agion project at ~/projects/...  │  • CREDA              │
│                                   │  • AnonThera          │
│  ACTIVITY FEED                    │                       │
│  ─────────────────                │                       │
│  10:42:01 Tool: open_app ✓        │                       │
│  10:42:00 Plan created (3 steps)  │                       │
│  10:41:59 Intent classified       │                       │
│  10:41:58 Wake word detected      │                       │
├──────────────────────────────────────────────────────────┤
│ BOTTOM BAR (48px)                                         │
│  [🎤 Listen]  [⏹ Stop]  [PTT]  [📝 Dictate]  [⚙ Settings] │
└──────────────────────────────────────────────────────────┘
```

**UI Rules:**
- No gradients. No glow effects. No animations larger than 4px movement.
- Information density over whitespace. Every pixel should earn its place.
- Plan steps show: ✓ (done), ⟳ (running, animated), ○ (pending), ✗ (failed)
- Live transcript streams character by character with a blinking cursor
- Activity feed auto-scrolls, shows last 50 entries
- Side panel tabs use subtle underline active state, not background fills
- Confirmation modal is the only fullscreen overlay — used only for destructive actions

---

## DATA MODELS — IMPLEMENT ALL OF THESE WITH PYDANTIC

```python
# core/shared/types.py

from enum import Enum
from pydantic import BaseModel, Field
from typing import Any, Optional, Literal
from datetime import datetime

class EngineMode(str, Enum):
    DICTATION = "dictation"
    ASSISTANT = "assistant"
    RESEARCH = "research"
    DEVELOPER = "developer"
    FOCUS = "focus"

class VoiceState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    VAD_DETECTED = "vad_detected"
    TRANSCRIBING = "transcribing"
    WAKE_DETECTED = "wake_detected"

class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    AWAITING_CONFIRMATION = "awaiting_confirmation"

class RiskLevel(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class PlanStep(BaseModel):
    step_id: str
    step_number: int
    description: str
    tool_name: str
    tool_args: dict[str, Any]
    status: StepStatus = StepStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    risk_level: RiskLevel = RiskLevel.SAFE

class ExecutionPlan(BaseModel):
    plan_id: str
    raw_intent: str
    steps: list[PlanStep]
    created_at: datetime
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None

class ToolResult(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    verified: bool = False

class WSMessage(BaseModel):
    event: str
    payload: dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class MemoryEntry(BaseModel):
    memory_id: str
    memory_type: Literal["short", "long", "project", "preference", "workflow"]
    key: str
    value: Any
    tags: list[str] = []
    created_at: datetime
    accessed_at: Optional[datetime] = None
    access_count: int = 0
```

---

## VOICE PIPELINE — IMPLEMENT THIS EXACT FLOW

```
Microphone Input
      ↓
Audio Ring Buffer (circular, 30s)
      ↓
Noise Suppressor (noisereduce, real-time)
      ↓
VAD Engine (Silero, 10ms chunks)
      ↓
  [Speech Detected?]
       │ No → continue buffering
       │ Yes ↓
Wake Word Detector (openWakeWord)
      ↓
  [Wake word found?]
       │ No  → discard segment
       │ Yes ↓
faster-whisper (stream transcription)
      ↓
Partial transcript → WebSocket → UI (live display)
      ↓
Final transcript → Intent Classifier
      ↓
Structured Intent → Coordinator
```

**Implementation requirements:**
- Audio is processed in a background thread, never blocking the main thread
- VAD uses 256ms windows with 10ms hop
- Silence timeout: 1.5 seconds after last speech ends the utterance
- Whisper model: `base.en` for speed, upgradeable via config
- Wake word confidence threshold: 0.5 (configurable)
- All partial transcripts fire WebSocket events of type `transcript.partial`
- Final transcript fires `transcript.final`
- Microphone profile stores: RMS baseline, noise floor, sample rate, device index

---

## TOOL IMPLEMENTATION — IMPLEMENT ALL BUILTIN TOOLS

Each tool must follow this contract:

```python
# core/tools/base_tool.py

from abc import ABC, abstractmethod
from pydantic import BaseModel
from core.shared.types import ToolResult, RiskLevel

class ToolInput(BaseModel):
    pass  # Override in each tool

class BaseTool(ABC):
    name: str              # snake_case identifier
    description: str       # One sentence — used by planner
    risk_level: RiskLevel  # Determines if confirmation is required

    @abstractmethod
    async def execute(self, args: dict) -> ToolResult:
        pass

    @abstractmethod
    def validate_args(self, args: dict) -> tuple[bool, str]:
        pass

    def requires_confirmation(self) -> bool:
        return self.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
```

**Tools to implement in Phase 1 (all of these, fully working):**

| Tool | Risk | Key behavior |
|------|------|-------------|
| `open_app` | LOW | psutil check if running, launch if not, focus if yes |
| `close_app` | MEDIUM | Graceful close with SIGTERM, force after 3s timeout |
| `search_files` | SAFE | Recursive search with glob + content search |
| `create_file` | LOW | Atomic write, no overwrite without confirmation |
| `move_file` | MEDIUM | Verify source exists, verify destination writable |
| `delete_file` | HIGH | Move to trash first, never permanent delete in Phase 1 |
| `open_url` | SAFE | Open in default browser, validate URL |
| `search_web` | SAFE | Open browser with search query, no scraping yet |
| `window_manager` | LOW | List windows, focus by name, minimize/maximize |
| `capture_screen` | LOW | Full screenshot, save to temp, return path |
| `copy_text` | SAFE | Write to clipboard via pyperclip |
| `paste_text` | LOW | Type or paste text at cursor |
| `volume_control` | SAFE | Get/set system volume (0–100) |
| `take_note` | SAFE | Append timestamped entry to notes.md in ~/NirmiqNotes/ |
| `list_notes` | SAFE | Return last N notes with timestamps |
| `search_notes` | SAFE | Full-text search in ~/NirmiqNotes/ |
| `set_timer` | SAFE | asyncio-based timer, fires WebSocket event on completion |
| `terminal_executor` | HIGH | Execute shell command — requires confirmation, never sudo |
| `pdf_summarizer` | SAFE | Extract text with PyPDF2, send to LLM for summary |
| `launch_project` | SAFE | Memory-backed: open stored project path in configured editor |

---

## PLANNER — IMPLEMENT THE FULL CHAIN

The planner must NEVER return free text. It must always return a structured `ExecutionPlan`.

```python
# Planner prompt template (inject this exactly)

PLANNER_SYSTEM_PROMPT = """
You are the planning engine for Nirmiq Echo, a voice operating system.
Your job is to convert a natural language intent into a precise, ordered execution plan.

You must respond ONLY with valid JSON matching this exact schema:
{
  "plan_id": "<uuid>",
  "steps": [
    {
      "step_number": 1,
      "description": "Human-readable description",
      "tool_name": "exact_tool_name",
      "tool_args": { "arg_key": "arg_value" },
      "risk_level": "safe|low|medium|high|critical"
    }
  ],
  "requires_confirmation": false,
  "confirmation_message": null
}

Available tools:
{tool_list}

Memory context:
{memory_context}

Rules:
- Use only tools from the available list
- Never add steps that aren't necessary
- If any step is HIGH risk, set requires_confirmation to true
- confirmation_message must be a clear, friendly sentence explaining what will happen
- If you cannot create a valid plan, return: {"error": "reason"}
- Do not wrap in markdown, do not explain, return only JSON
"""
```

---

## MEMORY SYSTEM — DATABASE SCHEMA

```sql
-- migrations/001_initial.sql

CREATE TABLE IF NOT EXISTS memory_entries (
    id          TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL,   -- short|long|project|preference|workflow
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,   -- JSON serialized
    tags        TEXT DEFAULT '[]',
    created_at  TEXT NOT NULL,
    accessed_at TEXT,
    access_count INTEGER DEFAULT 0,
    UNIQUE(memory_type, key)
);

CREATE TABLE IF NOT EXISTS command_history (
    id           TEXT PRIMARY KEY,
    raw_input    TEXT NOT NULL,
    intent       TEXT,
    plan_id      TEXT,
    status       TEXT NOT NULL,  -- success|failed|cancelled
    executed_at  TEXT NOT NULL,
    duration_ms  INTEGER
);

CREATE TABLE IF NOT EXISTS execution_logs (
    id          TEXT PRIMARY KEY,
    plan_id     TEXT NOT NULL,
    step_number INTEGER NOT NULL,
    tool_name   TEXT NOT NULL,
    tool_args   TEXT NOT NULL,   -- JSON
    result      TEXT,            -- JSON
    status      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT
);

CREATE INDEX idx_memory_type_key ON memory_entries(memory_type, key);
CREATE INDEX idx_command_history_executed ON command_history(executed_at DESC);
CREATE INDEX idx_logs_plan_id ON execution_logs(plan_id);
```

---

## WEBSOCKET PROTOCOL — ALL EVENTS

The backend must emit these WebSocket events in real-time:

| Event | Direction | Payload |
|-------|-----------|---------|
| `voice.state_change` | server→client | `{state: VoiceState}` |
| `transcript.partial` | server→client | `{text: str, confidence: float}` |
| `transcript.final` | server→client | `{text: str, duration_ms: int}` |
| `wake_word.detected` | server→client | `{phrase: str, confidence: float}` |
| `plan.created` | server→client | `{plan: ExecutionPlan}` |
| `plan.step_update` | server→client | `{plan_id: str, step_id: str, status: StepStatus, result?: any}` |
| `plan.completed` | server→client | `{plan_id: str, success: bool, summary: str}` |
| `confirmation.required` | server→client | `{plan_id: str, message: str, action_summary: str}` |
| `response.text` | server→client | `{text: str, plan_id?: str}` |
| `memory.updated` | server→client | `{key: str, memory_type: str}` |
| `system.status` | server→client | `{mic: bool, llm: bool, model_name: str}` |
| `timer.fired` | server→client | `{label: str, duration_s: int}` |
| `confirmation.response` | client→server | `{plan_id: str, confirmed: bool}` |
| `voice.control` | client→server | `{action: "start"\|"stop"\|"ptt_start"\|"ptt_stop"}` |
| `mode.change` | client→server | `{mode: EngineMode}` |

---

## MODES — IMPLEMENT ALL 5

### Mode 1: Dictation
- Voice → Text only
- No LLM, no planning
- Output typed into active window via pyautogui
- Indicator: `[DICTATION MODE]` in top bar, green mic

### Mode 2: Assistant (DEFAULT)
- Voice → Intent → Plan → Execute → Verify
- Full pipeline
- Indicator: `[ASSISTANT MODE]` in top bar, blue mic

### Mode 3: Research
- Voice → Search web → Fetch page → LLM summarize → Speak/display
- Opens browser, fetches top result, summarizes
- Indicator: `[RESEARCH MODE]` in top bar, purple mic

### Mode 4: Developer
- Voice → Terminal command (with confirmation)
- All commands logged with output
- No auto-execute: always shows plan and requires confirmation
- Indicator: `[DEVELOPER MODE]` in top bar, amber mic

### Mode 5: Focus
- Minimal UI (just mic indicator + transcript)
- No side panel
- No activity feed
- Muted system sounds
- Indicator: `[FOCUS MODE]` in top bar, dim mic

---

## SETTINGS PANEL — IMPLEMENT THESE SETTINGS

```
VOICE
  Microphone Device          [dropdown]
  Sensitivity                [slider 0–100]
  Wake Word                  [text input]
  Wake Word Confidence       [slider 0.3–0.9]
  Noise Suppression          [toggle]
  Calibrate Microphone       [button]

MODEL
  Command Model              [dropdown: llama3.2:3b, llama3.1:8b, custom]
  Planning Model             [dropdown]
  Reasoning Model            [dropdown]
  Ollama Endpoint            [text input: http://localhost:11434]
  Test Connection            [button]

MEMORY
  Storage Location           [path picker]
  Auto-clear short-term      [toggle]
  Session timeout (minutes)  [number input]
  Export Memory              [button]
  Clear All Memory           [button — destructive, confirmation required]

SYSTEM
  Launch at startup          [toggle]
  Log level                  [dropdown: INFO, DEBUG, WARNING]
  Open log folder            [button]
  Check for updates          [button]
  About Nirmiq Echo          [version, build date]
```

---

## BUILD ORDER — EXECUTE IN THIS EXACT SEQUENCE

Do not skip ahead. Each phase must be fully working before continuing.

### CHECKPOINT 1: Python Backend Foundation
1. Create project root, `pyproject.toml`, and all `__init__.py` files
2. Implement `core/shared/` — types, exceptions, logger
3. Implement `core/config/settings.py` with Pydantic Settings
4. Implement `core/memory/` — models, store, migrations
5. Run: `python -c "from core.memory.store import MemoryStore; print('Memory OK')"` — must pass

### CHECKPOINT 2: Voice Pipeline
1. Implement `core/voice/audio_capture.py`
2. Implement `core/voice/vad_engine.py`
3. Implement `core/voice/noise_suppressor.py`
4. Implement `core/voice/transcriber.py`
5. Implement `core/voice/wake_word.py`
6. Implement `core/voice/voice_pipeline.py`
7. Run: `python -m core.voice.voice_pipeline --test` — must print VAD events and sample transcription

### CHECKPOINT 3: Tool Registry + All Builtin Tools
1. Implement `core/tools/registry.py` and `core/tools/base_tool.py`
2. Implement every tool in `core/tools/builtin/`
3. Run: `python -c "from core.tools.registry import ToolRegistry; r = ToolRegistry(); print(len(r.tools), 'tools loaded')"` — must show 20+

### CHECKPOINT 4: Engine — Coordinator + Planner + Executor
1. Implement `core/engine/event_bus.py`
2. Implement `core/engine/planner.py`
3. Implement `core/engine/executor.py`
4. Implement `core/engine/verifier.py`
5. Implement `core/engine/coordinator.py`
6. Test: Feed `"open chrome and search for AI news"` through planner — must return valid JSON plan

### CHECKPOINT 5: FastAPI + WebSocket Server
1. Implement `core/api/schemas.py`
2. Implement all routes
3. Implement `core/api/server.py`
4. Start server, test WebSocket with `wscat -c ws://localhost:8765` — must respond to events

### CHECKPOINT 6: Electron + React UI
1. Set up Electron project in `ui/`
2. Implement design tokens CSS
3. Implement all stores (Zustand)
4. Implement all components (follow layout spec exactly)
5. Wire WebSocket client to all stores
6. Test: Run UI, verify live transcript appears when speaking

### CHECKPOINT 7: Integration + All 5 Modes
1. Wire all modes with mode switching
2. Test full flow: speak "Nirmiq, open Chrome" → wake word detected → transcript → plan → execute → verify → confirmation
3. Test dictation mode: speak freely → text appears in active window
4. Test settings panel: all settings persist to `config/nirmiq.yaml`

### CHECKPOINT 8: Tests + Polish
1. Write tests for all `core/` modules
2. Run `pytest` — all must pass
3. Create `README.md` with setup instructions
4. Create install script: `setup.sh` (Linux/Mac) and `setup.bat` (Windows)

---

## ERROR HANDLING STANDARDS

Every async function must follow this pattern:

```python
async def execute_tool(self, tool_name: str, args: dict) -> ToolResult:
    log = get_logger(__name__)
    try:
        tool = self.registry.get(tool_name)
        if not tool:
            return ToolResult(success=False, error=f"Unknown tool: {tool_name}")

        valid, error_msg = tool.validate_args(args)
        if not valid:
            return ToolResult(success=False, error=f"Invalid args: {error_msg}")

        result = await tool.execute(args)
        log.info("tool.executed", tool=tool_name, success=result.success)
        return result

    except asyncio.TimeoutError:
        log.error("tool.timeout", tool=tool_name)
        return ToolResult(success=False, error="Tool execution timed out")
    except PermissionError as e:
        log.error("tool.permission_denied", tool=tool_name, error=str(e))
        return ToolResult(success=False, error="Permission denied")
    except Exception as e:
        log.exception("tool.unexpected_error", tool=tool_name, error=str(e))
        return ToolResult(success=False, error=f"Unexpected error: {type(e).__name__}")
```

---

## PLUGIN INTERFACE — SCAFFOLD FOR PHASE 4

```python
# plugins/base_plugin.py

from abc import ABC, abstractmethod
from pydantic import BaseModel
from core.tools.base_tool import BaseTool

class PluginManifest(BaseModel):
    name: str
    version: str
    description: str
    author: str
    tools: list[str]
    permissions: list[str]

class BasePlugin(ABC):
    manifest: PluginManifest

    @abstractmethod
    async def register(self) -> list[BaseTool]:
        """Return list of tools this plugin provides."""
        pass

    @abstractmethod
    async def on_load(self) -> None:
        """Called when plugin is loaded."""
        pass

    @abstractmethod
    async def on_unload(self) -> None:
        """Called when plugin is unloaded."""
        pass

    def get_permissions(self) -> list[str]:
        return self.manifest.permissions
```

---

## CONFIRMATION FLOW — IMPLEMENT EXACTLY

When a high-risk step is detected:

1. Executor pauses at that step
2. Fires `confirmation.required` WebSocket event
3. UI renders `ConfirmationModal` with:
   - Title: "Confirm Action"
   - Body: the `confirmation_message` from the plan
   - Action summary: formatted list of what will change
   - Buttons: "Yes, do it" (accent) and "Cancel" (ghost)
4. UI fires `confirmation.response` back to server
5. If confirmed → executor continues
6. If cancelled → executor marks step as `SKIPPED`, plan ends, logs cancellation

---

## FINAL DELIVERABLE CHECKLIST

Before declaring Phase 1 complete, verify every item:

- [ ] `python -m core.main` starts the backend without errors
- [ ] Backend WebSocket server accepts connections on `ws://localhost:8765`
- [ ] Speaking "Nirmiq" activates the system (wake word works)
- [ ] Live transcript appears in UI while speaking
- [ ] "Nirmiq, open Chrome" launches Chrome
- [ ] "Nirmiq, take a note: meeting at 3pm" saves to ~/NirmiqNotes/
- [ ] "Nirmiq, what are my recent notes?" reads back last 3 notes
- [ ] "Nirmiq, set a timer for 5 minutes" fires timer event after 5 minutes
- [ ] All 5 modes are selectable from the UI
- [ ] Settings panel opens and saves to config/nirmiq.yaml
- [ ] Activity feed shows all events in real-time
- [ ] Side panel shows recent commands and projects from memory
- [ ] High-risk action (delete file) shows confirmation modal
- [ ] `pytest tests/` passes all tests
- [ ] UI renders with correct design tokens (dark, minimal, professional)

---

## START COMMAND

Begin with Checkpoint 1. Create the project root and establish the foundation.
Do not ask for clarification. Make reasonable decisions and proceed.
Every file you create must be complete and immediately importable/runnable.
Do not create stub files with pass statements unless they are explicitly placeholder interfaces.
Move through checkpoints sequentially. At each checkpoint, run the verification command before proceeding.
When complete, run the full deliverable checklist.

**This is Nirmiq Echo. Build it.**
