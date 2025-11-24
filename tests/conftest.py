"""Test configuration for Logler.

Ensures the local `src` layout is importable without requiring an editable
install when running `pytest` from the repository root.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if SRC.exists():
    sys.path.insert(0, str(SRC))
