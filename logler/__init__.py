"""
Logler - Beautiful local log viewer with thread tracking and real-time updates.
"""

__version__ = "1.0.0"
__author__ = "Logler Contributors"

from .parser import LogParser, LogEntry
from .tracker import ThreadTracker

__all__ = ["LogParser", "LogEntry", "ThreadTracker"]
