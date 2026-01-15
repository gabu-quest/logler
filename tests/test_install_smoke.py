"""
Smoke tests to verify logler installation works correctly.

Run with: uv run pytest tests/test_install_smoke.py -v
"""

import subprocess
import time
import pytest
import httpx
from pathlib import Path


EXAMPLE_LOGS = Path(__file__).parent.parent / "examples" / "logs"


class TestCLICommands:
    """Test that CLI commands work."""

    def test_version(self):
        result = subprocess.run(
            ["uv", "run", "logler", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "logler, version" in result.stdout

    def test_help(self):
        result = subprocess.run(
            ["uv", "run", "logler", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Beautiful local log viewer" in result.stdout

    def test_llm_help(self):
        result = subprocess.run(
            ["uv", "run", "logler", "llm", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "LLM-first CLI commands" in result.stdout


class TestLLMCommands:
    """Test LLM CLI commands with real log files."""

    def test_llm_schema(self):
        log_file = EXAMPLE_LOGS / "interleave" / "api.log"
        result = subprocess.run(
            ["uv", "run", "logler", "llm", "schema", str(log_file)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        import json

        data = json.loads(result.stdout)
        assert "files" in data
        assert len(data["files"]) == 1

    def test_llm_emit(self):
        log_file = EXAMPLE_LOGS / "interleave" / "api.log"
        result = subprocess.run(
            ["uv", "run", "logler", "llm", "emit", str(log_file)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        # Output is JSONL - each line is a JSON object
        lines = [line for line in result.stdout.strip().split("\n") if line]
        assert len(lines) > 0
        import json

        first = json.loads(lines[0])
        assert "ln" in first or "line_number" in first

    def test_llm_search(self):
        log_file = EXAMPLE_LOGS / "interleave" / "api.log"
        result = subprocess.run(
            ["uv", "run", "logler", "llm", "search", str(log_file), "--query", "api"],
            capture_output=True,
            text=True,
        )
        # Exit code 0 = results found, 1 = no results (both valid)
        assert result.returncode in [0, 1]
        import json

        data = json.loads(result.stdout)
        assert "query" in data
        assert "summary" in data


class TestWebServer:
    """Test the web server functionality."""

    @pytest.fixture
    def server(self):
        """Start server and yield, then cleanup."""
        import socket

        # Find a free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

        proc = subprocess.Popen(
            ["uv", "run", "logler", "serve", str(EXAMPLE_LOGS), "--port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for server to start
        time.sleep(2)

        yield f"http://localhost:{port}"

        proc.terminate()
        proc.wait(timeout=5)

    def test_browse_endpoint(self, server):
        resp = httpx.get(f"{server}/api/files/browse", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert "files" in data or "directories" in data

    def test_glob_endpoint(self, server):
        resp = httpx.get(f"{server}/api/files/glob?pattern=**/*.log", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert "files" in data
        assert "count" in data

    def test_index_page(self, server):
        resp = httpx.get(server, timeout=10)
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


class TestRustBackend:
    """Test that Rust backend is available and working."""

    def test_rust_available(self):
        result = subprocess.run(
            ["uv", "run", "python", "-c", "import logler_rs; print('OK')"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_rust_investigator(self):
        code = """
import logler_rs
import json
inv = logler_rs.PyInvestigator()
inv.load_files(['examples/logs/interleave/api.log'])
query = {
    'files': ['examples/logs/interleave/api.log'],
    'limit': 5,
    'filters': {'levels': []},
    'context_lines': 0
}
result = json.loads(inv.search(json.dumps(query)))
print(len(result.get('results', [])))
"""
        result = subprocess.run(
            ["uv", "run", "python", "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        count = int(result.stdout.strip())
        assert count > 0
