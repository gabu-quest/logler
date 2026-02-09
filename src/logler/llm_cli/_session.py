"""Session management commands: create, list, query, note, conclude."""

import click
import json
import sys
from typing import Optional
from datetime import datetime

from ._core import (
    llm,
    EXIT_SUCCESS,
    EXIT_NO_RESULTS,
    EXIT_INTERNAL_ERROR,
    _output_json,
    _error_json,
    _expand_globs,
)


# Session management subgroup
@llm.group()
def session():
    """
    Stateful investigation sessions for complex analyses.

    Sessions track investigation steps and can be saved/resumed.
    """
    pass


@session.command("create")
@click.option("--files", "-f", multiple=True, required=True, help="Files to include")
@click.option("--name", help="Session name")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def session_create(files: tuple, name: Optional[str], pretty: bool):
    """Create a new investigation session."""
    import uuid
    from pathlib import Path

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {files}")

        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        session_name = name or f"investigation-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        session_data = {
            "session_id": session_id,
            "name": session_name,
            "created_at": datetime.now().isoformat(),
            "files": file_list,
            "status": "active",
            "log": [],
        }

        # Save session
        sessions_dir = Path.home() / ".logler" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)

        session_file = sessions_dir / f"{session_id}.json"
        with open(session_file, "w") as f:
            json.dump(session_data, f, indent=2, default=str)

        output = {
            "session_id": session_id,
            "name": session_name,
            "created_at": session_data["created_at"],
            "files": file_list,
            "status": "active",
            "session_file": str(session_file),
        }

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@session.command("list")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def session_list(pretty: bool):
    """List all investigation sessions."""
    from pathlib import Path

    try:
        sessions_dir = Path.home() / ".logler" / "sessions"

        if not sessions_dir.exists():
            _output_json({"sessions": []}, pretty)
            sys.exit(EXIT_SUCCESS)

        sessions = []
        for session_file in sessions_dir.glob("sess_*.json"):
            try:
                with open(session_file) as f:
                    data = json.load(f)
                    sessions.append(
                        {
                            "session_id": data.get("session_id"),
                            "name": data.get("name"),
                            "created_at": data.get("created_at"),
                            "status": data.get("status"),
                            "files_count": len(data.get("files", [])),
                        }
                    )
            except (json.JSONDecodeError, KeyError):
                pass

        # Sort by created_at descending
        sessions.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        _output_json({"sessions": sessions}, pretty)
        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@session.command("query")
@click.argument("session_id")
@click.option("--level", help="Filter by level")
@click.option("--query", help="Search pattern")
@click.option("--limit", type=int, help="Limit results")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def session_query(
    session_id: str, level: Optional[str], query: Optional[str], limit: Optional[int], pretty: bool
):
    """Query logs within a session context."""
    from pathlib import Path
    from .. import investigate

    try:
        sessions_dir = Path.home() / ".logler" / "sessions"
        session_file = sessions_dir / f"{session_id}.json"

        if not session_file.exists():
            _error_json(f"Session not found: {session_id}")

        with open(session_file) as f:
            session_data = json.load(f)

        files = session_data.get("files", [])

        result = investigate.search(
            files=files, query=query, level=level, limit=limit, output_format="full"
        )

        # Log the query
        session_data["log"].append(
            {
                "timestamp": datetime.now().isoformat(),
                "action": "query",
                "params": {"level": level, "query": query, "limit": limit},
                "results_count": len(result.get("results", [])),
            }
        )

        with open(session_file, "w") as f:
            json.dump(session_data, f, indent=2, default=str)

        _output_json(result, pretty)
        sys.exit(EXIT_SUCCESS if result.get("results") else EXIT_NO_RESULTS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@session.command("note")
@click.argument("session_id")
@click.option("--text", required=True, help="Note text")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def session_note(session_id: str, text: str, pretty: bool):
    """Add a note to a session."""
    from pathlib import Path

    try:
        sessions_dir = Path.home() / ".logler" / "sessions"
        session_file = sessions_dir / f"{session_id}.json"

        if not session_file.exists():
            _error_json(f"Session not found: {session_id}")

        with open(session_file) as f:
            session_data = json.load(f)

        note_entry = {"timestamp": datetime.now().isoformat(), "action": "note", "text": text}

        session_data["log"].append(note_entry)

        with open(session_file, "w") as f:
            json.dump(session_data, f, indent=2, default=str)

        _output_json({"status": "ok", "note": note_entry}, pretty)
        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@session.command("conclude")
@click.argument("session_id")
@click.option("--summary", required=True, help="Investigation summary")
@click.option("--root-cause", help="Root cause description")
@click.option("--confidence", type=float, default=0.8, help="Confidence level (0.0-1.0)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def session_conclude(
    session_id: str, summary: str, root_cause: Optional[str], confidence: float, pretty: bool
):
    """Conclude a session with findings."""
    from pathlib import Path

    try:
        sessions_dir = Path.home() / ".logler" / "sessions"
        session_file = sessions_dir / f"{session_id}.json"

        if not session_file.exists():
            _error_json(f"Session not found: {session_id}")

        with open(session_file) as f:
            session_data = json.load(f)

        conclusion = {
            "summary": summary,
            "root_cause": root_cause,
            "confidence": confidence,
            "concluded_at": datetime.now().isoformat(),
        }

        session_data["status"] = "concluded"
        session_data["conclusion"] = conclusion
        session_data["log"].append(
            {
                "timestamp": datetime.now().isoformat(),
                "action": "conclude",
                "conclusion": conclusion,
            }
        )

        with open(session_file, "w") as f:
            json.dump(session_data, f, indent=2, default=str)

        output = {
            "session_id": session_id,
            "conclusion": conclusion,
            "investigation_log": session_data["log"],
        }

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)
