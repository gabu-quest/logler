"""Log file reading and streaming module."""

import os
import time
from collections import deque
from collections.abc import Iterator
from itertools import islice
from pathlib import Path

from .parser import cut_newline, is_blank_line, read_entry_lines


class CompleteLines:
    """The lines of a growing log file, each handed out once its newline has been written.

    `f` is a handle opened for bytes. Each pass (`for line in lines`) yields the complete
    lines the handle has from where it stands, as text, then stops. The start of a line still
    being written is kept, and the line comes out whole on a later pass: a line is decoded
    only when it is complete, so a character written in two parts is read as one. A byte that
    is not UTF-8 becomes the replacement character. A byte-order mark at the start of the
    file is not part of line 1, whenever it is written.
    """

    def __init__(self, f):
        self._f = f
        self._unfinished = b""
        self._at_file_start = f.tell() == 0

    def __iter__(self):
        for data in iter(self._f.readline, b""):
            if not data.endswith(b"\n"):
                self._unfinished += data
                return
            yield self._text(self._unfinished + data)
            self._unfinished = b""
            self._at_file_start = False

    def unfinished(self) -> str:
        """The start of the line still being written, "" when the file ends in a newline."""
        return self._text(self._unfinished)

    def _text(self, data: bytes) -> str:
        # utf-8-sig drops a byte-order mark, which only the file's first line can have
        return data.decode("utf-8-sig" if self._at_file_start else "utf-8", errors="replace")


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
        (``parser.read_lines``), a blank line left out: ``start_line`` counts from 0 in the
        file's lines."""
        lines_read = 0
        for number, line in read_entry_lines(str(self.file_path)):
            if number - 1 >= start_line:
                yield line
                lines_read += 1

                if max_lines and lines_read >= max_lines:
                    break

    def _read_lines_reverse(
        self, start_line: int = 0, max_lines: int | None = None
    ) -> Iterator[str]:
        """Read lines from the end, cut as ``parser.read_lines`` cuts them, in reverse, a blank
        line left out.

        The file is read backwards one ``buffer_size`` chunk at a time, only as far as the
        lines asked for need. ``start_line`` counts lines of the file from the end, blank ones
        too, as a forward read counts them from the start; ``max_lines`` counts the lines
        given back.
        """
        lines = islice(self._lines_backward(), start_line, None)
        entries = (line for line in lines if not is_blank_line(line))
        yield from islice(entries, max_lines or None)

    def _lines_backward(self) -> Iterator[str]:
        def text(data: bytes, terminated: bool, first: bool) -> str:
            # utf-8-sig drops a byte-order mark, which only line 1 of the file can have
            line = data.decode("utf-8-sig" if first else "utf-8", errors="replace")
            return cut_newline(line + "\n") if terminated else line

        with open(self.file_path, "rb") as f:
            position = f.seek(0, os.SEEK_END)
            # The start of the line being read, as pieces: the piece latest in the file first.
            pieces: list[bytes] = []
            terminated = False  # what follows the file's last "\n" has no newline of its own
            while position > 0:
                size = min(self.buffer_size, position)
                position -= size
                f.seek(position)
                chunk = f.read(size)
                if b"\n" not in chunk:
                    pieces.append(chunk)
                    continue
                head, *rest = chunk.split(b"\n")
                for data in reversed(rest):
                    line = data + b"".join(reversed(pieces))
                    pieces = []
                    if terminated or line:
                        yield text(line, terminated, False)
                    terminated = True
                pieces = [head]
            first_line = text(b"".join(reversed(pieces)), terminated, True)
            if terminated or first_line:  # a byte-order mark and nothing else is no line
                yield first_line

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
            if num_lines > 0:
                yield from reversed(list(self._read_lines_reverse(max_lines=num_lines)))
            return

        # One handle serves the first lines and the follow, so they share one position:
        # the first lines end where the follow begins, at the end of the last complete line.
        with open(self.file_path, "rb") as f:
            complete = CompleteLines(f)
            entries = (text for line in complete if not is_blank_line(text := cut_newline(line)))
            yield from deque(entries, maxlen=num_lines)

            while True:
                for line in complete:
                    if not is_blank_line(text := cut_newline(line)):
                        yield text

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

        matches_found = 0
        for line_num, line in read_entry_lines(str(self.file_path)):
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
        Count the lines of the file, blank ones too: the highest line number in it.

        Returns:
            Number of lines
        """
        count = 0
        with open(self.file_path, "rb") as f:
            for _ in f:
                count += 1
        return count
