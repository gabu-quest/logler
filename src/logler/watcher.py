"""
File watching with regex pattern matching.
"""

import asyncio
import fnmatch
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from rich.console import Console


class LogFileHandler(FileSystemEventHandler):
    """Handle log file events."""

    def __init__(self, pattern: str, callback):
        self.pattern = pattern
        self.callback = callback

    def on_created(self, event):
        """Handle file creation."""
        if not event.is_directory:
            path = Path(event.src_path)
            if fnmatch.fnmatch(path.name, self.pattern):
                self.callback(path)


class FileWatcher:
    """Watch for new log files matching a pattern."""

    def __init__(self, pattern: str, directory: str = ".", recursive: bool = False):
        self.pattern = pattern
        self.directory = Path(directory)
        self.recursive = recursive
        self.console = Console()

    async def watch(self):
        """Start watching for files."""
        observer = Observer()

        def on_file_created(path: Path):
            self.console.print(f"[green]✓[/green] New file: [cyan]{path}[/cyan]")

        handler = LogFileHandler(self.pattern, on_file_created)
        observer.schedule(handler, str(self.directory), recursive=self.recursive)
        observer.start()

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            observer.stop()

        observer.join()
