from __future__ import annotations

import asyncio
import contextlib
import os
import pty
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from web_server.game_api import WebApiError, WebGameManager


REPO_ROOT = Path(__file__).resolve().parents[1]
GAME_SCRIPT = REPO_ROOT / "quiet_relay_vertical_slice_datadriven.py"
WEB_ROOT = REPO_ROOT / "web"
WEB_INDEX = WEB_ROOT / "index.html"
WEB_STATIC_ROOT = REPO_ROOT / "web_static"
WEB_STATIC_ASSETS = WEB_STATIC_ROOT / "assets"
TERMINAL_INDEX = WEB_STATIC_ROOT / "index.html"
SESSION_ROOT = REPO_ROOT / "runtime" / "sessions"

MAX_SESSIONS = int(os.environ.get("QUIET_RELAY_MAX_SESSIONS", "8"))
IDLE_TIMEOUT_SECONDS = int(os.environ.get("QUIET_RELAY_IDLE_TIMEOUT_SECONDS", "900"))
PROCESS_SHUTDOWN_GRACE_SECONDS = 2.0

app = FastAPI(title="Quiet Relay Web")
game_manager = WebGameManager(SESSION_ROOT)

app.mount("/assets", StaticFiles(directory=WEB_STATIC_ASSETS, html=False), name="assets")

_active_sessions: set[str] = set()
_session_lock = asyncio.Lock()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_INDEX)


@app.get("/terminal")
async def terminal_index() -> FileResponse:
    return FileResponse(TERMINAL_INDEX)


@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"ok": True})


def _json_error(error: WebApiError) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(error)}, status_code=error.status_code)


@app.post("/api/sessions")
async def create_session(payload: dict[str, Any] | None = None) -> JSONResponse:
    payload = payload or {}
    try:
        response = game_manager.create_session(
            seed=int(payload.get("seed", 2026)),
            district_id=str(payload.get("district_id", "district_03_rain_toll_corridor")),
        )
    except WebApiError as error:
        return _json_error(error)
    return JSONResponse(response)


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> JSONResponse:
    try:
        session = game_manager.get_session(session_id)
        return JSONResponse(game_manager.response(session, []))
    except WebApiError as error:
        return _json_error(error)


@app.post("/api/sessions/{session_id}/actions")
async def post_action(session_id: str, payload: dict[str, Any] | None = None) -> JSONResponse:
    try:
        return JSONResponse(game_manager.handle_action(session_id, payload or {}))
    except WebApiError as error:
        return _json_error(error)


@app.post("/api/sessions/{session_id}/save")
async def save_session(session_id: str, payload: dict[str, Any] | None = None) -> JSONResponse:
    payload = payload or {}
    try:
        client_state = payload.get("client_state")
        return JSONResponse(game_manager.save_session(session_id, client_state if isinstance(client_state, dict) else None))
    except WebApiError as error:
        return _json_error(error)


@app.post("/api/sessions/{session_id}/load")
async def load_session(session_id: str) -> JSONResponse:
    try:
        return JSONResponse(game_manager.load_session(session_id))
    except WebApiError as error:
        return _json_error(error)


@app.get("/api/saves")
async def list_saves() -> JSONResponse:
    return JSONResponse(game_manager.list_saves())


@app.get("/{asset_path:path}", response_model=None)
async def web_asset(asset_path: str) -> FileResponse | JSONResponse:
    if not asset_path:
        return FileResponse(WEB_INDEX)
    target = (WEB_ROOT / asset_path).resolve()
    try:
        target.relative_to(WEB_ROOT)
    except ValueError:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    if not target.is_file():
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return FileResponse(target)


async def _try_register_session(session_id: str) -> bool:
    async with _session_lock:
        if len(_active_sessions) >= MAX_SESSIONS:
            return False
        _active_sessions.add(session_id)
        return True


async def _unregister_session(session_id: str) -> None:
    async with _session_lock:
        _active_sessions.discard(session_id)


