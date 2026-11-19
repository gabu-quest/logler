"""Tests for log reader."""

import json
import tempfile
from pathlib import Path

import pytest

from logler import log_reader
from logler.log_reader import LogReader
from logler.parser import read_lines


class TestLogReader:
    """Test LogReader class."""

    @pytest.fixture
    def sample_log_file(self):
        """Create a temporary log file for testing."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            f.write("Line 1: INFO Test message\n")
            f.write("Line 2: DEBUG Debug message\n")
            f.write("Line 3: ERROR Error message\n")
            f.write("Line 4: WARN Warning message\n")
            f.write("Line 5: INFO Another test\n")
            temp_path = f.name

        yield temp_path

        # Cleanup
        Path(temp_path).unlink()

    @pytest.fixture
    def large_log_file(self):
        """Create a larger temporary log file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            for i in range(1000):
                f.write(f"Line {i}: Test message {i}\n")
            temp_path = f.name

        yield temp_path

        Path(temp_path).unlink()

    def test_init_existing_file(self, sample_log_file):
        """Test initializing with existing file."""
        reader = LogReader(sample_log_file)
        assert reader.file_path == Path(sample_log_file)

    def test_init_nonexistent_file(self):
        """Test initializing with non-existent file."""
        with pytest.raises(FileNotFoundError):
            LogReader("/nonexistent/file.log")

    def test_read_lines_forward(self, sample_log_file):
        """Test reading lines forward."""
        reader = LogReader(sample_log_file)
        lines = list(reader.read_lines())
        assert len(lines) == 5
        assert lines[0] == "Line 1: INFO Test message"
        assert lines[4] == "Line 5: INFO Another test"

    def test_read_lines_with_start(self, sample_log_file):
        """Test reading lines from a start position."""
        reader = LogReader(sample_log_file)
        lines = list(reader.read_lines(start_line=2))
        assert len(lines) == 3
        assert lines[0] == "Line 3: ERROR Error message"

    def test_read_lines_with_max(self, sample_log_file):
        """Test reading limited number of lines."""
        reader = LogReader(sample_log_file)
        lines = list(reader.read_lines(max_lines=3))
        assert len(lines) == 3
        assert lines[2] == "Line 3: ERROR Error message"

    def test_read_lines_reverse(self, sample_log_file):
        """Test reading lines in reverse."""
        reader = LogReader(sample_log_file)
        lines = list(reader.read_lines(reverse=True))
        assert len(lines) == 5
        assert lines[0] == "Line 5: INFO Another test"
        assert lines[4] == "Line 1: INFO Test message"

    def test_read_lines_reverse_with_max(self, sample_log_file):
        """Test reading limited lines in reverse."""
        reader = LogReader(sample_log_file)
        lines = list(reader.read_lines(reverse=True, max_lines=2))
        assert len(lines) == 2
        assert lines[0] == "Line 5: INFO Another test"
        assert lines[1] == "Line 4: WARN Warning message"

    def test_search_simple(self, sample_log_file):
        """Test simple search."""
        reader = LogReader(sample_log_file)
        results = list(reader.search("ERROR"))
        assert len(results) == 1
        assert results[0][0] == 3  # line number
        assert "ERROR" in results[0][1]  # line content

    def test_search_case_sensitive(self, sample_log_file):
        """Test case-sensitive search."""
        reader = LogReader(sample_log_file)
        results = list(reader.search("error", case_sensitive=True))
        assert len(results) == 0  # Should not match ERROR

        results = list(reader.search("ERROR", case_sensitive=True))
        assert len(results) == 1

    def test_search_regex(self, sample_log_file):
        """Test regex search."""
        reader = LogReader(sample_log_file)
        results = list(reader.search(r"Line \d+: (INFO|DEBUG)", regex=True))
        assert len(results) == 3  # Lines 1, 2, and 5

    def test_search_with_max_lines(self, sample_log_file):
        """Test search with max lines limit."""
        reader = LogReader(sample_log_file)
        results = list(reader.search("message", max_lines=2))
        assert len(results) == 2

    def test_count_lines(self, sample_log_file):
        """Test counting lines."""
        reader = LogReader(sample_log_file)
        count = reader.count_lines()
        assert count == 5

    def test_count_lines_large(self, large_log_file):
        """Test counting lines in large file."""
        reader = LogReader(large_log_file)
        count = reader.count_lines()
        assert count == 1000

    def test_get_file_info(self, sample_log_file):
        """Test getting file information."""
        reader = LogReader(sample_log_file)
        info = reader.get_file_info()

        assert "path" in info
        assert "size" in info
        assert "size_human" in info
        assert info["size"] > 0
        assert "B" in info["size_human"] or "KB" in info["size_human"]

    def test_format_bytes(self):
        """Test byte formatting."""
        assert "B" in LogReader._format_bytes(500)
        assert "KB" in LogReader._format_bytes(1024 * 5)
        assert "MB" in LogReader._format_bytes(1024 * 1024 * 5)
        assert "GB" in LogReader._format_bytes(1024 * 1024 * 1024 * 5)

    def test_tail_basic(self, sample_log_file):
        """Test basic tail functionality."""
        reader = LogReader(sample_log_file)
        lines = list(reader.tail(num_lines=3, follow=False))
        assert len(lines) == 3
        assert "Line 3" in lines[0]
        assert "Line 5" in lines[2]

    def test_tail_more_than_file(self, sample_log_file):
        """Test tail with more lines than file has."""
        reader = LogReader(sample_log_file)
        lines = list(reader.tail(num_lines=100, follow=False))
        assert len(lines) == 5

    def test_read_large_file(self, large_log_file):
        """Test reading large file efficiently."""
        reader = LogReader(large_log_file)
        lines = list(reader.read_lines(max_lines=10))
        assert len(lines) == 10
        assert lines[0] == "Line 0: Test message 0"

    def test_reverse_large_file(self, large_log_file):
        """Test reverse reading of large file."""
        reader = LogReader(large_log_file)
        lines = list(reader.read_lines(reverse=True, max_lines=10))
        assert len(lines) == 10
        assert "Line 999" in lines[0]

    def test_glob_tail_handles_multiple_files(self, tmp_path):
        """Tail multiple files from a glob pattern."""
        # create two files
        paths = []
        for idx in range(2):
            p = tmp_path / f"file{idx}.log"
            p.write_text("\n".join([f"A{idx}-{i}" for i in range(5)]))
            paths.append(str(p))

        # use glob
        import glob

        files = glob.glob(str(tmp_path / "*.log"))
        assert len(files) == 2

        # ensure tail returns last lines per file
        for f in files:
            reader = LogReader(f)
            lines = list(reader.tail(num_lines=2, follow=False))
            assert lines[-1].startswith("A")

    def test_tail_glob_on_real_fixtures(self):
        """Tail multiple real log fixtures and verify the last entries."""
        fixtures = sorted(Path("examples/logs").glob("2025-11-0*.log"))
        assert len(fixtures) == 3

        expected_last = {
            "2025-11-01.log": {"service": "api", "message": "log line 199 on day 1"},
            "2025-11-02.log": {"service": "worker", "message": "log line 199 on day 2"},
            "2025-11-03.log": {"service": "api", "message": "log line 199 on day 3"},
        }

        for path in fixtures:
            reader = LogReader(path)
            lines = list(reader.tail(num_lines=1, follow=False))
            assert len(lines) == 1
            entry = json.loads(lines[0])

            assert entry["service"] == expected_last[path.name]["service"]
            assert entry["message"] == expected_last[path.name]["message"]


