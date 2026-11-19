"""The test session stops at start when the compiled extension cannot be imported."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from logler._search_core import BUILD_HINT

ROOT = Path(__file__).resolve().parent.parent

RUNNER = (
    "import sys; sys.modules['logler_rs'] = None; import pytest; "
    "sys.exit(pytest.main(['-p', 'no:cacheprovider', '-q', "
    "'tests/test_parser.py']))"
)


def test_session_exits_with_build_command_when_extension_missing():
    result = subprocess.run(
        [sys.executable, "-c", RUNNER],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=120,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 3, output
    assert "logler_rs (the compiled extension) cannot be imported" in output
    assert BUILD_HINT in output
    assert "passed" not in output
    assert "skipped" not in output
