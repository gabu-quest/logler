"""
Helper to ensure the Rust backend is installed.

Attempts to import `logler_rs`; if missing, runs `maturin develop` against
`crates/logler-py/Cargo.toml` with the `sql` feature enabled.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


def ensure_rust_backend(auto_install: bool = True) -> bool:
    """Ensure logler_rs is importable. Optionally auto-installs via maturin."""
    try:
        import logler_rs  # noqa: F401

        return True
    except Exception:
        if not auto_install:
            return False

    maturin = _which("maturin")
    if not maturin:
        return False

    repo_root = Path(__file__).resolve().parents[2]
    cmd = [
        maturin,
        "develop",
        "--release",
        "-m",
        str(repo_root / "crates" / "logler-py" / "Cargo.toml"),
        "--features",
        "sql",
    ]
    try:
        subprocess.run(
            cmd, cwd=repo_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except Exception:
        return False

    try:
        import logler_rs  # noqa: F401

        return True
    except Exception:
        return False


def _which(cmd: str) -> Optional[str]:
    from shutil import which

    return which(cmd)
