from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import httpx
from typing import Optional, List
import os

app = FastAPI(title="Logler Web UI")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="templates")

# Rust backend URL
RUST_BACKEND = os.getenv("RUST_BACKEND_URL", "http://localhost:3000")


class OpenFileRequest(BaseModel):
    path: str


class SearchRequest(BaseModel):
    file_id: str
    query: str
    limit: Optional[int] = 100


class FilterRequest(BaseModel):
    file_id: str
    levels: Optional[List[str]] = None
    pattern: Optional[str] = None
    thread_id: Optional[str] = None
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main application page"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health")
async def health():
    """Health check"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{RUST_BACKEND}/health", timeout=5.0)
            backend_status = "healthy" if response.status_code == 200 else "unhealthy"
        except Exception:
            backend_status = "unreachable"

    return {
        "status": "healthy",
        "backend": backend_status
    }


@app.post("/api/files/open")
async def open_file(req: OpenFileRequest):
    """Open a log file via Rust backend"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{RUST_BACKEND}/api/files/open",
                json={"path": req.path},
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/logs")
async def get_logs(file_id: str, offset: int = 0, limit: int = 100):
    """Get logs from opened file"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{RUST_BACKEND}/api/logs",
                params={"file_id": file_id, "offset": offset, "limit": limit},
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/logs/search")
async def search_logs(req: SearchRequest):
    """Search logs"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{RUST_BACKEND}/api/logs/search",
                json=req.dict(),
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/logs/filter")
async def filter_logs(req: FilterRequest):
    """Filter logs"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{RUST_BACKEND}/api/logs/filter",
                json=req.dict(exclude_none=True),
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
async def get_stats(file_id: str):
    """Get statistics"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{RUST_BACKEND}/api/logs/stats",
                params={"file_id": file_id},
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/threads")
async def get_threads():
    """Get all thread contexts"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{RUST_BACKEND}/api/threads",
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/traces")
async def get_traces():
    """Get all trace contexts"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{RUST_BACKEND}/api/traces",
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/correlations")
async def get_correlations():
    """Get all correlation IDs"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{RUST_BACKEND}/api/correlations",
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=str(e))


# HTMX partial endpoints for dynamic updates
@app.get("/partials/log-entry/{entry_id}", response_class=HTMLResponse)
async def log_entry_partial(entry_id: str, request: Request):
    """Return a single log entry as HTML"""
    # This would fetch the entry and return formatted HTML
    return templates.TemplateResponse(
        "partials/log_entry.html",
        {"request": request, "entry_id": entry_id}
    )


@app.get("/partials/thread-view/{thread_id}", response_class=HTMLResponse)
async def thread_view_partial(thread_id: str, request: Request):
    """Return thread view as HTML"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{RUST_BACKEND}/api/threads/{thread_id}",
                timeout=30.0
            )
            response.raise_for_status()
            thread_data = response.json()

            return templates.TemplateResponse(
                "partials/thread_view.html",
                {"request": request, "thread": thread_data}
            )
        except httpx.HTTPError:
            raise HTTPException(status_code=404, detail="Thread not found")


@app.get("/partials/trace-view/{trace_id}", response_class=HTMLResponse)
async def trace_view_partial(trace_id: str, request: Request):
    """Return trace view as HTML"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{RUST_BACKEND}/api/traces/{trace_id}",
                timeout=30.0
            )
            response.raise_for_status()
            trace_data = response.json()

            return templates.TemplateResponse(
                "partials/trace_view.html",
                {"request": request, "trace": trace_data}
            )
        except httpx.HTTPError:
            raise HTTPException(status_code=404, detail="Trace not found")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
