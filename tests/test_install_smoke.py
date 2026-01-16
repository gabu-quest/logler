"""
Smoke tests to verify logler installation works correctly.

Run with: pytest tests/test_install_smoke.py -v
"""

import subprocess
from pathlib import Path


EXAMPLE_LOGS = Path(__file__).parent.parent / "examples" / "logs"


class TestCLICommands:
    """Test that CLI commands work."""

    def test_version(self):
        result = subprocess.run(
            ["logler", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "logler, version" in result.stdout

    def test_help(self):
        result = subprocess.run(
            ["logler", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Beautiful local log viewer" in result.stdout

    def test_llm_help(self):
        result = subprocess.run(
            ["logler", "llm", "--help"],
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
            ["logler", "llm", "schema", str(log_file)],
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
            ["logler", "llm", "emit", str(log_file)],
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
            ["logler", "llm", "search", str(log_file), "--query", "api"],
            capture_output=True,
            text=True,
        )
        # Exit code 0 = results found, 1 = no results (both valid)
        assert result.returncode in [0, 1]
        import json

        data = json.loads(result.stdout)
        assert "query" in data
        assert "summary" in data


class TestRustBackend:
    """Test that Rust backend is available and working."""

    def test_rust_available(self):
        result = subprocess.run(
            ["python", "-c", "import logler_rs; print('OK')"],
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
            ["python", "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        count = int(result.stdout.strip())
        assert count > 0