async def _read_pty(master_fd: int, size: int = 4096) -> bytes:
    loop = asyncio.get_running_loop()
    ready = loop.create_future()

    def mark_ready() -> None:
        if not ready.done():
            ready.set_result(None)

    loop.add_reader(master_fd, mark_ready)
    try:
        await ready
        return os.read(master_fd, size)
    finally:
        loop.remove_reader(master_fd)


def _build_command(save_path: Path, log_dir: Path) -> list[str]:
    return [
        sys.executable,
        str(GAME_SCRIPT),
        "--save-file",
        str(save_path),
        "--log-dir",
        str(log_dir),
    ]


def _spawn_game(session_dir: Path) -> tuple[subprocess.Popen[bytes], int]:
    log_dir = session_dir / "logs"
    save_path = session_dir / "save.json"
    log_dir.mkdir(parents=True, exist_ok=True)

    master_fd, slave_fd = pty.openpty()
    env = os.environ.copy()
    env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "TERM": "xterm-256color",
        }
    )

    try:
        process = subprocess.Popen(
            _build_command(save_path, log_dir),
            cwd=REPO_ROOT,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
            start_new_session=True,
        )
    finally:
        os.close(slave_fd)

    return process, master_fd


async def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return

    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)

    try:
        await asyncio.to_thread(process.wait, PROCESS_SHUTDOWN_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass

    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        await asyncio.to_thread(process.wait, PROCESS_SHUTDOWN_GRACE_SECONDS)


async def _relay_process_output(websocket: WebSocket, master_fd: int, process: subprocess.Popen[bytes]) -> None:
    while process.poll() is None:
        try:
            data = await _read_pty(master_fd)
        except OSError:
            break
        if not data:
            break
        await websocket.send_text(data.decode("utf-8", errors="replace"))

    await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)


async def _relay_browser_input(websocket: WebSocket, master_fd: int, last_input_at: list[float]) -> None:
    while True:
        message = await websocket.receive_text()
        last_input_at[0] = time.monotonic()
        os.write(master_fd, message.encode("utf-8"))


async def _enforce_idle_timeout(websocket: WebSocket, last_input_at: list[float]) -> None:
    while True:
        await asyncio.sleep(min(IDLE_TIMEOUT_SECONDS, 30))
        idle_for = time.monotonic() - last_input_at[0]
        if idle_for >= IDLE_TIMEOUT_SECONDS:
            await websocket.send_text(
                f"\r\n[Quiet Relay] Session closed after {IDLE_TIMEOUT_SECONDS} seconds of inactivity.\r\n"
            )
            await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
            return


@app.websocket("/ws/play")
async def play(websocket: WebSocket) -> None:
    await websocket.accept()

    session_id = uuid.uuid4().hex
    if not await _try_register_session(session_id):
        await websocket.send_text("[Quiet Relay] Server is at the session limit. Try again later.\r\n")
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
        return

    session_dir = SESSION_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    process: subprocess.Popen[bytes] | None = None
    master_fd: int | None = None
    tasks: set[asyncio.Task[None]] = set()
    try:
        process, master_fd = _spawn_game(session_dir)
        await websocket.send_text(
            f"[Quiet Relay] Session {session_id} started. Save: runtime/sessions/{session_id}/save.json\r\n"
        )

        last_input_at = [time.monotonic()]
        tasks = {
            asyncio.create_task(_relay_process_output(websocket, master_fd, process)),
            asyncio.create_task(_relay_browser_input(websocket, master_fd, last_input_at)),
            asyncio.create_task(_enforce_idle_timeout(websocket, last_input_at)),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            with contextlib.suppress(WebSocketDisconnect):
                task.result()
    except WebSocketDisconnect:
        pass
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if master_fd is not None:
            with contextlib.suppress(OSError):
                os.close(master_fd)
        if process is not None:
            await _terminate_process(process)
        await _unregister_session(session_id)
