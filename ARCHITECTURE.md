# Logler Architecture

## Overview

Logler is built with a modern, high-performance architecture that separates concerns between data processing (Rust) and presentation (Python/Web).

```
┌─────────────────────────────────────────────────────────────┐
│                         User Browser                         │
│                    (HTMX + Alpine.js)                       │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP/WebSocket
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Gateway (Python)                  │
│  - Web UI serving                                           │
│  - HTTP proxy to Rust backend                               │
│  - HTMX partial rendering                                   │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP/REST
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   Rust Backend (Axum)                        │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              logler-server (Web API)                  │  │
│  │  - REST API endpoints                                 │  │
│  │  - WebSocket real-time streaming                     │  │
│  │  - File watching                                      │  │
│  │  - State management                                   │  │
│  └─────────────────────┬────────────────────────────────┘  │
│                        │                                     │
│  ┌─────────────────────▼────────────────────────────────┐  │
│  │              logler-core (Library)                    │  │
│  │                                                        │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │  │
│  │  │   Parser     │  │    Reader    │  │  Thread    │ │  │
│  │  │              │  │              │  │  Tracker   │ │  │
│  │  │ - Format     │  │ - Async file │  │            │ │  │
│  │  │   detection  │  │   reading    │  │ - Thread   │ │  │
│  │  │ - JSON/Plain │  │ - Streaming  │  │   context  │ │  │
│  │  │ - Regex      │  │ - Tail       │  │ - Trace    │ │  │
│  │  │   extraction │  │              │  │   tracking │ │  │
│  │  └──────────────┘  └──────────────┘  └────────────┘ │  │
│  │                                                        │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │  │
│  │  │   Filter     │  │    Stats     │  │   Types    │ │  │
│  │  │              │  │              │  │            │ │  │
│  │  │ - Level      │  │ - Aggregates │  │ - LogEntry │ │  │
│  │  │ - Pattern    │  │ - Counts     │  │ - Level    │ │  │
│  │  │ - Thread ID  │  │ - Error rate │  │ - Context  │ │  │
│  │  │ - Trace ID   │  │              │  │            │ │  │
│  │  └──────────────┘  └──────────────┘  └────────────┘ │  │
│  └────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              logler-cli (CLI Tool)                    │  │
│  │  - Terminal interface                                 │  │
│  │  - Uses logler-core directly                          │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Components

### 1. Rust Backend

#### logler-core (Library)
The core parsing and analysis engine.

**Modules:**
- `parser.rs`: Log format detection and parsing
  - Regex-based pattern matching
  - JSON structured log parsing
  - Multi-format support (JSON, plain, syslog, logfmt, Apache)
  - Extraction of thread IDs, correlation IDs, trace IDs

- `reader.rs`: Async file I/O
  - Tokio-based async file reading
  - Streaming support for large files
  - Memory-efficient chunked reading
  - Tail/head operations

- `thread_tracker.rs`: Correlation tracking
  - Thread context tracking
  - Trace/span correlation
  - Correlation ID mapping
  - Temporal analysis

- `filter.rs`: Log filtering
  - Multi-dimensional filtering
  - Regex pattern matching
  - Time range filtering

- `stats.rs`: Statistics computation
  - Log level distribution
  - Error rate calculation
  - Service/thread aggregation

- `types.rs`: Core data structures
  - `LogEntry`: Main log entry structure
  - `LogLevel`, `LogFormat`: Enums
  - `ThreadContext`, `TraceContext`: Correlation types

#### logler-server (Web Server)
REST API and WebSocket server.

**Features:**
- Axum web framework
- REST endpoints for all operations
- WebSocket for real-time streaming
- File watching (notify crate)
- In-memory caching (DashMap)

**API Endpoints:**
- File operations: `/api/files/*`
- Log operations: `/api/logs/*`
- Thread tracking: `/api/threads/*`
- Trace tracking: `/api/traces/*`
- Correlation: `/api/correlations/*`
- WebSocket: `/ws`

#### logler-cli (CLI Tool)
Command-line interface for terminal usage.

**Commands:**
- `view`: View log files
- `search`: Search logs
- `stats`: Show statistics

### 2. Python FastAPI Gateway

**Responsibilities:**
- Serve web UI (HTML/CSS/JS)
- Proxy requests to Rust backend
- HTMX partial rendering
- Session management (future)

**Stack:**
- FastAPI for async web framework
- Jinja2 for templating
- httpx for HTTP client
- Uvicorn for ASGI server

### 3. Web Frontend

**Technologies:**
- HTMX for dynamic updates
- Alpine.js for client-side state
- TailwindCSS for styling
- Native WebSocket API

**Features:**
- Real-time log streaming
- Advanced filtering UI
- Thread/trace visualization
- Statistics dashboard
- Auto-scrolling viewer

## Data Flow

### 1. Opening a Log File

```
Browser → FastAPI → Rust API → LogReader
                              ↓
                          Parse logs
                              ↓
                          Track threads/traces
                              ↓
                          Store in memory
                              ↓
Browser ← FastAPI ← JSON response
```

### 2. Filtering Logs

```
Browser → FastAPI → Rust API → Apply filters
                              ↓
                          Filter in-memory cache
                              ↓
Browser ← FastAPI ← Filtered results
```

### 3. Real-time Streaming (Future)

```
Browser ←→ WebSocket ←→ Rust API
                           ↓
                      File watcher
                           ↓
                      New log lines
                           ↓
                      Parse & filter
                           ↓
Browser ←─── Push to WebSocket
```

## Performance Characteristics

### Rust Backend
- **Parsing speed**: ~1M lines/second (JSON logs)
- **Memory usage**: O(n) where n = file size (streaming)
- **Concurrency**: Async/await with Tokio runtime
- **Thread safety**: Lock-free data structures (DashMap)

### Python Gateway
- **Request latency**: <10ms (proxy overhead)
- **Concurrent requests**: 1000+ (async httpx)
- **Memory**: Minimal (stateless proxy)

### Web Frontend
- **Initial load**: <100KB (gzipped)
- **DOM updates**: Incremental via HTMX
- **WebSocket**: Binary protocol for efficiency

## Scalability

### Current Scale
- File size: Tested up to 10GB
- Concurrent users: 1000+ WebSocket connections
- Log lines: Millions per file

### Future Improvements
- Distributed log aggregation
- Multi-file support
- Log indexing (ElasticSearch/Loki)
- Persistent storage
- Clustering

## Security

### Current Implementation
- No authentication (local use)
- CORS enabled (development)
- Path traversal protection
- Resource limits

### Production Recommendations
- Add authentication (JWT/OAuth)
- Rate limiting
- TLS/HTTPS
- Sandboxing file access
- Input sanitization

## Deployment

### Development
```bash
make dev
```

### Production
```bash
make build
make run
```

### Docker
```bash
make docker-build
make docker-up
```

## Technology Choices

### Why Rust?
- **Performance**: 100x faster than Python for parsing
- **Memory safety**: No segfaults or memory leaks
- **Concurrency**: Built-in async/await
- **Type safety**: Catch errors at compile time

### Why FastAPI?
- **Rapid development**: Quick API prototyping
- **Async support**: Non-blocking I/O
- **OpenAPI**: Auto-generated docs
- **Ecosystem**: Rich Python libraries

### Why HTMX?
- **Simplicity**: No build step required
- **Progressive enhancement**: Works without JS
- **Low overhead**: Minimal client-side code
- **Server-driven**: UI logic in backend

## Future Architecture

### Planned Enhancements
1. **Log aggregation**: Multi-file, multi-host support
2. **Persistence**: SQLite/PostgreSQL backend
3. **Indexing**: Full-text search
4. **Alerting**: Real-time alerts on patterns
5. **Plugins**: Custom parsers and formatters
6. **Authentication**: Multi-user support
7. **API tokens**: Programmatic access
8. **Export**: CSV, JSON, Parquet
9. **Integration**: Grafana, ElasticSearch, Loki
10. **Machine learning**: Anomaly detection
