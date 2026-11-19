"""Log file reading and streaming module."""

import os
import time
from collections import deque
from collections.abc import Iterator
from pathlib import Path


class CompleteLines:
    """The lines of a growing log file, each handed out once its newline has been written.

    `f` is a handle opened for bytes. Each pass (`for line in lines`) yields the complete
    lines the handle has from where it stands, as text, then stops. The start of a line still
    being written is kept, and the line comes out whole on a later pass: a line is decoded
    only when it is complete, so a character written in two parts is read as one. A byte that
    is not UTF-8 becomes the replacement character.
    """

    def __init__(self, f):
        self._f = f
        self._unfinished = b""

    def __iter__(self):
        for data in iter(self._f.readline, b""):
            if not data.endswith(b"\n"):
                self._unfinished += data
                return
            yield self._text(self._unfinished + data)
            self._unfinished = b""

    def unfinished(self) -> str:
        """The start of the line still being written, "" when the file ends in a newline."""
        return self._text(self._unfinished)

    @staticmethod
    def _text(data: bytes) -> str:
        return data.decode("utf-8", errors="replace")


class LogReader:
    """Efficient log file reader with support for tailing and large files."""

    def __init__(self, file_path: str, buffer_size: int = 8192):
        """
        Initialize the log reader.

        Args:
            file_path: Path to the log file
            buffer_size: Buffer size for reading (default 8KB)
        """
        self.file_path = Path(file_path)
        self.buffer_size = buffer_size

        if not self.file_path.exists():
            raise FileNotFoundError(f"Log file not found: {file_path}")

        if not self.file_path.is_file():
            raise ValueError(f"Not a file: {file_path}")

    def read_lines(
        self, start_line: int = 0, max_lines: int | None = None, reverse: bool = False
    ) -> Iterator[str]:
        """
        Read lines from the log file.

        Args:
            start_line: Line number to start from (0-indexed)
            max_lines: Maximum number of lines to read (None for all)
            reverse: Read lines in reverse order

        Yields:
            Log lines as strings
        """
        if reverse:
            yield from self._read_lines_reverse(start_line, max_lines)
        else:
            yield from self._read_lines_forward(start_line, max_lines)

    def _read_lines_forward(
        self, start_line: int = 0, max_lines: int | None = None
    ) -> Iterator[str]:
        """Read lines forward from the file, cut and numbered as search cuts them
        (``parser.read_lines``): ``start_line`` counts from 0."""
        from .parser import read_lines

        lines_read = 0
        for number, line in read_lines(str(self.file_path)):
            if number - 1 >= start_line:
                yield line
                lines_read += 1

                if max_lines and lines_read >= max_lines:
                    break

    def _read_lines_reverse(
        self, start_line: int = 0, max_lines: int | None = None
    ) -> Iterator[str]:
        """
        Read lines in reverse order using an efficient algorithm.

        This reads the file from the end in chunks to avoid loading
        the entire file into memory.
        """
        with open(self.file_path, "rb") as f:
            # Seek to end of file
            f.seek(0, os.SEEK_END)
            file_size = f.tell()

            # Read in chunks from the end
            buffer = b""
            position = file_size
            lines: list[str] = []

            while position > 0:
                # Determine chunk size
                chunk_size = min(self.buffer_size, position)
                position -= chunk_size

                # Read chunk
                f.seek(position)
                chunk = f.read(chunk_size)

                # Combine with previous buffer
                buffer = chunk + buffer

                # Split into lines
                chunk_lines = buffer.split(b"\n")

                # Keep the first incomplete line in buffer
                buffer = chunk_lines[0]
                chunk_lines = chunk_lines[1:]

                # Add lines in reverse
                for line in reversed(chunk_lines):
                    if line or lines:  # Skip empty lines at the end
                        try:
                            decoded = line.decode("utf-8", errors="replace")
                            lines.append(decoded.rstrip("\r"))
                        except UnicodeDecodeError:
                            continue

            # Add the first line if buffer has content
            if buffer:
                try:
                    decoded = buffer.decode("utf-8", errors="replace")
                    lines.append(decoded.rstrip("\r"))
                except UnicodeDecodeError:
                    pass

            # Apply start_line and max_lines
            lines_to_yield = lines[start_line:]
            if max_lines:
                lines_to_yield = lines_to_yield[:max_lines]

            yield from lines_to_yield

    def tail(
        self, num_lines: int = 10, follow: bool = False, sleep_interval: float = 0.1
    ) -> Iterator[str]:
        """
        Tail the log file (like tail -f).

        Args:
            num_lines: Number of initial lines to show
            follow: If True, continue watching for new lines
            sleep_interval: How long to sleep between checks (seconds)

        Yields:
            Log lines as strings
        """
        if not follow:
            lines = list(self._read_lines_reverse(max_lines=num_lines))
            yield from reversed(lines)
            return

        # One handle serves the first lines and the follow, so they share one position:
        # the first lines end where the follow begins, at the end of the last complete line.
        with open(self.file_path, "rb") as f:
            complete = CompleteLines(f)
            for line in deque(complete, maxlen=num_lines):
                yield line.rstrip("\n\r")

            while True:
                for line in complete:
                    yield line.rstrip("\n\r")

                if os.fstat(f.fileno()).st_size < f.tell():
                    # File was truncated (log rotation), start from beginning
                    f.seek(0)
                    complete = CompleteLines(f)
                else:
                    time.sleep(sleep_interval)

    def search(
        self,
        pattern: str,
        case_sensitive: bool = False,
        regex: bool = False,
        max_lines: int | None = None,
    ) -> Iterator[tuple[int, str]]:
        """
        Search for lines matching a pattern.

        Args:
            pattern: Search pattern (string or regex)
            case_sensitive: Whether search is case-sensitive
            regex: Whether pattern is a regex
            max_lines: Maximum number of matching lines to return

        Yields:
            Tuples of (line_number, line_content)
        """
        import re as regex_module

        def make_regex_matcher(compiled):
            return lambda line: compiled.search(line)

        def make_case_insensitive_matcher(pat):
            return lambda line: pat in line.lower()

        def make_case_sensitive_matcher(pat):
            return lambda line: pat in line

        if regex:
            flags = 0 if case_sensitive else regex_module.IGNORECASE
            compiled_pattern = regex_module.compile(pattern, flags)
            match_func = make_regex_matcher(compiled_pattern)
        else:
            if not case_sensitive:
                pattern = pattern.lower()
                match_func = make_case_insensitive_matcher(pattern)
            else:
                match_func = make_case_sensitive_matcher(pattern)

        with open(self.file_path, encoding="utf-8", errors="replace") as f:
            matches_found = 0

            for line_num, line in enumerate(f, 1):
                line = line.rstrip("\n\r")

                if match_func(line):
                    yield (line_num, line)
                    matches_found += 1

                    if max_lines and matches_found >= max_lines:
                        break

    def get_file_info(self) -> dict:
        """
        Get information about the log file.

        Returns:
            Dictionary with file metadata
        """
        stat = self.file_path.stat()

        return {
            "path": str(self.file_path.absolute()),
            "size": stat.st_size,
            "size_human": self._format_bytes(stat.st_size),
            "modified": stat.st_mtime,
            "created": stat.st_ctime,
        }

    @staticmethod
    def _format_bytes(size: int) -> str:
        """Format bytes to human-readable string."""
        value = float(size)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if value < 1024.0:
                return f"{value:.2f} {unit}"
            value /= 1024.0
        return f"{value:.2f} PB"

    def count_lines(self) -> int:
        """
        Count total number of lines in the file.

        Returns:
            Number of lines
        """
        count = 0
        with open(self.file_path, "rb") as f:
            for _ in f:
                count += 1
        return count