class TestReadLinesCutsLikeSearch:
    """`LogReader.read_lines` cuts a file the way `parser.read_lines` and the index do."""

    @pytest.fixture
    def odd_file(self, tmp_path):
        path = tmp_path / "odd.log"
        path.write_bytes(b"\xef\xbb\xbfone\rtwo\nthree\r\r\nfour  \n")
        return str(path)

    def test_a_bare_return_does_not_end_a_line_and_a_bom_is_not_text(self, odd_file):
        assert list(LogReader(odd_file).read_lines()) == ["one\rtwo", "three\r", "four  "]

    def test_start_line_and_max_lines_count_those_lines(self, odd_file):
        assert list(LogReader(odd_file).read_lines(start_line=1, max_lines=1)) == ["three\r"]


class TestReverseReadYieldsText:
    """What `read_lines(reverse=True)` yields: `str`, like the forward read, never `bytes`."""

    @pytest.fixture
    def path(self, tmp_path):
        path = tmp_path / "app.log"
        path.write_bytes("alpha\nbeta \xe9\r\ngamma\n".encode())
        return path

    def test_reverse_read_yields_str_lines_in_reverse_order(self, path):
        lines = list(LogReader(path).read_lines(reverse=True))
        assert lines == ["gamma", "beta \xe9", "alpha"]
        assert [type(x) for x in lines] == [str, str, str]

    def test_forward_read_yields_the_same_type(self, path):
        lines = list(LogReader(path).read_lines())
        assert [type(x) for x in lines] == [str, str, str]


