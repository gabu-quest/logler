"""System information collection for benchmark reports."""

from __future__ import annotations

import platform
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class SystemInfo:
    """System information captured at benchmark run time."""

    python_version: str
    logler_version: str
    rust_available: bool
    logler_rs_version: str
    platform_system: str
    platform_machine: str
    platform_release: str
    cpu_count: int
    timestamp: str

    @classmethod
    def collect(cls) -> SystemInfo:
        from importlib.metadata import version as pkg_version

        try:
            logler_ver = pkg_version("logler")
        except Exception:
            logler_ver = "dev"

        rust_available = False
        rs_version = "unavailable"
        try:
            import logler_rs

            rust_available = True
            rs_version = getattr(logler_rs, "__version__", "unknown")
        except ImportError:
            pass

        import os

        return cls(
            python_version=sys.version.split()[0],
            logler_version=logler_ver,
            rust_available=rust_available,
            logler_rs_version=rs_version,
            platform_system=platform.system(),
            platform_machine=platform.machine(),
            platform_release=platform.release(),
            cpu_count=os.cpu_count() or 1,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def summary_line(self) -> str:
        rust_tag = f"Rust {self.logler_rs_version}" if self.rust_available else "no Rust"
        return (
            f"Python {self.python_version} | "
            f"logler {self.logler_version} | "
            f"{rust_tag} | "
            f"{self.platform_system} {self.platform_machine} ({self.cpu_count} cores)"
        )
