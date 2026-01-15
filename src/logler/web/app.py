"""
FastAPI web application for Logler.
"""

import asyncio
import glob
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ..parser import LogEntry, LogParser
from ..log_reader import LogReader
from ..tracker import ThreadTracker
from ..investigate import follow_thread_hierarchy, analyze_error_flow

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


def _sanitize_glob_pattern(pattern: str) -> str:
    """Remove path traversal sequences from glob patterns."""
    import re as _re

    # Remove any ../ or ..\ sequences that could escape the root
    # Use a loop to handle multiple consecutive traversal attempts like ../../
    while ".." in pattern:
        old_pattern = pattern
        pattern = _re.sub(r"\.\.[\\/]", "", pattern)
        pattern = _re.sub(r"[\\/]\.\.", "", pattern)
        pattern = _re.sub(r"^\.\.", "", pattern)  # Leading ..
        if pattern == old_pattern:
            break  # No more changes possible
    return pattern


def _glob_within_root(pattern: str) -> List[Path]:
    """
    Run a glob pattern scoped to LOG_ROOT, returning file paths only.
    """
    if not pattern:
        return []

    # Sanitize the pattern to prevent path traversal
    pattern = _sanitize_glob_pattern(pattern)

    # Normalize relative patterns to LOG_ROOT
    raw_pattern = pattern
    if not Path(pattern).is_absolute():
        raw_pattern = str(LOG_ROOT / pattern)

    matches = glob.glob(raw_pattern, recursive=True)
    results: List[Path] = []
    seen = set()
    for match in matches:
        p = Path(match)
        try:
            p = _ensure_within_root(p)
        except HTTPException:
            continue
        if not p.is_file():
            continue
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        results.append(p)
    return sorted(results)


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
MAX_RETURNED_ENTRIES = 10000


def _normalize_level(level: str) -> str:
    return level.upper()


