"""
Logler - Beautiful local log viewer with thread tracking and real-time updates.
"""

__version__ = "1.0.7"
__author__ = "Logler Contributors"

from .parser import LogParser, LogEntry
from .tracker import ThreadTracker
from .log_reader import LogReader
from .tree_formatter import format_tree, format_waterfall, print_tree, print_waterfall

__all__ = [
    "LogParser",
    "LogEntry",
    "ThreadTracker",
    "LogReader",
    "format_tree",
    "format_waterfall",
    "print_tree",
    "print_waterfall",
]
