"""Test configuration for Logler.

Ensures the local `src` layout is importable without requiring an editable
install when running `pytest` from the repository root.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import importlib
import sys
import subprocess
import shutil

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if SRC.exists():
    sys.path.insert(0, str(SRC))


@dataclass
class RustBackendStatus:
    ready: bool
    skip_reason: str | None = None
    error: str | None = None


def _attempt_import_logler_rs() -> tuple[bool, Exception | None]:
    try:
        import logler_rs  # noqa: F401
        return True, None
    except Exception as exc:  # pragma: no cover - only hit when Rust missing
        return False, exc


def _ensure_rust_backend() -> RustBackendStatus:
    imported, import_err = _attempt_import_logler_rs()
    if imported:
        return RustBackendStatus(ready=True)

    maturin = shutil.which("maturin")
    cargo = shutil.which("cargo")
    missing = [name for name, path in (("maturin", maturin), ("cargo", cargo)) if not path]
    if missing:
        reason = f"Rust toolchain missing ({', '.join(missing)}); cannot build logler_rs"
        return RustBackendStatus(ready=False, skip_reason=reason, error=str(import_err))

    cmd = [
        maturin,
        "develop",
        "--release",
        "-m",
        str(ROOT / "crates" / "logler-py" / "Cargo.toml"),
        "--features",
        "sql",
    ]
    proc = subprocess.run(cmd, cwd=ROOT, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        return RustBackendStatus(
            ready=False,
            error=f"maturin develop failed ({proc.returncode}): {(proc.stderr or proc.stdout).strip()}",
        )

    imported, post_build_err = _attempt_import_logler_rs()
    if imported:
        return RustBackendStatus(ready=True)

    return RustBackendStatus(
        ready=False,
        error=f"logler_rs import failed after build: {post_build_err}",
    )


RUST_BACKEND_STATUS = _ensure_rust_backend()
RUST_READY = RUST_BACKEND_STATUS.ready


@pytest.fixture(scope="session")
def rust_backend():
    status = RUST_BACKEND_STATUS
    if status.skip_reason:
        pytest.skip(status.skip_reason)
    if not status.ready:
        pytest.fail(status.error or "Rust backend missing even though maturin is available")

    import logler_rs
    return logler_rs


@pytest.fixture(scope="session")
def investigate_module(rust_backend):
    import logler.investigate as investigate

    investigate = importlib.reload(investigate)
    assert getattr(investigate, "RUST_AVAILABLE", False), "logler.investigate reports RUST_AVAILABLE=False"
    return investigate
