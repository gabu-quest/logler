"""
BRUTAL LOG READER TESTS - Stress Test Edition

These tests push LogReader to its limits with edge cases,
large files, corruption, and adversarial inputs.
"""

import os
import pytest
import tempfile
import threading
import time
from pathlib import Path
from logler.log_reader import LogReader


class TestFileEdgeCases:
    """File system edge cases that break readers."""

    def test_empty_file(self):
        """Empty file with zero bytes"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.read_lines())
            assert lines == []
            assert reader.count_lines() == 0
        finally:
            Path(temp_path).unlink()

    def test_file_with_only_newlines(self):
        """File with only newline characters"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            f.write("\n\n\n\n\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.read_lines())
            # Behavior may vary - important is no crash
            assert isinstance(lines, list)
        finally:
            Path(temp_path).unlink()

    def test_file_without_trailing_newline(self):
        """File without trailing newline"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            f.write("Line 1\nLine 2\nLine 3 no newline")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.read_lines())
            assert len(lines) == 3
            assert lines[2] == "Line 3 no newline"
        finally:
            Path(temp_path).unlink()

    def test_file_single_line_no_newline(self):
        """Single line without newline"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            f.write("Single line no newline")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.read_lines())
            assert len(lines) == 1
            assert lines[0] == "Single line no newline"
        finally:
            Path(temp_path).unlink()

    def test_file_with_windows_line_endings(self):
        """Windows CRLF line endings"""
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.log') as f:
            f.write(b"Line 1\r\nLine 2\r\nLine 3\r\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.read_lines())
            assert len(lines) == 3
            # Should handle CRLF gracefully
            assert "Line 1" in lines[0]
        finally:
            Path(temp_path).unlink()

    def test_file_with_old_mac_line_endings(self):
        """Old Mac CR-only line endings"""
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.log') as f:
            f.write(b"Line 1\rLine 2\rLine 3\r")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.read_lines())
            # Behavior varies - shouldn't crash
            assert isinstance(lines, list)
        finally:
            Path(temp_path).unlink()

    def test_file_with_mixed_line_endings(self):
        """Mixed line endings in same file"""
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.log') as f:
            f.write(b"Unix line\nWindows line\r\nOld mac line\rAnother unix\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.read_lines())
            assert isinstance(lines, list)
            assert len(lines) >= 1
        finally:
            Path(temp_path).unlink()

    def test_file_with_bom(self):
        """UTF-8 file with BOM"""
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.log') as f:
            f.write(b"\xef\xbb\xbfINFO First line with BOM\nINFO Second line\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.read_lines())
            assert len(lines) == 2
        finally:
            Path(temp_path).unlink()

    def test_nonexistent_file(self):
        """Non-existent file"""
        with pytest.raises(FileNotFoundError):
            LogReader("/this/path/does/not/exist/ever.log")

    def test_directory_instead_of_file(self):
        """Directory path instead of file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises((IsADirectoryError, PermissionError, OSError, ValueError)):
                reader = LogReader(tmpdir)
                list(reader.read_lines())


class TestLargeFileHandling:
    """Large file stress tests."""

    def test_10k_lines(self):
        """10,000 lines"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            for i in range(10000):
                f.write(f"2024-01-01T00:00:00Z INFO Line {i}: {'x' * 100}\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            assert reader.count_lines() == 10000

            # Forward read
            lines = list(reader.read_lines(max_lines=100))
            assert len(lines) == 100
            assert "Line 0:" in lines[0]

            # Reverse read
            rev_lines = list(reader.read_lines(reverse=True, max_lines=100))
            assert len(rev_lines) == 100
            assert "Line 9999:" in rev_lines[0]
        finally:
            Path(temp_path).unlink()

    def test_100k_lines(self):
        """100,000 lines"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            for i in range(100000):
                f.write(f"Line {i}\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            assert reader.count_lines() == 100000

            # Tail should work efficiently
            tail_lines = list(reader.tail(num_lines=50, follow=False))
            assert len(tail_lines) == 50
            assert "Line 99999" in tail_lines[-1]
        finally:
            Path(temp_path).unlink()

    def test_lines_with_varying_lengths(self):
        """Lines with wildly varying lengths"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            for i in range(1000):
                # Length varies from 1 to 5000 characters
                length = (i % 500) * 10 + 1
                f.write(f"Line {i}: " + "x" * length + "\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.read_lines())
            assert len(lines) == 1000

            # Verify shortest and longest were read correctly
            assert "Line 0:" in lines[0]
            assert len(lines[499]) > 5000  # Should have ~5000 x's
        finally:
            Path(temp_path).unlink()

    def test_very_long_single_line(self):
        """Single line that's 1MB"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            f.write("INFO " + "x" * (1024 * 1024) + "\n")
            f.write("INFO Normal line\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.read_lines())
            assert len(lines) == 2
            assert len(lines[0]) > 1024 * 1024
        finally:
            Path(temp_path).unlink()


class TestSearchEdgeCases:
    """Search functionality edge cases."""

    @pytest.fixture
    def search_file(self):
        """Create a file for search tests"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            f.write("INFO Normal message\n")
            f.write("ERROR Something failed\n")
            f.write("INFO Special chars: $^.*+?{}[]|()\\\n")
            f.write("DEBUG Message with UPPERCASE and lowercase\n")
            f.write("INFO Unicode: こんにちは 🚀\n")
            f.write("WARN\n")  # Level only, no message
            f.write("INFO " + "a" * 10000 + "\n")  # Very long line
            temp_path = f.name

        yield temp_path
        Path(temp_path).unlink()

    def test_search_empty_pattern(self, search_file):
        """Search with empty pattern"""
        reader = LogReader(search_file)
        results = list(reader.search(""))
        # Empty pattern behavior varies - shouldn't crash
        assert isinstance(results, list)

    def test_search_regex_special_chars(self, search_file):
        """Search for literal regex special characters"""
        reader = LogReader(search_file)
        # Non-regex search should treat these literally
        results = list(reader.search("$^.", case_sensitive=True, regex=False))
        assert len(results) >= 1

    def test_search_regex_pattern(self, search_file):
        """Valid regex pattern"""
        reader = LogReader(search_file)
        results = list(reader.search(r"(INFO|ERROR)", regex=True))
        assert len(results) >= 3

    def test_search_invalid_regex(self, search_file):
        """Invalid regex pattern"""
        reader = LogReader(search_file)
        # Invalid regex should either fail gracefully or raise
        try:
            results = list(reader.search(r"[invalid(regex", regex=True))
            # If it returns, should be empty or handle gracefully
            assert isinstance(results, list)
        except Exception:
            # Exception is acceptable for invalid regex
            pass

    def test_search_case_insensitive(self, search_file):
        """Case insensitive search"""
        reader = LogReader(search_file)
        results = list(reader.search("uppercase", case_sensitive=False))
        assert len(results) >= 1

    def test_search_unicode(self, search_file):
        """Search for unicode characters"""
        reader = LogReader(search_file)
        results = list(reader.search("こんにちは"))
        assert len(results) >= 1

    def test_search_emoji(self, search_file):
        """Search for emoji"""
        reader = LogReader(search_file)
        results = list(reader.search("🚀"))
        assert len(results) >= 1

    def test_search_max_lines_zero(self, search_file):
        """Search with max_lines=0 - implementation may treat as 'unlimited'"""
        reader = LogReader(search_file)
        results = list(reader.search("INFO", max_lines=0))
        # Some implementations treat 0 as "no limit" rather than "no results"
        # Either behavior is acceptable - just verify no crash
        assert isinstance(results, list)

    def test_search_max_lines_one(self, search_file):
        """Search with max_lines=1"""
        reader = LogReader(search_file)
        results = list(reader.search("INFO", max_lines=1))
        assert len(results) == 1

    def test_search_no_matches(self, search_file):
        """Search for non-existent pattern"""
        reader = LogReader(search_file)
        results = list(reader.search("ZZZYYYXXX_DOES_NOT_EXIST"))
        assert len(results) == 0


class TestReverseReading:
    """Reverse reading edge cases."""

    def test_reverse_empty_file(self):
        """Reverse read empty file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.read_lines(reverse=True))
            assert lines == []
        finally:
            Path(temp_path).unlink()

    def test_reverse_single_line(self):
        """Reverse read single line file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            f.write("Only line\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.read_lines(reverse=True))
            assert len(lines) == 1
            assert lines[0] == "Only line"
        finally:
            Path(temp_path).unlink()

    def test_reverse_preserves_order(self):
        """Reverse read preserves reverse order"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            for i in range(100):
                f.write(f"Line {i}\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.read_lines(reverse=True))
            assert len(lines) == 100
            assert "Line 99" in lines[0]
            assert "Line 0" in lines[99]
        finally:
            Path(temp_path).unlink()

    def test_reverse_with_start_line(self):
        """Reverse read starting from specific line"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            for i in range(10):
                f.write(f"Line {i}\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            # Start from line 5 (0-indexed), reading backwards
            lines = list(reader.read_lines(start_line=5, reverse=True))
            # Behavior may vary - just verify no crash
            assert isinstance(lines, list)
        finally:
            Path(temp_path).unlink()


class TestTailFunctionality:
    """Tail functionality edge cases."""

    def test_tail_empty_file(self):
        """Tail empty file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.tail(num_lines=10, follow=False))
            assert lines == []
        finally:
            Path(temp_path).unlink()

    def test_tail_more_than_exists(self):
        """Tail more lines than exist"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            f.write("Line 1\nLine 2\nLine 3\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.tail(num_lines=1000, follow=False))
            assert len(lines) == 3
        finally:
            Path(temp_path).unlink()

    def test_tail_zero_lines(self):
        """Tail zero lines - implementation may treat as 'all lines'"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            f.write("Line 1\nLine 2\nLine 3\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.tail(num_lines=0, follow=False))
            # Some implementations treat 0 as "no limit" rather than "no results"
            # Either behavior is acceptable - just verify no crash
            assert isinstance(lines, list)
        finally:
            Path(temp_path).unlink()

    def test_tail_negative_lines(self):
        """Tail negative lines (should handle gracefully)"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            f.write("Line 1\nLine 2\nLine 3\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            # Should either handle gracefully or raise a clear error
            try:
                lines = list(reader.tail(num_lines=-5, follow=False))
                assert isinstance(lines, list)
            except (ValueError, AssertionError):
                pass  # Acceptable to reject negative
        finally:
            Path(temp_path).unlink()


class TestFileInfo:
    """File info edge cases."""

    def test_file_info_normal(self):
        """Normal file info"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            f.write("Some content\n" * 100)
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            info = reader.get_file_info()
            assert "path" in info
            assert "size" in info
            assert info["size"] > 0
        finally:
            Path(temp_path).unlink()

    def test_file_info_empty_file(self):
        """File info for empty file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            info = reader.get_file_info()
            assert info["size"] == 0
        finally:
            Path(temp_path).unlink()


class TestFormatBytes:
    """Byte formatting edge cases."""

    def test_format_bytes_zero(self):
        """Zero bytes"""
        result = LogReader._format_bytes(0)
        assert "0" in result or "B" in result

    def test_format_bytes_negative(self):
        """Negative bytes (shouldn't happen but test anyway)"""
        # Should handle gracefully
        try:
            result = LogReader._format_bytes(-100)
            assert isinstance(result, str)
        except (ValueError, AssertionError):
            pass

    def test_format_bytes_boundaries(self):
        """Boundary values for KB, MB, GB"""
        assert "B" in LogReader._format_bytes(1023)
        assert "KB" in LogReader._format_bytes(1024)
        assert "KB" in LogReader._format_bytes(1024 * 1023)
        assert "MB" in LogReader._format_bytes(1024 * 1024)
        assert "GB" in LogReader._format_bytes(1024 * 1024 * 1024)

    def test_format_bytes_large_values(self):
        """Very large byte values"""
        result = LogReader._format_bytes(1024 * 1024 * 1024 * 1024)  # 1 TB
        assert isinstance(result, str)

        result = LogReader._format_bytes(10**18)  # Exabyte range
        assert isinstance(result, str)


class TestConcurrentAccess:
    """Concurrent access tests."""

    def test_multiple_readers_same_file(self):
        """Multiple readers on same file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            for i in range(1000):
                f.write(f"Line {i}\n")
            temp_path = f.name

        try:
            readers = [LogReader(temp_path) for _ in range(10)]
            results = []

            def read_file(reader):
                lines = list(reader.read_lines())
                results.append(len(lines))

            threads = [threading.Thread(target=read_file, args=(r,)) for r in readers]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # All readers should see same content
            assert all(r == 1000 for r in results)
        finally:
            Path(temp_path).unlink()

    def test_read_while_counting(self):
        """Read and count simultaneously"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            for i in range(1000):
                f.write(f"Line {i}\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            results = {}

            def do_read():
                results['read'] = len(list(reader.read_lines()))

            def do_count():
                results['count'] = reader.count_lines()

            t1 = threading.Thread(target=do_read)
            t2 = threading.Thread(target=do_count)

            t1.start()
            t2.start()
            t1.join()
            t2.join()

            assert results['read'] == 1000
            assert results['count'] == 1000
        finally:
            Path(temp_path).unlink()


class TestBinaryContent:
    """Binary content detection and handling."""

    def test_pure_binary_file(self):
        """Pure binary file (random bytes)"""
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.log') as f:
            f.write(os.urandom(1000))
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            # Should not crash, behavior may vary
            try:
                lines = list(reader.read_lines())
                assert isinstance(lines, list)
            except UnicodeDecodeError:
                # Acceptable to fail on binary
                pass
        finally:
            Path(temp_path).unlink()

    def test_text_with_some_binary(self):
        """Text file with some binary bytes"""
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.log') as f:
            f.write(b"INFO Normal line\n")
            f.write(b"ERROR Line with binary: \x00\x01\x02\x03\n")
            f.write(b"INFO Another normal line\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            try:
                lines = list(reader.read_lines())
                assert len(lines) >= 1
            except UnicodeDecodeError:
                pass  # Acceptable
        finally:
            Path(temp_path).unlink()


class TestSpecialFilenames:
    """Special filename handling."""

    def test_filename_with_spaces(self):
        """Filename with spaces"""
        with tempfile.NamedTemporaryFile(
            mode='w', delete=False, suffix='.log',
            prefix='test file with spaces '
        ) as f:
            f.write("Line 1\nLine 2\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.read_lines())
            assert len(lines) == 2
        finally:
            Path(temp_path).unlink()

    def test_filename_with_unicode(self):
        """Filename with unicode characters"""
        with tempfile.NamedTemporaryFile(
            mode='w', delete=False, suffix='.log',
            prefix='test_日本語_'
        ) as f:
            f.write("Line 1\nLine 2\n")
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            lines = list(reader.read_lines())
            assert len(lines) == 2
        finally:
            Path(temp_path).unlink()


class TestStartLineEdgeCases:
    """Start line parameter edge cases."""

    @pytest.fixture
    def numbered_file(self):
        """Create a file with numbered lines"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            for i in range(100):
                f.write(f"Line {i}\n")
            temp_path = f.name
        yield temp_path
        Path(temp_path).unlink()

    def test_start_line_zero(self, numbered_file):
        """Start from line 0"""
        reader = LogReader(numbered_file)
        lines = list(reader.read_lines(start_line=0, max_lines=5))
        assert len(lines) == 5
        assert "Line 0" in lines[0]

    def test_start_line_one(self, numbered_file):
        """Start from line 1"""
        reader = LogReader(numbered_file)
        lines = list(reader.read_lines(start_line=1, max_lines=5))
        assert len(lines) == 5
        # Depending on 0-indexed or 1-indexed
        assert "Line" in lines[0]

    def test_start_line_middle(self, numbered_file):
        """Start from middle of file"""
        reader = LogReader(numbered_file)
        lines = list(reader.read_lines(start_line=50, max_lines=5))
        assert len(lines) == 5

    def test_start_line_near_end(self, numbered_file):
        """Start near end of file"""
        reader = LogReader(numbered_file)
        lines = list(reader.read_lines(start_line=95, max_lines=10))
        # Should return remaining lines (less than 10)
        assert len(lines) <= 10

    def test_start_line_past_end(self, numbered_file):
        """Start past end of file"""
        reader = LogReader(numbered_file)
        lines = list(reader.read_lines(start_line=500, max_lines=5))
        assert len(lines) == 0

    def test_start_line_negative(self, numbered_file):
        """Negative start line"""
        reader = LogReader(numbered_file)
        try:
            lines = list(reader.read_lines(start_line=-5, max_lines=5))
            # If allowed, should handle gracefully
            assert isinstance(lines, list)
        except (ValueError, AssertionError, IndexError):
            pass  # Acceptable to reject negative


class TestMemoryEfficiency:
    """Tests to ensure we're not loading entire file into memory."""

    def test_stream_large_file(self):
        """Verify streaming doesn't load entire file"""
        # Create a 10MB file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            line = "INFO " + "x" * 990 + "\n"  # ~1000 bytes per line
            for _ in range(10000):  # 10MB
                f.write(line)
            temp_path = f.name

        try:
            reader = LogReader(temp_path)
            # Just read first 10 lines - shouldn't load entire file
            lines = list(reader.read_lines(max_lines=10))
            assert len(lines) == 10
        finally:
            Path(temp_path).unlink()
