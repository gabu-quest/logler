"""Tests for log reader."""

import json
import pytest
import tempfile
from pathlib import Path
from logler.log_reader import LogReader


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
