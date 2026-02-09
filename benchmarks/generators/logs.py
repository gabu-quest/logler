"""Log generator — deterministic JSON-lines log files with realistic patterns."""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path


class LogGenerator:
    """Generates deterministic JSON-lines log files for benchmarks.

    Produces realistic log entries with threads, correlations, traces,
    spans, and varied message templates.
    """

    LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]
    LEVEL_WEIGHTS = [0.1, 0.6, 0.2, 0.1]

    SERVICES = ["api-gateway", "auth-service", "user-service", "order-service", "cache-service"]

    HTTP_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]
    HTTP_PATHS = [
        "/api/users",
        "/api/orders",
        "/api/products",
        "/api/auth/login",
        "/api/auth/refresh",
        "/api/health",
        "/api/metrics",
        "/api/search",
        "/api/inventory",
        "/api/payments",
    ]
    HTTP_STATUSES = [200, 200, 200, 201, 204, 301, 400, 401, 403, 404, 500, 502, 503]

    DB_TABLES = ["users", "orders", "products", "sessions", "inventory", "payments"]
    DB_OPS = ["SELECT", "INSERT", "UPDATE", "DELETE"]

    CACHE_KEYS = ["user:{}", "session:{}", "product:{}", "config:{}", "rate_limit:{}"]

    ERROR_MESSAGES = [
        "Connection refused to {}:{}",
        "Timeout after {}ms waiting for {}",
        "Failed to parse response from {}",
        "Authentication failed for user {}",
        "Rate limit exceeded for client {}",
        "Out of memory: heap size {}MB",
        "Deadlock detected in transaction {}",
        "Circuit breaker open for {}",
        "SSL handshake failed with {}",
        "DNS resolution failed for {}",
    ]

    INFO_TEMPLATES = [
        "Request received from {}",
        "Processing batch of {} items",
        "Cache {} for key={}",
        "Health check passed (uptime={}s)",
        "Worker {} started processing",
        "Scheduled task {} completed",
        "Connection pool: {}/{} active",
        "Metrics exported ({} datapoints)",
    ]

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self.base_time = datetime(2025, 1, 15, 10, 0, 0)

    def generate(
        self,
        num_entries: int,
        *,
        num_threads: int = 10,
        num_correlations: int = 20,
        error_rate: float = 0.1,
        with_spans: bool = False,
    ) -> list[dict]:
        """Generate a list of log entries as dicts.

        Args:
            num_entries: Number of log entries to generate.
            num_threads: Number of unique thread IDs.
            num_correlations: Number of unique correlation IDs.
            error_rate: Fraction of entries that are ERROR level.
            with_spans: Include span_id and parent_span_id fields.

        Returns:
            List of log entry dicts, sorted by timestamp.
        """
        thread_ids = [f"worker-{i:03d}" for i in range(num_threads)]
        correlation_ids = [f"req-{i:06d}" for i in range(num_correlations)]
        trace_ids = [f"trace-{i:04x}" for i in range(num_correlations)]

        # Pre-compute level distribution respecting error_rate
        level_weights = list(self.LEVEL_WEIGHTS)
        level_weights[3] = error_rate  # ERROR
        remaining = 1.0 - error_rate
        non_error_total = sum(level_weights[:3])
        if non_error_total > 0:
            for i in range(3):
                level_weights[i] = level_weights[i] / non_error_total * remaining

        entries = []
        for i in range(num_entries):
            ts = self.base_time + timedelta(milliseconds=i * self.rng.uniform(0.5, 5.0))
            level = self.rng.choices(self.LEVELS, weights=level_weights, k=1)[0]
            thread_id = self.rng.choice(thread_ids)
            cid_idx = i % num_correlations
            correlation_id = correlation_ids[cid_idx]
            trace_id = trace_ids[cid_idx]

            message = self._generate_message(level)
            duration_ms = round(self.rng.uniform(0.1, 500.0), 2)

            entry = {
                "timestamp": ts.isoformat() + "Z",
                "level": level,
                "message": message,
                "thread_id": thread_id,
                "correlation_id": correlation_id,
                "trace_id": trace_id,
                "fields": {
                    "duration_ms": duration_ms,
                },
            }

            if with_spans:
                span_id = f"span-{i:08x}"
                entry["span_id"] = span_id
                # ~60% of entries have a parent span
                if self.rng.random() < 0.6 and i > 0:
                    parent_idx = self.rng.randint(max(0, i - 20), i - 1)
                    entry["parent_span_id"] = f"span-{parent_idx:08x}"

            if level == "ERROR":
                entry["fields"]["status_code"] = self.rng.choice([500, 502, 503])
            elif self.rng.random() < 0.3:
                entry["fields"]["status_code"] = self.rng.choice([200, 201, 204, 301])

            entries.append(entry)

        return entries

    def write_file(self, path: str | Path, entries: list[dict]) -> int:
        """Write entries as JSON-lines to a file. Returns bytes written."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(e) for e in entries]
        content = "\n".join(lines) + "\n"
        path.write_text(content)
        return len(content.encode())

    def generate_multi_service(
        self,
        services: list[str],
        entries_per: int,
        correlation_id: str,
    ) -> dict[str, list[dict]]:
        """Generate log entries across multiple services sharing a correlation ID.

        Returns:
            Dict mapping service name to list of entries.
        """
        result: dict[str, list[dict]] = {}
        base_ts = self.base_time

        for svc_idx, service in enumerate(services):
            entries = []
            svc_offset = timedelta(milliseconds=svc_idx * 50)

            for i in range(entries_per):
                ts = base_ts + svc_offset + timedelta(milliseconds=i * self.rng.uniform(1, 10))
                level = self.rng.choices(self.LEVELS, weights=self.LEVEL_WEIGHTS, k=1)[0]

                entry = {
                    "timestamp": ts.isoformat() + "Z",
                    "level": level,
                    "message": self._generate_message(level),
                    "thread_id": f"{service}-worker-{i % 3}",
                    "correlation_id": correlation_id,
                    "trace_id": f"trace-{hash(correlation_id) & 0xFFFF:04x}",
                    "service": service,
                    "fields": {
                        "duration_ms": round(self.rng.uniform(0.1, 200.0), 2),
                    },
                }
                entries.append(entry)

            result[service] = entries

        return result

    def _generate_message(self, level: str) -> str:
        """Generate a realistic log message based on level."""
        if level == "ERROR":
            template = self.rng.choice(self.ERROR_MESSAGES)
            hosts = ["db-primary", "cache-01", "auth-svc", "api-gw", "queue-01"]
            return template.format(
                self.rng.choice(hosts),
                self.rng.randint(1000, 9999),
            )

        if level == "WARN":
            warnings = [
                f"Slow query: {self.rng.choice(self.DB_OPS)} on {self.rng.choice(self.DB_TABLES)} "
                f"took {self.rng.randint(100, 5000)}ms",
                f"High memory usage: {self.rng.randint(70, 95)}%",
                f"Connection pool nearly exhausted: {self.rng.randint(8, 10)}/10",
                f"Retry attempt {self.rng.randint(1, 3)} for {self.rng.choice(self.HTTP_PATHS)}",
                f"Deprecated API call to {self.rng.choice(self.HTTP_PATHS)}",
            ]
            return self.rng.choice(warnings)

        if level == "DEBUG":
            debugs = [
                f"Entering {self.rng.choice(['validate', 'transform', 'serialize', 'parse'])}()",
                f"Cache lookup for {self.rng.choice(self.CACHE_KEYS).format(self.rng.randint(1, 100))}",
                f"SQL: {self.rng.choice(self.DB_OPS)} * FROM {self.rng.choice(self.DB_TABLES)} "
                f"WHERE id = {self.rng.randint(1, 10000)}",
            ]
            return self.rng.choice(debugs)

        # INFO
        method = self.rng.choice(self.HTTP_METHODS)
        path = self.rng.choice(self.HTTP_PATHS)
        status = self.rng.choice(self.HTTP_STATUSES)
        duration = self.rng.randint(1, 500)
        return f"{method} {path} {status} {duration}ms"
