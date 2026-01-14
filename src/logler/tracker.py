"""
Thread and trace tracking for log correlation.
"""

from typing import Dict, List, Optional
from collections import defaultdict

from .parser import LogEntry


class ThreadTracker:
    """Track threads and correlate log entries."""

    def __init__(self):
        self.threads: Dict[str, dict] = {}
        self.traces: Dict[str, dict] = {}
        self.correlations: Dict[str, List[LogEntry]] = defaultdict(list)

    def track(self, entry: LogEntry):
        """Track a log entry."""
        # Track by thread ID
        if entry.thread_id:
            self._track_thread(entry)

        # Track by correlation ID
        if entry.correlation_id:
            self.correlations[entry.correlation_id].append(entry)

        # Track by trace ID
        if entry.trace_id:
            self._track_trace(entry)

    def _track_thread(self, entry: LogEntry):
        """Track thread information."""
        thread_id = entry.thread_id

        if thread_id not in self.threads:
            self.threads[thread_id] = {
                "thread_id": thread_id,
                "first_seen": entry.timestamp,
                "last_seen": entry.timestamp,
                "log_count": 0,
                "error_count": 0,
                "correlation_ids": set(),
            }

        thread = self.threads[thread_id]
        thread["log_count"] += 1

        if entry.level in ["ERROR", "FATAL", "CRITICAL"]:
            thread["error_count"] += 1

        if entry.timestamp:
            if not thread["first_seen"] or entry.timestamp < thread["first_seen"]:
                thread["first_seen"] = entry.timestamp
            if not thread["last_seen"] or entry.timestamp > thread["last_seen"]:
                thread["last_seen"] = entry.timestamp

        if entry.correlation_id:
            thread["correlation_ids"].add(entry.correlation_id)

    def _track_trace(self, entry: LogEntry):
        """Track trace information."""
        trace_id = entry.trace_id

        if trace_id not in self.traces:
            self.traces[trace_id] = {
                "trace_id": trace_id,
                "spans": [],
                "services": set(),
                "start_time": entry.timestamp,
                "end_time": entry.timestamp,
            }

        trace = self.traces[trace_id]

        if entry.span_id:
            trace["spans"].append(
                {
                    "span_id": entry.span_id,
                    "timestamp": entry.timestamp,
                    "message": entry.message,
                }
            )

        if entry.service_name:
            trace["services"].add(entry.service_name)

        if entry.timestamp:
            if not trace["start_time"] or entry.timestamp < trace["start_time"]:
                trace["start_time"] = entry.timestamp
            if not trace["end_time"] or entry.timestamp > trace["end_time"]:
                trace["end_time"] = entry.timestamp

    def get_thread(self, thread_id: str) -> Optional[dict]:
        """Get thread information."""
        thread = self.threads.get(thread_id)
        if thread:
            thread["correlation_ids"] = list(thread["correlation_ids"])
        return thread

    def get_all_threads(self) -> List[dict]:
        """Get all tracked threads."""
        result = []
        for thread in self.threads.values():
            thread_copy = thread.copy()
            thread_copy["correlation_ids"] = list(thread["correlation_ids"])
            result.append(thread_copy)
        return sorted(result, key=lambda x: x["log_count"], reverse=True)

    def get_trace(self, trace_id: str) -> Optional[dict]:
        """Get trace information."""
        trace = self.traces.get(trace_id)
        if trace:
            trace_copy = trace.copy()
            trace_copy["services"] = list(trace["services"])
            if trace_copy["start_time"] and trace_copy["end_time"]:
                delta = trace_copy["end_time"] - trace_copy["start_time"]
                trace_copy["duration_ms"] = delta.total_seconds() * 1000
            return trace_copy
        return None

    def get_all_traces(self) -> List[dict]:
        """Get all tracked traces."""
        result = []
        for trace_id in self.traces:
            trace = self.get_trace(trace_id)
            if trace:
                result.append(trace)
        return result

    def get_by_correlation(self, correlation_id: str) -> List[LogEntry]:
        """Get logs by correlation ID."""
        return self.correlations.get(correlation_id, [])

    def get_all_correlations(self) -> List[str]:
        """Get all correlation IDs."""
        return list(self.correlations.keys())
