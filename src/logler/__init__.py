"""logler - Cool local log viewing tool."""

__version__ = "0.1.0"

from .log_reader import LogReader
from .log_parser import LogParser

__all__ = ["LogReader", "LogParser"]
