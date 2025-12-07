#!/usr/bin/env python3
"""
Live interleave log generator.

Writes to three files under examples/logs/interleave with staggered cadences
so you can watch the UI interleave and follow real-time updates.

Usage:
    python examples/en/live_interleave_stream.py
Then in another shell:
    uv run logler serve --auto-port examples/logs/interleave/api.log examples/logs/interleave/search.log examples/logs/interleave/worker.log
Enable follow/interleave in the UI to see live updates.
"""

from __future__ import annotations

import json
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("examples/logs/interleave")
FILES = {
    "api": BASE / "api.log",
    "search": BASE / "search.log",
    "worker": BASE / "worker.log",
}
CADENCE = {
    "api": 0.8,      # seconds between writes
    "search": 1.3,
    "worker": 1.0,
}


def make_line(service: str, idx: int) -> dict:
    level = random.choices(["INFO", "WARN", "ERROR"], weights=[0.7, 0.2, 0.1])[0]
    correlation = f"live-demo-{idx // 5:04d}"
    message = {
        "INFO": f"{service} heartbeat ok",
        "WARN": f"{service} cache miss spike",
        "ERROR": f"{service} timeout reaching upstream",
    }[level]
    return {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "level": level,
        "service": service,
        "thread_id": f"{service}-{idx % 50:03d}",
        "correlation_id": correlation,
        "trace_id": f"trace-{correlation}",
        "span_id": f"span-{service}-{idx}",
        "message": message,
    }


def main():
    BASE.mkdir(parents=True, exist_ok=True)
    handles = {name: path.open("a", encoding="utf-8") for name, path in FILES.items()}

    def stop(_signo, _frame):
        for f in handles.values():
            f.flush()
            f.close()
        print("\nStopped live interleave writer.")
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    print("Writing live interleave logs to:")
    for name, path in FILES.items():
        print(f"  {name}: {path} (every {CADENCE[name]}s)")
    print("Use the UI interleave mode to watch them stream.")

    last_emit = {name: 0.0 for name in FILES}
    counters = {name: 0 for name in FILES}

    while True:
        now = time.perf_counter()
        for name, handle in handles.items():
            if now - last_emit[name] >= CADENCE[name]:
                counters[name] += 1
                handle.write(json.dumps(make_line(name, counters[name])) + "\n")
                handle.flush()
                last_emit[name] = now
        time.sleep(0.05)


if __name__ == "__main__":
    main()
