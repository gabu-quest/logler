"""
InvestigationSession — stateful multi-step investigation with history tracking.

Public API surface is re-exported by :mod:`logler.investigate`.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime

from ._search_core import search, follow_thread, find_patterns
from .comparison import compare_threads, cross_service_timeline


class InvestigationSession:
    """Track investigation state and history for multi-step analysis.

    This allows LLM agents to:

    * Track what they've already investigated
    * Undo/redo operations
    * Save and resume investigations
    * Generate reports of their investigation process

    Example::

        session = InvestigationSession(files=["app.log"])
        session.search(level="ERROR")
        session.follow_thread(correlation_id="req-123")
        session.find_patterns()

        history = session.get_history()
        session.save("incident_2024_01_15.json")

        session2 = InvestigationSession.load("incident_2024_01_15.json")
    """

    def __init__(self, files: Optional[List[str]] = None, name: Optional[str] = None):
        self.files = files or []
        self.name = name or f"investigation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.history = []
        self.current_index = -1
        self.metadata = {}

        if files:
            self._add_to_history("init", "Initialize investigation", {"files": files}, None)

    def search(
        self,
        query: Optional[str] = None,
        level: Optional[str] = None,
        output_format: str = "summary",
        **kwargs,
    ) -> Dict[str, Any]:
        """Perform search and track in history."""
        params = {"query": query, "level": level, "output_format": output_format, **kwargs}
        result = search(self.files, query=query, level=level, output_format=output_format, **kwargs)

        self._add_to_history(
            "search",
            f"Search for {level or 'all'} logs" + (f" matching '{query}'" if query else ""),
            params,
            result,
        )

        return result

    def follow_thread(
        self,
        thread_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Follow thread and track in history."""
        params = {"thread_id": thread_id, "correlation_id": correlation_id, "trace_id": trace_id}
        result = follow_thread(
            self.files, thread_id=thread_id, correlation_id=correlation_id, trace_id=trace_id
        )

        thread_desc = thread_id or correlation_id or trace_id
        self._add_to_history("follow_thread", f"Follow thread: {thread_desc}", params, result)

        return result

    def find_patterns(self, min_occurrences: int = 3) -> Dict[str, Any]:
        """Find patterns and track in history."""
        params = {"min_occurrences": min_occurrences}
        result = find_patterns(self.files, min_occurrences=min_occurrences)

        self._add_to_history(
            "find_patterns", f"Find patterns (min {min_occurrences} occurrences)", params, result
        )

        return result

    def compare_threads(self, **kwargs) -> Dict[str, Any]:
        """Compare threads and track in history."""
        result = compare_threads(self.files, **kwargs)

        desc = f"Compare {kwargs.get('correlation_a', 'A')} vs {kwargs.get('correlation_b', 'B')}"
        self._add_to_history("compare_threads", desc, kwargs, result)

        return result

    def cross_service_timeline(
        self, service_files: Dict[str, List[str]], **kwargs
    ) -> Dict[str, Any]:
        """Create cross-service timeline and track in history."""
        result = cross_service_timeline(service_files, **kwargs)

        desc = f"Cross-service timeline for {list(service_files.keys())}"
        self._add_to_history(
            "cross_service_timeline", desc, {"service_files": service_files, **kwargs}, result
        )

        return result

    def add_note(self, note: str):
        """Add a text note to the investigation."""
        self._add_to_history("note", f"Note: {note[:50]}...", {"note": note}, None)

    def _add_to_history(
        self,
        operation_type: str,
        description: str,
        params: Dict[str, Any],
        result: Optional[Dict[str, Any]],
    ):
        """Add operation to history."""
        # Remove any operations after current index (for undo/redo)
        self.history = self.history[: self.current_index + 1]

        entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation_type,
            "description": description,
            "params": params,
            "result_summary": self._summarize_result(result) if result else None,
        }

        self.history.append(entry)
        self.current_index = len(self.history) - 1

    def _summarize_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Create a compact summary of operation result."""
        if not result:
            return {}

        summary = {}

        # Common fields
        if "total_matches" in result:
            summary["total_matches"] = result["total_matches"]
        if "total_entries" in result:
            summary["total_entries"] = result["total_entries"]
        if "duration_ms" in result:
            summary["duration_ms"] = result["duration_ms"]
        if "summary" in result:
            summary["summary"] = result["summary"]

        # Pattern results
        if "patterns" in result:
            summary["pattern_count"] = len(result["patterns"])

        # Timeline results
        if "timeline" in result:
            summary["timeline_length"] = len(result["timeline"])

        return summary

    def get_history(self, include_results: bool = False) -> List[Dict[str, Any]]:
        """Get investigation history."""
        if include_results:
            return self.history
        else:
            # Return without full results (more token-efficient)
            return [
                {
                    "timestamp": h["timestamp"],
                    "operation": h["operation"],
                    "description": h["description"],
                    "result_summary": h.get("result_summary"),
                }
                for h in self.history
            ]

    def undo(self) -> bool:
        """Undo last operation."""
        if self.current_index > 0:
            self.current_index -= 1
            return True
        return False

    def redo(self) -> bool:
        """Redo previously undone operation."""
        if self.current_index < len(self.history) - 1:
            self.current_index += 1
            return True
        return False

    def get_current_focus(self) -> Optional[Dict[str, Any]]:
        """Get the current operation being focused on."""
        if 0 <= self.current_index < len(self.history):
            return self.history[self.current_index]
        return None

    def save(self, filepath: str):
        """Save session to file."""
        import json

        data = {
            "name": self.name,
            "files": self.files,
            "history": self.history,
            "current_index": self.current_index,
            "metadata": self.metadata,
            "saved_at": datetime.now().isoformat(),
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, filepath: str) -> "InvestigationSession":
        """Load session from file."""
        import json

        with open(filepath, "r") as f:
            data = json.load(f)

        session = cls(files=data["files"], name=data["name"])
        session.history = data["history"]
        session.current_index = data["current_index"]
        session.metadata = data.get("metadata", {})

        return session

    def get_summary(self) -> str:
        """Get a human-readable summary of the investigation."""
        if not self.history:
            return "No investigation steps yet"

        lines = [
            f"Investigation: {self.name}",
            f"Steps completed: {len(self.history)}",
            "",
            "Timeline:",
        ]

        for i, entry in enumerate(self.history):
            marker = "\u2192" if i == self.current_index else " "
            lines.append(f"  {marker} {i + 1}. {entry['description']}")
            if entry.get("result_summary"):
                for key, value in entry["result_summary"].items():
                    lines.append(f"      {key}: {value}")

        return "\n".join(lines)

    def generate_report(self, format: str = "markdown", include_evidence: bool = True) -> str:
        """Generate a comprehensive investigation report.

        Args:
            format: Output format — ``"markdown"``, ``"text"``, or ``"json"``.
            include_evidence: Include example log entries as evidence.

        Returns:
            Formatted investigation report string.
        """
        if format == "markdown":
            return self._generate_markdown_report(include_evidence)
        elif format == "text":
            return self._generate_text_report(include_evidence)
        elif format == "json":
            import json

            return json.dumps(self._generate_json_report(include_evidence), indent=2)
        else:
            return self._generate_markdown_report(include_evidence)

    def _generate_markdown_report(self, include_evidence: bool) -> str:
        """Generate Markdown format report."""
        lines = [
            f"# Investigation Report: {self.name}",
            "",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Files Analyzed:** {', '.join(self.files)}",
            f"**Steps Completed:** {len(self.history)}",
            "",
            "---",
            "",
            "## Executive Summary",
            "",
        ]

        # Try to extract key findings
        error_counts = []
        patterns_found = []
        key_insights = []

        for entry in self.history:
            summary = entry.get("result_summary") or {}
            if "total_matches" in summary and entry["operation"] == "search":
                error_counts.append(
                    f"- Found {summary['total_matches']} matches in {entry['description']}"
                )
            if "pattern_count" in summary:
                patterns_found.append(f"- Identified {summary['pattern_count']} repeated patterns")
            if "summary" in summary:
                key_insights.append(f"- {summary['summary']}")

        if error_counts:
            lines.extend(error_counts)
        if patterns_found:
            lines.extend(patterns_found)
        if key_insights:
            lines.append("")
            lines.append("### Key Findings")
            lines.extend(key_insights)

        lines.extend(["", "---", "", "## Investigation Timeline", ""])

        # Add detailed timeline
        for i, entry in enumerate(self.history):
            timestamp = entry.get("timestamp", "Unknown time")
            desc = entry["description"]
            operation = entry["operation"]

            lines.append(f"### Step {i + 1}: {desc}")
            lines.append("")
            lines.append(f"- **Time:** {timestamp}")
            lines.append(f"- **Operation:** `{operation}`")

            # Add results
            if entry.get("result_summary"):
                lines.append("- **Results:**")
                for key, value in entry["result_summary"].items():
                    lines.append(f"  - {key}: {value}")

            lines.append("")

        lines.extend(
            [
                "---",
                "",
                "## Conclusions",
                "",
                "Based on the investigation steps above, review the key findings and error patterns.",
                "",
                "## Next Steps",
                "",
                "- [ ] Review identified error patterns",
                "- [ ] Investigate root causes",
                "- [ ] Implement fixes",
                "- [ ] Monitor for recurrence",
                "",
            ]
        )

        return "\n".join(lines)

    def _generate_text_report(self, include_evidence: bool) -> str:
        """Generate plain text format report."""
        lines = [
            "=" * 70,
            f"INVESTIGATION REPORT: {self.name}",
            "=" * 70,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Files: {', '.join(self.files)}",
            f"Steps: {len(self.history)}",
            "=" * 70,
            "",
            "TIMELINE:",
            "",
        ]

        for i, entry in enumerate(self.history):
            timestamp = entry.get("timestamp", "Unknown")
            lines.append(f"{i + 1}. [{timestamp}] {entry['description']}")

            if entry.get("result_summary"):
                for key, value in entry["result_summary"].items():
                    lines.append(f"   - {key}: {value}")
            lines.append("")

        lines.extend(["=" * 70, "END OF REPORT", "=" * 70])

        return "\n".join(lines)

    def _generate_json_report(self, include_evidence: bool) -> Dict[str, Any]:
        """Generate JSON format report."""
        return {
            "name": self.name,
            "generated_at": datetime.now().isoformat(),
            "files": self.files,
            "steps_completed": len(self.history),
            "timeline": (
                self.history if include_evidence else self.get_history(include_results=False)
            ),
            "metadata": self.metadata,
        }