ODD_BYTES = (
    b"\xef\xbb\xbfone\rtwo\r\n"  # byte-order mark, a lone return inside a line, CRLF
    b"spaced  \n"
    b"bad\xffbyte\n"
    b"\xe6\x97\xa5\xe6\x9c\xac\r\n"  # multi-byte characters
    b"end\r\r\n"
    b"last"  # no final newline
)
ODD_LINES = ["one\rtwo", "spaced  ", "bad\ufffdbyte", "\u65e5\u672c", "end\r", "last"]


def _parser_lines(path):
    return [line for _, line in read_lines(str(path))]


class _Stop(Exception):
    pass


def _follow(path, count, writes=()):
    """The lines `tail(follow=True)` yields: the last `count` the file has, then what the
    `writes` bring. Each time the follow finds nothing new and waits, the next of `writes`
    is done, a pair of an open mode ("ab" appends, "wb" replaces the file) and the bytes;
    the wait after the last one ends the follow."""
    out = []
    pending = list(writes)

    def wait(_seconds):
        if not pending:
            raise _Stop
        mode, data = pending.pop(0)
        with open(path, mode) as f:
            f.write(data)

    original = log_reader.time.sleep
    log_reader.time.sleep = wait
    try:
        for line in LogReader(path).tail(num_lines=count, follow=True):
            out.append(line)
    except _Stop:
        pass
    finally:
        log_reader.time.sleep = original
    return out


class TestEveryReaderCutsOneWay:
    """The forward read, the reverse read, tail, tail(follow=True) and search give the text
    `parser.read_lines` gives, for a file of every odd ending."""

    @pytest.fixture
    def odd_file(self, tmp_path):
        path = tmp_path / "odd.log"
        path.write_bytes(ODD_BYTES)
        return path

    def test_the_parser_gives_the_expected_lines(self, odd_file):
        assert _parser_lines(odd_file) == ODD_LINES

    def test_forward(self, odd_file):
        assert list(LogReader(odd_file).read_lines()) == ODD_LINES

    def test_reverse(self, odd_file):
        assert list(LogReader(odd_file).read_lines(reverse=True)) == ODD_LINES[::-1]

    def test_tail(self, odd_file):
        assert list(LogReader(odd_file).tail(num_lines=10)) == ODD_LINES

    def test_search(self, odd_file):
        found = list(LogReader(odd_file).search("", regex=True))
        assert found == list(enumerate(ODD_LINES, start=1))

    def test_tail_follow_gives_every_complete_line(self, tmp_path):
        path = tmp_path / "odd_nl.log"
        path.write_bytes(ODD_BYTES + b"\n")
        assert _follow(path, 10) == ODD_LINES

    def test_tail_follow_last_lines_only(self, tmp_path):
        path = tmp_path / "odd_nl.log"
        path.write_bytes(ODD_BYTES + b"\n")
        assert _follow(path, 2) == ODD_LINES[-2:]


class TestEmptyAndSingleLineFiles:
    @pytest.mark.parametrize(
        "data,lines",
        [
            (b"", []),
            (b"solo", ["solo"]),
            (b"\n", [""]),
            (b"\xef\xbb\xbf", []),  # a byte-order mark and nothing else
            (b"\xef\xbb\xbf\n", [""]),
            (b"\xef\xbb\xbfsolo", ["solo"]),
        ],
    )
    def test_every_reader_agrees(self, tmp_path, data, lines):
        path = tmp_path / "tiny.log"
        path.write_bytes(data)
        reader = LogReader(path)
        assert _parser_lines(path) == lines
        assert list(reader.read_lines()) == lines
        assert list(reader.read_lines(reverse=True)) == lines
        assert list(reader.tail(num_lines=5)) == lines
        assert [text for _, text in reader.search("", regex=True)] == lines

    def test_a_lone_unterminated_line_is_not_followed_until_complete(self, tmp_path):
        path = tmp_path / "tiny.log"
        path.write_bytes(b"solo")
        assert _follow(path, 5) == []

    def test_a_line_written_in_two_parts_is_followed_once_whole(self, tmp_path):
        path = tmp_path / "grow.log"
        path.write_bytes(b"first\n")
        writes = [("ab", b"sec"), ("ab", b"ond\nthird\n")]
        assert _follow(path, 5, writes) == ["first", "second", "third"]

    @pytest.mark.parametrize("at_open", [b"", b"\xef\xbb"])
    def test_a_byte_order_mark_written_after_the_follow_began_is_not_part_of_line_one(
        self, tmp_path, at_open
    ):
        path = tmp_path / "late.log"
        path.write_bytes(at_open)
        rest = (b"\xef\xbb\xbf" + b"hello\nworld\n")[len(at_open) :]
        assert _follow(path, 5, [("ab", rest)]) == ["hello", "world"]

    def test_a_file_replaced_by_a_shorter_one_is_followed_from_its_start(self, tmp_path):
        path = tmp_path / "rotated.log"
        path.write_bytes(b"a long first line\n")
        writes = [("wb", b"\xef\xbb\xbfnew\n")]
        assert _follow(path, 5, writes) == ["a long first line", "new"]

    def test_tail_zero_gives_no_line(self, tmp_path):
        path = tmp_path / "three.log"
        path.write_bytes(b"a\nb\nc\n")
        assert list(LogReader(path).tail(num_lines=0)) == []
        assert _follow(path, 0) == []

    def test_max_lines_larger_than_the_file(self, tmp_path):
        path = tmp_path / "three.log"
        path.write_bytes(b"a\nb\nc\n")
        assert list(LogReader(path).read_lines(reverse=True, max_lines=99)) == ["c", "b", "a"]

    def test_start_line_skips_from_the_end(self, tmp_path):
        path = tmp_path / "three.log"
        path.write_bytes(b"a\nb\nc\n")
        assert list(LogReader(path).read_lines(reverse=True, start_line=1, max_lines=1)) == ["b"]