def _entry_matches(entry: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    if not filters:
        return True

    levels = filters.get("levels") or []
    if levels:
        normalized = {_normalize_level(lvl) for lvl in levels}
        if entry.get("level") not in normalized:
            return False

    threads = set(filters.get("threads") or [])
    if threads and entry.get("thread_id") not in threads:
        return False

    corr = (filters.get("correlation") or "").lower()
    if corr and corr not in (entry.get("correlation_id") or "").lower():
        return False

    query = (filters.get("query") or "").lower()
    if query and query not in (entry.get("message") or "").lower():
        return False

    return True


def _parse_timestamp(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _normalize_entry_dict(entry: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(entry, dict):
        return entry
    level = entry.get("level")
    if isinstance(level, str):
        entry["level"] = level.upper()
    if entry.get("service_name") is None and entry.get("service") is not None:
        entry["service_name"] = entry.get("service")
    return entry


def _track_entries(entries: List[Dict[str, Any]]):
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        tracker.track(
            LogEntry(
                line_number=entry.get("line_number") or 0,
                raw=entry.get("raw") or entry.get("message") or "",
                timestamp=_parse_timestamp(entry.get("timestamp")),
                level=str(entry.get("level") or "UNKNOWN"),
                message=entry.get("message") or entry.get("raw") or "",
                thread_id=entry.get("thread_id"),
                correlation_id=entry.get("correlation_id"),
                trace_id=entry.get("trace_id"),
                span_id=entry.get("span_id"),
                service_name=entry.get("service_name") or entry.get("service"),
                fields=entry.get("fields") or {},
            )
        )


def _rust_filter(
    files: List[str],
    filters: Dict[str, Any],
    limit: int,
    track: bool,
) -> Optional[List[Dict[str, Any]]]:
    try:
        import logler_rs  # type: ignore
    except ImportError:
        return None

    try:
        from ..cache import get_cached_investigator

        inv = get_cached_investigator(files)
    except (ImportError, AttributeError, TypeError):
        inv = logler_rs.PyInvestigator()
        inv.load_files(files)

    base_filters: Dict[str, Any] = {}
    if filters.get("levels"):
        base_filters["levels"] = [_normalize_level(lvl) for lvl in filters["levels"]]
    thread_list = list(filters.get("threads") or [])
    if filters.get("correlation"):
        base_filters["correlation_id"] = filters["correlation"]

    filter_sets: List[Dict[str, Any]] = []
    if thread_list:
        for tid in thread_list:
            f = dict(base_filters)
            f["thread_id"] = tid
            filter_sets.append(f)
    else:
        filter_sets.append(base_filters)

    entries: List[Dict[str, Any]] = []

    try:
        for rust_filters in filter_sets:
            query_dict = {
                "files": files,
                "query": filters.get("query"),
                "filters": rust_filters,
                "limit": limit,
                "context_lines": 0,
            }

            result_json = inv.search(json.dumps(query_dict))
            result = json.loads(result_json)
            for item in result.get("results", []):
                entry = item.get("entry", {}) if isinstance(item, dict) else {}
                entry.setdefault("entry_id", f"{entry.get('file','')}:{entry.get('line_number',0)}")
                entry = _normalize_entry_dict(entry)
                entries.append(entry)

        entries.sort(
            key=lambda e: (
                e.get("timestamp") or "",
                e.get("line_number") or 0,
            )
        )
        if len(entries) > limit:
            entries = entries[-limit:]
        if track:
            _track_entries(entries)
        return entries
    except (json.JSONDecodeError, KeyError, ValueError, AttributeError, RuntimeError):
        # Rust filter failed - fall back to Python implementation
        return None


def _python_filter(
    files: List[str],
    filters: Dict[str, Any],
    limit: int,
    track: bool,
) -> List[Dict[str, Any]]:
    matched: List[Dict[str, Any]] = []
    for raw_path in files:
        path = _ensure_within_root(Path(raw_path))
        if not path.exists():
            continue
        with open(path, "r") as f:
            for line_number, line in enumerate(f, start=1):
                entry = parser.parse_line(line_number, line.rstrip())
                if track:
                    tracker.track(entry)
                entry_dict = {
                    "entry_id": f"{path}:{line_number}",
                    "file": str(path),
                    "line_number": line_number,
                    "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                    "level": entry.level,
                    "message": entry.message,
                    "thread_id": entry.thread_id,
                    "correlation_id": entry.correlation_id,
                    "service_name": entry.service_name,
                    "trace_id": entry.trace_id,
                    "span_id": entry.span_id,
                }
                if _entry_matches(entry_dict, filters):
                    matched.append(entry_dict)
    return matched[-limit:]


def filter_entries(
    files: List[str],
    filters: Optional[Dict[str, Any]],
    limit: int = MAX_RETURNED_ENTRIES,
    track_threads: bool = False,
) -> List[Dict[str, Any]]:
    clean_filters = dict(filters or {})
    clean_filters["threads"] = set(clean_filters.get("threads") or [])
    entries = _rust_filter(files, clean_filters, limit, track_threads)
    if entries is None:
        entries = _python_filter(files, clean_filters, limit, track_threads)
    return [_normalize_entry_dict(e) for e in entries if isinstance(e, dict)]


def _tail_entries(path: Path, limit: int) -> Tuple[List[Dict[str, Any]], int]:
    """
    Fast tail path: avoids indexing the entire file and only parses the last N lines.
    Returns parsed entries and the total line count.
    """
    total_lines = sum(1 for _ in path.open("r", encoding="utf-8", errors="replace"))
    reader = LogReader(str(path))
    raw_lines = list(reader.tail(num_lines=limit, follow=False))
    start_line = max(1, total_lines - len(raw_lines) + 1)

    entries: List[Dict[str, Any]] = []
    for idx, raw in enumerate(raw_lines):
        line_no = start_line + idx
        entry = parser.parse_line(line_no, raw.rstrip())
        entries.append(
            {
                "entry_id": f"{path}:{line_no}",
                "file": str(path),
                "line_number": line_no,
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                "level": entry.level,
                "message": entry.message,
                "thread_id": entry.thread_id,
                "correlation_id": entry.correlation_id,
                "service_name": entry.service_name,
                "trace_id": entry.trace_id,
                "span_id": entry.span_id,
            }
        )

    return entries, total_lines


def sample_entries(
    entries: List[Dict[str, Any]], per_level: Optional[int], per_thread: Optional[int]
) -> List[Dict[str, Any]]:
    if not entries:
        return entries

    sampled = []

    if per_level:
        by_level: Dict[str, List[Dict[str, Any]]] = {}
        for e in entries:
            lvl = e.get("level", "INFO")
            by_level.setdefault(lvl, []).append(e)
        for level_entries in by_level.values():
            sampled.extend(level_entries[-per_level:])

    if per_thread:
        by_thread: Dict[str, List[Dict[str, Any]]] = {}
        for e in entries:
            tid = e.get("thread_id")
            if not tid:
                continue
            by_thread.setdefault(tid, []).append(e)
        for thread_entries in by_thread.values():
            sampled.extend(thread_entries[-per_thread:])

    # If neither sampling applied, return original
    if not per_level and not per_thread:
        return entries

    # Deduplicate by entry_id
    seen = set()
    deduped = []
    for e in sampled:
        eid = e.get("entry_id")
        if eid and eid in seen:
            continue
        if eid:
            seen.add(eid)
        deduped.append(e)
    return deduped


class FileRequest(BaseModel):
    path: str
    filters: Optional[Dict[str, Any]] = None
    limit: Optional[int] = None
    quick: Optional[bool] = None


class FilesRequest(BaseModel):
    paths: List[str]
    filters: Optional[Dict[str, Any]] = None
    limit: Optional[int] = None


class FilterRequest(BaseModel):
    paths: List[str]
    filters: Optional[Dict[str, Any]] = None
    limit: Optional[int] = None
    sample_per_level: Optional[int] = None
    sample_per_thread: Optional[int] = None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main page."""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "active_files": active_files,
        },
    )


@app.get("/api/files/browse")
async def browse_files(directory: str = "."):
    """Browse files in a directory."""
    dir_path = _ensure_within_root(Path(directory))

    if not dir_path.exists() or not dir_path.is_dir():
        return {"error": "Invalid directory", "files": []}

    files = []
    directories = []
    try:
        for item in sorted(dir_path.iterdir()):
            if item.is_dir() and _ensure_within_root(item):
                directories.append(
                    {
                        "name": item.name,
                        "path": str(item.absolute()),
                    }
                )
            if item.is_file() and (item.suffix in [".log", ".txt"] or "log" in item.name.lower()):
                files.append(
                    {
                        "name": item.name,
                        "path": str(item.absolute()),
                        "size": item.stat().st_size,
                    }
                )
    except PermissionError:
        return {"error": "Permission denied", "files": []}

    parent_dir = dir_path.parent if dir_path.parent != dir_path else None
    if parent_dir and not (parent_dir == LOG_ROOT or LOG_ROOT in parent_dir.parents):
        parent_dir = None

    return {
        "current_dir": str(dir_path),
        "parent_dir": str(parent_dir) if parent_dir else None,
        "files": files,
        "directories": directories,
        "log_root": str(LOG_ROOT),
    }


@app.get("/api/files/glob")
async def glob_files(pattern: str = "**/*.log", base_dir: str = ".", limit: int = 200):
    """Search for files by glob pattern within LOG_ROOT. When base_dir is provided, pattern is resolved relative to it."""
    try:
        base = _ensure_within_root(Path(base_dir))
    except HTTPException:
        base = LOG_ROOT

    raw_pattern = pattern
    if not Path(pattern).is_absolute():
        raw_pattern = str((base / pattern))

    matches = _glob_within_root(raw_pattern)
    files = []
    for p in matches[:limit]:
        try:
            stat = p.stat()
            files.append(
                {
                    "name": p.name,
                    "path": str(p),
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                }
            )
        except OSError:
            continue
    return {
        "pattern": pattern,
        "count": len(matches),
        "files": files,
        "truncated": len(matches) > limit,
    }


@app.post("/api/files/open")
async def open_file(request: FileRequest):
    """Open a log file."""
    global tracker
    file_path = _ensure_within_root(Path(request.path))

    if not file_path.exists():
        return {"error": "File not found"}

    quick_mode = request.quick is not False  # default to quick unless explicitly disabled
    if quick_mode:
        tracker = ThreadTracker()
        quick_limit = min(request.limit or 1000, MAX_RETURNED_ENTRIES)
        entries, total_lines = _tail_entries(file_path, quick_limit)
        tracker = ThreadTracker()
        _track_entries(entries)
        return {
            "file_path": str(file_path),
            "entries": entries,
            "total": total_lines,
            "partial": True,
        }

    # Reset tracker to avoid double-counting between file loads
    tracker = ThreadTracker()

    if str(file_path) not in active_files:
        active_files.append(str(file_path))

    entries = filter_entries(
        [str(file_path)],
        request.filters,
        limit=request.limit or MAX_RETURNED_ENTRIES,
        track_threads=True,
    )
    total_count = len(entries)
    entries = entries[-1000:]

    return {
        "file_path": str(file_path),
        "entries": entries,
        "total": total_count,
    }


@app.post("/api/files/open_many")
async def open_many(request: FilesRequest):
    """Open multiple log files and interleave entries."""
    global tracker
    tracker = ThreadTracker()
    valid_files = []
    for raw_path in request.paths:
        try:
            file_path = _ensure_within_root(Path(raw_path))
        except HTTPException:
            continue
        if file_path.exists():
            valid_files.append(str(file_path))

    entries = filter_entries(
        valid_files,
        request.filters,
        limit=request.limit or MAX_RETURNED_ENTRIES,
        track_threads=True,
    )

    # Sort by timestamp if available
    entries.sort(key=lambda e: e["timestamp"] or "")

    file_counts: Dict[str, int] = {}
    file_meta: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        file = entry.get("file")
        if file:
            file_counts[file] = file_counts.get(file, 0) + 1
            ts = entry.get("timestamp")
            meta = file_meta.setdefault(file, {"first": None, "last": None})
            if ts:
                if meta["first"] is None or ts < meta["first"]:
                    meta["first"] = ts
                if meta["last"] is None or ts > meta["last"]:
                    meta["last"] = ts

    for lf in valid_files:
        if lf not in active_files:
            active_files.append(lf)

    return {
        "files": valid_files,
        "entries": entries,
        "total": len(entries),
        "file_counts": file_counts,
        "file_meta": [
            {
                "file": f,
                "count": file_counts.get(f, 0),
                "first": meta.get("first"),
                "last": meta.get("last"),
            }
            for f, meta in file_meta.items()
        ],
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


@app.post("/api/files/filter")
async def filter_files(request: FilterRequest):
    """Filter entries on the server to reduce payload size."""
    files = []
    for raw in request.paths:
        try:
            files.append(str(_ensure_within_root(Path(raw))))
        except HTTPException:
            continue
    entries = filter_entries(files, request.filters, limit=request.limit or MAX_RETURNED_ENTRIES)
    entries = sample_entries(entries, request.sample_per_level, request.sample_per_thread)
    return {"entries": entries, "total": len(entries)}


@app.post("/api/files/sample")
async def sample_files(request: FilterRequest):
    """Filter entries and return samples by level/thread to lighten payloads."""
    files = []
    for raw in request.paths:
        try:
            files.append(str(_ensure_within_root(Path(raw))))
        except HTTPException:
            continue
    entries = filter_entries(files, request.filters, limit=request.limit or MAX_RETURNED_ENTRIES)
    sampled = sample_entries(entries, request.sample_per_level, request.sample_per_thread)
    return {"entries": sampled, "total": len(entries), "sampled": len(sampled)}


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
    current_filters: Dict[str, Any] = {}
    drop_count = 0

    try:
        while True:
            # Receive messages (for file selection, etc.)
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("action") == "follow":
                file_path = message.get("file_path")
                current_filters = message.get("filters") or {}
                drop_count = 0
                await follow_file(websocket, file_path, current_filters, drop_count)

    except WebSocketDisconnect:
        pass  # Normal disconnect
    finally:
        if websocket in websocket_clients:
            websocket_clients.remove(websocket)


async def follow_file(
    websocket: WebSocket, file_path: str, filters: Dict[str, Any], drop_count: int
):
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
    with open(path, "r") as f:
        f.seek(0, 2)
        position = f.tell()
    with open(path, "r") as f:
        line_number = sum(1 for _ in f)

    # Follow file
    try:
        while True:
            with open(path, "r") as f:
                current_size = path.stat().st_size
                if current_size < position:
                    # File was truncated/rotated; restart from beginning
                    position = 0
                    line_number = 0
                f.seek(position)
                new_lines = f.readlines()
                position = f.tell()

                for line in new_lines:
                    line_number += 1
                    entry = parser.parse_line(line_number, line.rstrip())
                    tracker.track(entry)

                    entry_dict = {
                        "entry_id": f"{path}:{line_number}",
                        "file": str(path),
                        "line_number": entry.line_number,
                        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                        "level": entry.level,
                        "message": entry.message,
                        "thread_id": entry.thread_id,
                        "correlation_id": entry.correlation_id,
                    }

                    if not _entry_matches(entry_dict, filters):
                        continue

                    try:
                        await asyncio.wait_for(
                            websocket.send_json({"type": "log_entry", "entry": entry_dict}),
                            timeout=0.25,
                        )
                    except asyncio.TimeoutError:
                        drop_count += 1
                        # Occasionally inform client of drops to avoid flooding
                        if drop_count % 50 == 0:
                            try:
                                await websocket.send_json({"type": "dropped", "count": drop_count})
                            except Exception:
                                pass
                    except Exception:
                        return

            await asyncio.sleep(0.1)

    except Exception as e:
        await websocket.send_json({"error": str(e)})


class HierarchyRequest(BaseModel):
    paths: List[str]
    root_identifier: str
    max_depth: Optional[int] = None
    min_confidence: float = 0.0
    use_naming_patterns: bool = True
    use_temporal_inference: bool = True


@app.post("/api/hierarchy")
async def get_hierarchy(request: HierarchyRequest):
    """
    Build and return thread/span hierarchy for visualization.

    Returns a hierarchical tree structure with:
    - Parent-child relationships
    - Duration and timing information
    - Error counts and propagation
    - Bottleneck detection
    """
    files = []
    for raw in request.paths:
        try:
            files.append(str(_ensure_within_root(Path(raw))))
        except HTTPException:
            continue

    if not files:
        return {"error": "No valid files provided", "hierarchy": None}

    try:
        hierarchy = follow_thread_hierarchy(
            files=files,
            root_identifier=request.root_identifier,
            max_depth=request.max_depth,
            use_naming_patterns=request.use_naming_patterns,
            use_temporal_inference=request.use_temporal_inference,
            min_confidence=request.min_confidence,
        )

        # Also analyze error flow
        error_analysis = analyze_error_flow(hierarchy)

        return {
            "hierarchy": hierarchy,
            "error_analysis": error_analysis,
        }
    except Exception as e:
        return {"error": str(e), "hierarchy": None}


async def run_server(host: str, port: int, initial_files: List[str]):
    """Run the FastAPI server."""
    import uvicorn

    global active_files
    active_files = initial_files

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()
