#!/usr/bin/env python3
"""
Live log generator for frontend follow/tail demos.

This script continuously appends JSON log lines to examples/logs/live_follow_demo.log
to exercise the web UI's auto-scroll/tail behavior.
"""

from __future__ import annotations

import json
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path("examples/logs/live_follow_demo.log")


def make_line(i: int) -> dict:
    services = ["api", "search", "ledger", "auth", "payments"]
    levels = ["INFO", "WARN", "ERROR"]
    service = random.choice(services)
    level = random.choices(levels, weights=[0.7, 0.2, 0.1])[0]
    correlation = f"live-{i//10:04d}"
    message = {
        "INFO": "heartbeat ok",
        "WARN": "cache miss spike",
        "ERROR": "Database timeout",
    }[level]

    return {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "level": level,
        "service": service,
        "thread_id": f"t-{service}-{i % 50:03d}",
        "correlation_id": correlation,
        "trace_id": f"trace-{correlation}",
        "span_id": f"span-{i}",
        "message": message,
        "metric": round(random.random() * 100, 2),
    }


def main():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("w", encoding="utf-8") as f:
        print(f"Writing live log lines to {LOG_PATH} (Ctrl+C to stop)...")
        print("Start the UI in another shell: uv run logler serve --auto-port examples/logs/live_follow_demo.log")
        print("Then open the browser and enable follow/tail to watch updates.")

        def stop(_signo, _frame):
            print("\nStopping live writer.")
            sys.exit(0)

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)

        i = 0
        while True:
            line = make_line(i)
            f.write(json.dumps(line) + "\n")
            f.flush()
            time.sleep(0.15)
            i += 1


if __name__ == "__main__":
    main()