class TestReverseReadChunkBorders:
    """A chunk border falls inside a multi-byte character, inside CRLF, and a line is
    longer than a chunk: the lines are always the parser's, reversed."""

    @pytest.mark.parametrize("buffer_size", [1, 2, 3, 4, 5, 7, 8, 13, 64, 8192])
    def test_every_chunk_size_gives_the_parser_lines_reversed(self, tmp_path, buffer_size):
        path = tmp_path / "odd.log"
        path.write_bytes(ODD_BYTES + b"\n\n" + "x\u00e9\U0001f600".encode() * 20 + b"\r\nz\r\n")
        reader = LogReader(path, buffer_size=buffer_size)
        assert list(reader.read_lines(reverse=True)) == _parser_lines(path)[::-1]
        assert list(reader.tail(num_lines=3)) == _parser_lines(path)[-3:]

    def test_a_chunk_border_between_the_return_and_the_newline(self, tmp_path):
        path = tmp_path / "crlf.log"
        path.write_bytes(b"aaaa\r\nbbbb\r\n")
        # one byte a chunk, so every "\r" and its "\n" are read apart
        assert list(LogReader(path, buffer_size=1).read_lines(reverse=True)) == ["bbbb", "aaaa"]

    def test_a_line_longer_than_one_chunk(self, tmp_path):
        path = tmp_path / "long.log"
        path.write_bytes(b"first\n" + b"y" * 100 + b"\nlast\n")
        lines = list(LogReader(path, buffer_size=8).read_lines(reverse=True))
        assert lines == ["last", "y" * 100, "first"]


def _make_big_file(path):
    """About 50 MB: 100-byte lines, the last ten of them numbered 'tail-0' to 'tail-9'."""
    block = b"".join(b"line %04d " % i + b"x" * 89 + b"\n" for i in range(1000))
    with open(path, "wb") as f:
        for _ in range(525):
            f.write(block)
        for i in range(10):
            f.write(b"tail-%d\n" % i)
    assert path.stat().st_size > 50_000_000


class _CountingFile:
    def __init__(self, f, counter):
        self._f = f
        self._counter = counter

    def read(self, *args):
        data = self._f.read(*args)
        self._counter.append(len(data))
        return data

    def __getattr__(self, name):
        return getattr(self._f, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._f.__exit__(*exc)


class TestReverseReadStopsEarly:
    @pytest.fixture
    def big(self, tmp_path):
        path = tmp_path / "big.log"
        _make_big_file(path)
        return path

    @pytest.fixture
    def counter(self, monkeypatch):
        counts: list[int] = []
        real_open = open

        def counting_open(*args, **kwargs):
            return _CountingFile(real_open(*args, **kwargs), counts)

        monkeypatch.setattr(log_reader, "open", counting_open, raising=False)
        return counts

    def test_the_last_ten_lines_read_under_a_megabyte(self, big, counter):
        lines = list(LogReader(big).read_lines(reverse=True, max_lines=10))
        assert lines == [f"tail-{i}" for i in range(9, -1, -1)]
        assert sum(counter) < 1_000_000

    def test_tail_reads_under_a_megabyte(self, big, counter):
        lines = list(LogReader(big).tail(num_lines=10))
        assert lines == [f"tail-{i}" for i in range(10)]
        assert sum(counter) < 1_000_000

    def test_a_file_of_one_line_is_read_back_whole(self, tmp_path):
        path = tmp_path / "one.log"
        path.write_bytes(b"z" * 50_000_000)
        lines = list(LogReader(path).tail(num_lines=1))
        assert [len(x) for x in lines] == [50_000_000]
