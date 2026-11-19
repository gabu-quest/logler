"""logler never builds its extension at import, and says what is true when it is missing."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_detect_correlation_chains_without_extension_raises_runtime_error(monkeypatch, tmp_path):
    import logler.hierarchy as hierarchy

    log = tmp_path / "a.log"
    log.write_text("2024-01-15 10:00:00 INFO hello\n")
    monkeypatch.setattr(hierarchy, "RUST_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="Rust backend not available"):
        hierarchy.detect_correlation_chains([str(log)])


def test_missing_extension_warns_truthfully_and_builds_nothing(tmp_path):
    stub = tmp_path / "stub"
    (stub / "logler_rs").mkdir(parents=True)
    (stub / "logler_rs" / "__init__.py").write_text('raise ImportError("stub")\n')

    bindir = tmp_path / "bin"
    bindir.mkdir()
    marker = tmp_path / "maturin-ran"
    maturin = bindir / "maturin"
    maturin.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
    maturin.chmod(0o755)

    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(stub), str(ROOT / "src")]),
        "PATH": os.pathsep.join([str(bindir), os.environ.get("PATH", "")]),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-W",
            "always",
            "-c",
            "import logler._search_core as c; print('AVAILABLE', c.RUST_AVAILABLE)",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "AVAILABLE False" in result.stdout
    assert not marker.exists()
    assert "stub" in result.stderr
    assert "maturin develop --release -m crates/logler-py/Cargo.toml" in result.stderr
    assert "fallback" not in result.stderr.lower()
