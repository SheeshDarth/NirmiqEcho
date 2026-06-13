"""FastAPI app: REST control + WebSocket event stream.

The EventBus is bridged to every connected WebSocket client, so the UI sees
plan.created / step_update / completed / confirmation.required in real time.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from core.config.settings import get_settings
from core.engine.coordinator import Coordinator
from core.shared.logger import get_logger
from core.shared.types import EngineMode
from .schemas import ConfirmationRequest, IntentRequest, ModeRequest, StatusResponse

log = get_logger(__name__)


def _allowed_origins(settings) -> set[str]:
    """Same-origin browser origins for the locally-served dashboard."""
    s = settings.server
    origins: set[str] = set()
    for host in ("127.0.0.1", "localhost"):
        for port in {s.http_port, s.ws_port}:
            origins.add(f"http://{host}:{port}")
            origins.add(f"https://{host}:{port}")
    return origins


def _origin_ok(origin: str | None, allowed: set[str]) -> bool:
    """
    A request is allowed when it carries no Origin header (non-browser
    clients: the voice loop, python, curl, wscat) OR its Origin is one of
    our own localhost origins. A malicious website always sends its real
    Origin (e.g. https://evil.com) and is rejected — this is what stops a
    page you visit from driving the assistant over fetch or WebSocket.
    """
    if not origin:
        return True
    return origin in allowed


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_text(json.dumps(message, default=str))
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


def create_app() -> FastAPI:
    settings = get_settings()
    manager = ConnectionManager()
    coordinator = Coordinator()

    # Bridge every engine event to all websocket clients.
    async def _forward(msg: dict) -> None:
        await manager.broadcast(msg)

    coordinator.bus.subscribe("*", _forward)

    # Optional voice: speaking drives the coordinator. Opt-in so headless/test
    # runs don't grab the mic. Enable with NIRMIQ_VOICE=1.
    voice_enabled = os.getenv("NIRMIQ_VOICE", "0") == "1"
    app_state = {"voice": None, "mode": EngineMode.ASSISTANT}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        llm_ok = await coordinator.router.health()
        log.info("server.startup", llm=llm_ok, tools=len(coordinator.registry.tools),
                 voice=voice_enabled)
        if voice_enabled:
            _start_voice(app_state, coordinator, manager,
                         asyncio.get_running_loop())
        yield
        if app_state["voice"]:
            app_state["voice"].stop()

    app = FastAPI(title="Nirmiq Echo", version="0.1.0", lifespan=lifespan)
    allowed_origins = _allowed_origins(settings)
    # CORS limited to our own localhost origins (the dashboard is same-origin,
    # so this is belt-and-suspenders) — never "*", which would let any site
    # read responses from a command-executing server.
    app.add_middleware(
        CORSMiddleware, allow_origins=sorted(allowed_origins),
        allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
    )

    # Reject any cross-origin browser request to a command-executing server.
    # Defeats CSRF / DNS-rebinding: a page on evil.com sends Origin: evil.com
    # and is blocked, while same-origin and non-browser clients pass.
    @app.middleware("http")
    async def _origin_guard(request: Request, call_next):
        origin = request.headers.get("origin")
        if not _origin_ok(origin, allowed_origins):
            log.warning("server.origin_blocked", origin=origin,
                        path=request.url.path)
            return JSONResponse({"error": "cross-origin request rejected"},
                                status_code=403)
        return await call_next(request)

    _ui = Path(__file__).resolve().parent.parent.parent / "ui" / "web" / "index.html"

    @app.get("/")
    async def index():
        if _ui.exists():
            return FileResponse(str(_ui))
        return {"name": "Nirmiq Echo", "ui": "not found"}

    @app.get("/health")
    async def health() -> StatusResponse:
        return StatusResponse(
            mic=False,  # set by the voice pipeline when wired
            llm=await coordinator.router.health(),
            model_name=settings.models.command_model,
            tools=len(coordinator.registry.tools),
        )

    @app.get("/tools")
    async def tools() -> list[dict]:
        return coordinator.registry.manifest()

    @app.get("/memory/{memory_type}")
    async def memory(memory_type: str) -> list[dict]:
        return [e.model_dump(mode="json")
                for e in coordinator.memory.list(memory_type)]

    @app.get("/commands/recent")
    async def recent() -> list[dict]:
        return coordinator.memory.recent_commands()

    @app.post("/intent")
    async def intent(req: IntentRequest) -> dict:
        return await coordinator.handle_intent(req.text, req.mode)

    @app.post("/confirm")
    async def confirm(req: ConfirmationRequest) -> dict:
        coordinator.confirm(req.plan_id, req.confirmed)
        return {"ok": True}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        # WebSockets are NOT covered by CORS — a malicious site could open
        # this socket and send intent.submit. Validate Origin before accept.
        if not _origin_ok(ws.headers.get("origin"), allowed_origins):
            log.warning("ws.origin_blocked", origin=ws.headers.get("origin"))
            await ws.close(code=1008)  # policy violation
            return
        await manager.connect(ws)
        try:
            # announce current status on connect
            await ws.send_text(json.dumps({
                "event": "system.status",
                "payload": {
                    "llm": await coordinator.router.health(),
                    "model_name": settings.models.command_model,
                    "tools": len(coordinator.registry.tools),
                },
            }))
            while True:
                raw = await ws.receive_text()
                await _handle_client_message(coordinator, raw)
        except WebSocketDisconnect:
            manager.disconnect(ws)
        except Exception as e:  # noqa: BLE001
            log.error("ws.error", error=str(e))
            manager.disconnect(ws)

    app.state.coordinator = coordinator
    app.state.manager = manager
    return app


def _start_voice(app_state: dict, coordinator: Coordinator,
                 manager: ConnectionManager, loop) -> None:
    """Start the voice pipeline on a background thread and bridge its
    callbacks (which run off the event loop) back onto the async loop."""
    from core.voice.voice_pipeline import VoicePipeline

    def emit(event: str, payload: dict) -> None:
        asyncio.run_coroutine_threadsafe(
            manager.broadcast({"event": event, "payload": payload}), loop)

    def on_state(state: str) -> None:
        emit("voice.state_change", {"state": state})

    def on_transcript(text: str) -> None:
        emit("transcript.final", {"text": text, "duration_ms": 0})
        asyncio.run_coroutine_threadsafe(
            coordinator.handle_intent(text, app_state["mode"]), loop)

    pipeline = VoicePipeline(on_transcript=on_transcript, on_state=on_state)

    def _boot():
        try:
            pipeline.load_model()
            pipeline.start()
            log.info("voice.online", mic=pipeline.profile.device_name,
                     model=pipeline.transcriber.info)
            emit("system.status", {"mic": True,
                                   "model_name": pipeline.transcriber.info})
        except Exception as e:  # noqa: BLE001
            log.error("voice.failed", error=str(e))

    import threading
    threading.Thread(target=_boot, daemon=True, name="voice-boot").start()
    app_state["voice"] = pipeline


async def _handle_client_message(coordinator: Coordinator, raw: str) -> None:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return
    event = msg.get("event")
    payload = msg.get("payload", {})
    if event == "intent.submit":
        try:
            mode = EngineMode(payload.get("mode", "assistant"))
        except ValueError:
            mode = EngineMode.ASSISTANT
        asyncio.create_task(coordinator.handle_intent(payload.get("text", ""), mode))
    elif event == "confirmation.response":
        coordinator.confirm(payload.get("plan_id", ""), bool(payload.get("confirmed")))
    elif event == "mode.change":
        # mode is applied per-intent; nothing global to persist in phase 1
        pass
