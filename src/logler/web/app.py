"""
FastAPI web application for Logler.
"""

import asyncio
import json
import os
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import aiofiles

from ..parser import LogParser
from ..tracker import ThreadTracker

# Get package directory
PACKAGE_DIR = Path(__file__).parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

# Create FastAPI app
LOG_ROOT = Path(os.environ.get("LOGLER_ROOT", ".")).expanduser().resolve()


def _ensure_within_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == LOG_ROOT or LOG_ROOT in resolved.parents:
        return resolved
    raise HTTPException(status_code=403, detail="Requested path is outside the configured log root")


app = FastAPI(
    title="Logler",
    description="Beautiful log viewer",
    summary="Legacy web UI (Python FastAPI) with log root restrictions",
)

# Mount static files if directory exists
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Setup templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Global state
parser = LogParser()
tracker = ThreadTracker()
active_files: List[str] = []
websocket_clients: List[WebSocket] = []


class FileRequest(BaseModel):
    path: str


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main page."""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "active_files": active_files,
        }
    )


@app.get("/api/files/browse")
async def browse_files(directory: str = "."):
    """Browse files in a directory."""
    dir_path = _ensure_within_root(Path(directory))

    if not dir_path.exists() or not dir_path.is_dir():
        return {"error": "Invalid directory", "files": []}

    files = []
    try:
        for item in sorted(dir_path.iterdir()):
            if item.is_file() and (item.suffix in [".log", ".txt"] or "log" in item.name.lower()):
                files.append({
                    "name": item.name,
                    "path": str(item.absolute()),
                    "size": item.stat().st_size,
                })
    except PermissionError:
        return {"error": "Permission denied", "files": []}

    parent_dir = dir_path.parent if dir_path.parent != dir_path else None
    if parent_dir and not (parent_dir == LOG_ROOT or LOG_ROOT in parent_dir.parents):
        parent_dir = None

    return {
        "current_dir": str(dir_path),
        "parent_dir": str(parent_dir) if parent_dir else None,
        "files": files,
    }


@app.post("/api/files/open")
async def open_file(request: FileRequest):
    """Open a log file."""
    file_path = _ensure_within_root(Path(request.path))

    if not file_path.exists():
        return {"error": "File not found"}

    if str(file_path) not in active_files:
        active_files.append(str(file_path))

    # Parse file
    entries = []
    async with aiofiles.open(file_path, 'r') as f:
        line_number = 0
        async for line in f:
            line_number += 1
            entry = parser.parse_line(line_number, line.rstrip())
            tracker.track(entry)
            entries.append({
                "line_number": entry.line_number,
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                "level": entry.level,
                "message": entry.message,
                "thread_id": entry.thread_id,
                "correlation_id": entry.correlation_id,
                "trace_id": entry.trace_id,
                "span_id": entry.span_id,
            })

    return {
        "file_path": str(file_path),
        "entries": entries[-1000:],  # Last 1000 entries
        "total": len(entries),
    }


@app.get("/api/threads")
async def get_threads():
    """Get all tracked threads."""
    threads = tracker.get_all_threads()
    # Convert datetime to ISO format
    for thread in threads:
        if thread.get("first_seen"):
            thread["first_seen"] = thread["first_seen"].isoformat()
        if thread.get("last_seen"):
            thread["last_seen"] = thread["last_seen"].isoformat()
    return threads


@app.get("/api/traces")
async def get_traces():
    """Get all tracked traces."""
    traces = tracker.get_all_traces()
    for trace in traces:
        if trace.get("start_time"):
            trace["start_time"] = trace["start_time"].isoformat()
        if trace.get("end_time"):
            trace["end_time"] = trace["end_time"].isoformat()
        for span in trace.get("spans", []):
            if span.get("timestamp"):
                span["timestamp"] = span["timestamp"].isoformat()
    return traces


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await websocket.accept()
    websocket_clients.append(websocket)

    try:
        while True:
            # Receive messages (for file selection, etc.)
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("action") == "follow":
                file_path = message.get("file_path")
                await follow_file(websocket, file_path)

    except WebSocketDisconnect:
        websocket_clients.remove(websocket)


async def follow_file(websocket: WebSocket, file_path: str):
    """Follow a log file and send updates via WebSocket."""
    try:
        path = _ensure_within_root(Path(file_path))
    except HTTPException as exc:
        await websocket.send_json({"error": exc.detail})
        return

    if not path.exists():
        await websocket.send_json({"error": "File not found"})
        return

    # Get initial position (end of file)
    with open(path, 'r') as f:
        f.seek(0, 2)
        position = f.tell()
        line_number = sum(1 for _ in open(path))

    # Follow file
    try:
        while True:
            with open(path, 'r') as f:
                f.seek(position)
                new_lines = f.readlines()
                position = f.tell()

                for line in new_lines:
                    line_number += 1
                    entry = parser.parse_line(line_number, line.rstrip())
                    tracker.track(entry)

                    await websocket.send_json({
                        "type": "log_entry",
                        "entry": {
                            "line_number": entry.line_number,
                            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                            "level": entry.level,
                            "message": entry.message,
                            "thread_id": entry.thread_id,
                            "correlation_id": entry.correlation_id,
                        }
                    })

            await asyncio.sleep(0.1)

    except Exception as e:
        await websocket.send_json({"error": str(e)})


async def run_server(host: str, port: int, initial_files: List[str]):
    """Run the FastAPI server."""
    import uvicorn

    global active_files
    active_files = initial_files

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()
