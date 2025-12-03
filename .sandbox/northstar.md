Logler — North Star & Mini-Whitepaper

North Star (what Logler is)

Logler is a local-first, ultra-fast, beautiful log explorer.
It gives developers a zero-infrastructure way to tail, filter, search, compare, and trace logs in real time—without ELK/Kibana, servers, or cloud lock-in. You point it at one or more files; it streams instantly, indexes on the fly, and presents a clean, responsive UI that “just opens” by default.

Why now: most tools are either a plain tail -f or a heavyweight stack. Logler fills the gap: production-grade speed and UX, but portable and private.


---

Core Value (what it does best)

Live tail + instant filters (regex + color rules), with rotation handling.

Historical search over big files via DuckDB (substring or regex).

Side-by-side multi-log view (experimental): synchronized by timestamp or arrival.

Threaded view (experimental): show all lines across logs sharing a correlation/thread ID.

One-command UX: CLI launches backend and UI automatically; --no-ui for headless.

Local-first privacy: runs on your machine; no telemetry by default.


---

Target Users

Backend / platform / SRE engineers who want fast, private analysis of local or remote-mounted logs.

App developers reproducing issues on Windows/macOS/Linux without spinning up ELK.

Power users who need multi-file correlation and “follow this request/thread” workflows.


---

Architecture (how it works)

Rust tail engine (PyO3)

Async tailer (Tokio + file-watch) with rotation awareness and low latency.

Emits structured TailEvent records (timestamp, raw line; parsed fields expanding over time).

Windows-friendly; tested with typical MSVC toolchain.

Python service (FastAPI)

WebSocket streams:

/ws/log single-log

/ws/multilog merged multi-log (experimental)

Search & indexing (DuckDB):

/search (substring/regex over history)

/threads (discover IDs) & /search/thread (correlated timeline)

CLI (Typer): tail, multitail (experimental), serve, build-ui, plus planned version/info.

UI launches by default; --no-ui to suppress, --ui-port override.

Frontend (React + Vite + Tailwind)

Components: LogList (virtualized), FilterBar, SearchBar, MultiLogViewer (split view), ThreadView (experimental).

Design system: Unified Design System (Wada Sanzo / Goshuin-inspired tokens, accessible contrast, focus states).

Dev mode: Vite hot-reload.
Prod mode: built frontend/dist served as FastAPI static files.


---

Performance & Quality

Latency target: sub-50 ms from file append to UI update (typical).

Scale target: multi-hundred-MB to GB-scale logs; stress tests cover 100K–1M lines.

Robustness: rotation, long lines, malformed lines, mixed encodings (evolving).

Test suite:

Rust: unit/integration + stress (append/rotate/concurrency).

Python: pytest for REST/WS + search/threads; stress markers.

Frontend: Vitest unit/snapshots + Playwright E2E (WebSocket stubs, split-view, filters).

Windows support: fixes for npm.cmd, MSVC linker, PATH; setup with uv + maturin.


---

Developer Experience

Setup: uv venv + maturin develop; one-shot dev_setup.sh.

CLI UX: defaults to opening the UI; headless via --no-ui.

Docs: README quickstart; optional logler init (planned) to scaffold config.

CI/CD: GitHub Actions builds frontend (npm run build), runs all tests, builds wheels with maturin, and can publish to PyPI (supports Trusted Publisher).
frontend/dist is not committed—CI builds it.


---

Security & Privacy

Local-first by default; no cloud dependency.

No tracking/telemetry unless explicitly added (opt-in only).

Fits inside offline or air-gapped workflows (copy logs, analyze locally).


---

Roadmap (pragmatic, low-risk first)

Near-term

Windows niceties: robust npm.cmd subprocess; friendlier error messages.

logler version / logler info commands; version in UI footer.

Saved filters & custom regex → color rules.

Better timestamp parsing & time-zone handling.

Rust deepening (opt-in, incremental)

Push regex/thread extraction down to Rust for line-rate parsing.

Optional live pre-filtering and highlighting in Rust stream.

Pluggable parsers (JSON, nginx/syslog, k8s formats) and format auto-detect.

Power features

“Jump to next/prev error/warn”, bookmarks, shareable filter sets.

Export thread traces (OpenTelemetry/Jaeger).

Desktop packaging (single-binary UI via Tauri/Electron) for non-Python users.

Non-goals (for now)

No managed SaaS/clustered backend.

Not a full ELK replacement; Logler is a fast local companion.


---

Success Criteria

Cold-start to “seeing live logs” ≤ 10 s on a fresh machine.

Sub-50 ms median tail latency on typical workloads.

Users report “I stopped opening Kibana for local/dev debugging.”

Clean CI (lint/test/build) and painless Windows/macOS/Linux installs.


---

One-page pitch

> Logler is the snappy, private, local log viewer that makes tail -f feel obsolete and ELK feel heavyweight.
It fuses a Rust tail engine, a Python search/index layer, and a modern React UI—opening by default—so you can filter, search, compare, and trace logs instantly, without standing up infrastructure.
Ship faster, debug deeper, and keep your data on your machine.



