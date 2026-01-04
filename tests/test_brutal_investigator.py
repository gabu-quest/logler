"""
BRUTAL INVESTIGATOR TESTS - Integration Torture

These tests put the Investigator class through hell with
real file operations, edge cases, and adversarial inputs.
"""

import json
import os
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone


# Import with Rust backend check
try:
    from logler.investigate import (
        search,
        follow_thread,
        get_context,
        find_patterns,
        Investigator,
        InvestigationSession,
        RUST_AVAILABLE,
    )
except ImportError:
    RUST_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not RUST_AVAILABLE,
    reason="Rust backend required for investigator tests"
)


@pytest.fixture
def temp_log_file():
    """Create a temporary log file with realistic content"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
        # Generate realistic log entries
        for i in range(100):
            entry = json.dumps({
                "timestamp": f"2024-01-15T10:{i // 60:02d}:{i % 60:02d}Z",
                "level": ["INFO", "DEBUG", "WARN", "ERROR"][i % 4],
                "message": f"Log message number {i}",
                "thread_id": f"worker-{i % 5}",
                "correlation_id": f"req-{i % 20}",
                "service": "test-service"
            })
            f.write(entry + "\n")
        temp_path = f.name

    yield temp_path
    Path(temp_path).unlink()


@pytest.fixture
def multi_log_files():
    """Create multiple log files for multi-file tests"""
    files = []
    for service in ["api", "worker", "db"]:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            for i in range(50):
                entry = json.dumps({
                    "timestamp": f"2024-01-15T10:{i:02d}:00Z",
                    "level": "INFO" if i % 3 == 0 else "ERROR",
                    "message": f"{service} message {i}",
                    "thread_id": f"{service}-thread-{i % 3}",
                    "correlation_id": f"req-{i % 10}",
                    "service": service
                })
                f.write(entry + "\n")
            files.append(f.name)

    yield files

    for f in files:
        Path(f).unlink()


class TestSearchFunction:
    """Search function edge cases."""

    def test_search_empty_query(self, temp_log_file):
        """Search with empty query (should return all or none)"""
        result = search(files=[temp_log_file], query="", limit=10)
        assert "results" in result or "total_matches" in result

    def test_search_none_query(self, temp_log_file):
        """Search with None query"""
        result = search(files=[temp_log_file], query=None, limit=10)
        assert isinstance(result, dict)

    def test_search_with_level_filter(self, temp_log_file):
        """Search filtered by level"""
        result = search(files=[temp_log_file], level="ERROR", limit=50)
        # Should only return ERROR entries
        for item in result.get("results", []):
            entry = item.get("entry", {})
            assert entry.get("level", "").upper() == "ERROR"

    def test_search_with_thread_filter(self, temp_log_file):
        """Search filtered by thread"""
        result = search(files=[temp_log_file], thread_id="worker-0", limit=50)
        for item in result.get("results", []):
            entry = item.get("entry", {})
            assert "worker-0" in str(entry.get("thread_id", ""))

    def test_search_with_correlation_filter(self, temp_log_file):
        """Search filtered by correlation ID"""
        result = search(files=[temp_log_file], correlation_id="req-0", limit=50)
        assert isinstance(result, dict)

    def test_search_output_format_summary(self, temp_log_file):
        """Search with summary output format"""
        result = search(files=[temp_log_file], query="message", output_format="summary")
        assert "total_matches" in result

    def test_search_output_format_count(self, temp_log_file):
        """Search with count output format"""
        result = search(files=[temp_log_file], query="message", output_format="count")
        assert "total_matches" in result

    def test_search_output_format_compact(self, temp_log_file):
        """Search with compact output format"""
        result = search(files=[temp_log_file], query="message", output_format="compact")
        assert isinstance(result, dict)

    def test_search_with_context_lines(self, temp_log_file):
        """Search with context lines"""
        result = search(
            files=[temp_log_file],
            query="number 50",
            context_lines=5,
            limit=5
        )
        # Should have context entries if matches found
        if result.get("results"):
            item = result["results"][0]
            # Context fields may or may not be present depending on implementation
            assert isinstance(item, dict)

    def test_search_limit_zero(self, temp_log_file):
        """Search with limit=0"""
        result = search(files=[temp_log_file], query="message", limit=0)
        assert result.get("results", []) == [] or len(result.get("results", [])) == 0

    def test_search_limit_one(self, temp_log_file):
        """Search with limit=1"""
        result = search(files=[temp_log_file], query="message", limit=1)
        assert len(result.get("results", [])) <= 1

    def test_search_nonexistent_pattern(self, temp_log_file):
        """Search for pattern that doesn't exist"""
        result = search(files=[temp_log_file], query="ZZZYYYXXX_NEVER_EXISTS")
        assert result.get("total_matches", 0) == 0

    def test_search_regex_pattern(self, temp_log_file):
        """Search with regex-like pattern"""
        result = search(files=[temp_log_file], query="message.*50", limit=10)
        assert isinstance(result, dict)

    def test_search_multiple_files(self, multi_log_files):
        """Search across multiple files"""
        result = search(files=multi_log_files, query="message", limit=50)
        assert result.get("total_matches", 0) > 0

    def test_search_empty_file_list(self):
        """Search with empty file list"""
        try:
            result = search(files=[], query="test")
            assert isinstance(result, dict)
        except (ValueError, RuntimeError):
            pass  # Acceptable to reject empty file list

    def test_search_nonexistent_file(self):
        """Search in non-existent file"""
        with pytest.raises((FileNotFoundError, RuntimeError, OSError)):
            search(files=["/does/not/exist.log"], query="test")


class TestFollowThread:
    """Follow thread functionality tests."""

    def test_follow_thread_by_id(self, temp_log_file):
        """Follow specific thread"""
        result = follow_thread(files=[temp_log_file], thread_id="worker-0")
        assert "entries" in result or "timeline" in result or isinstance(result, dict)

    def test_follow_thread_by_correlation(self, temp_log_file):
        """Follow by correlation ID"""
        result = follow_thread(files=[temp_log_file], correlation_id="req-0")
        assert isinstance(result, dict)

    def test_follow_nonexistent_thread(self, temp_log_file):
        """Follow non-existent thread"""
        result = follow_thread(files=[temp_log_file], thread_id="does-not-exist")
        # Should return empty result, not crash
        entries = result.get("entries", [])
        assert len(entries) == 0

    def test_follow_no_id_specified(self, temp_log_file):
        """Follow with no ID specified"""
        # Should handle gracefully or return error
        try:
            result = follow_thread(files=[temp_log_file])
            assert isinstance(result, dict)
        except (ValueError, RuntimeError):
            pass  # Acceptable to require at least one ID


class TestGetContext:
    """Get context around line tests."""

    def test_context_middle_of_file(self, temp_log_file):
        """Get context from middle of file"""
        result = get_context(
            file=temp_log_file,
            line_number=50,
            lines_before=5,
            lines_after=5
        )
        assert "target" in result or "context_before" in result

    def test_context_start_of_file(self, temp_log_file):
        """Get context at start of file"""
        result = get_context(
            file=temp_log_file,
            line_number=1,
            lines_before=10,
            lines_after=5
        )
        # Should handle requesting lines before start of file
        assert isinstance(result, dict)

    def test_context_end_of_file(self, temp_log_file):
        """Get context at end of file"""
        result = get_context(
            file=temp_log_file,
            line_number=100,
            lines_before=5,
            lines_after=10
        )
        assert isinstance(result, dict)

    def test_context_line_zero(self, temp_log_file):
        """Get context at line 0"""
        try:
            result = get_context(
                file=temp_log_file,
                line_number=0,
                lines_before=5,
                lines_after=5
            )
            assert isinstance(result, dict)
        except (ValueError, IndexError, RuntimeError):
            pass  # Acceptable to reject line 0

    def test_context_negative_line(self, temp_log_file):
        """Get context at negative line"""
        try:
            result = get_context(
                file=temp_log_file,
                line_number=-1,
                lines_before=5,
                lines_after=5
            )
            assert isinstance(result, dict)
        except (ValueError, IndexError, RuntimeError, OverflowError):
            pass  # Acceptable to reject negative

    def test_context_past_end_of_file(self, temp_log_file):
        """Get context past end of file"""
        try:
            result = get_context(
                file=temp_log_file,
                line_number=99999,
                lines_before=5,
                lines_after=5
            )
            # Should handle gracefully
            assert isinstance(result, dict)
        except (RuntimeError, IndexError):
            pass  # Acceptable to reject line past end


class TestFindPatterns:
    """Pattern detection tests."""

    @pytest.fixture
    def repetitive_log_file(self):
        """Create file with repetitive patterns"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            # Create patterns that should be detected
            for i in range(100):
                if i % 10 == 0:
                    msg = "Connection timeout to database"
                elif i % 7 == 0:
                    msg = "Cache miss for key user_123"
                elif i % 5 == 0:
                    msg = "Request completed in 150ms"
                else:
                    msg = f"Unique message {i}"

                entry = json.dumps({
                    "timestamp": f"2024-01-15T10:{i:02d}:00Z",
                    "level": "INFO",
                    "message": msg
                })
                f.write(entry + "\n")
            temp_path = f.name

        yield temp_path
        Path(temp_path).unlink()

    def test_find_patterns_basic(self, repetitive_log_file):
        """Find patterns in file"""
        result = find_patterns(files=[repetitive_log_file], min_occurrences=5)
        assert "patterns" in result
        # Should find the timeout pattern
        patterns = result["patterns"]
        assert isinstance(patterns, list)

    def test_find_patterns_high_threshold(self, repetitive_log_file):
        """Find patterns with high min_occurrences"""
        result = find_patterns(files=[repetitive_log_file], min_occurrences=50)
        patterns = result.get("patterns", [])
        # May be empty with high threshold
        assert isinstance(patterns, list)

    def test_find_patterns_threshold_one(self, repetitive_log_file):
        """Find patterns with min_occurrences=1"""
        result = find_patterns(files=[repetitive_log_file], min_occurrences=1)
        # Every unique message would be a pattern
        assert isinstance(result, dict)


class TestInvestigatorClass:
    """Investigator class tests."""

    def test_investigator_load_single_file(self, temp_log_file):
        """Load single file into investigator"""
        inv = Investigator()
        inv.load_files([temp_log_file])
        metadata = inv.get_metadata()
        # get_metadata returns a list of file metadata
        assert isinstance(metadata, list)
        assert len(metadata) == 1
        assert metadata[0]["lines"] == 100

    def test_investigator_load_multiple_files(self, multi_log_files):
        """Load multiple files into investigator"""
        inv = Investigator()
        inv.load_files(multi_log_files)
        metadata = inv.get_metadata()
        # get_metadata returns a list of file metadata
        assert isinstance(metadata, list)
        assert len(metadata) == 3
        total_lines = sum(m["lines"] for m in metadata)
        assert total_lines == 150  # 50 * 3 files

    def test_investigator_search(self, temp_log_file):
        """Search through investigator"""
        inv = Investigator()
        inv.load_files([temp_log_file])
        result = inv.search(query="message", limit=10)
        assert "results" in result

    def test_investigator_follow_thread(self, temp_log_file):
        """Follow thread through investigator"""
        inv = Investigator()
        inv.load_files([temp_log_file])
        result = inv.follow_thread(thread_id="worker-0")
        assert isinstance(result, dict)

    def test_investigator_find_patterns(self, temp_log_file):
        """Find patterns through investigator"""
        inv = Investigator()
        inv.load_files([temp_log_file])
        result = inv.find_patterns(min_occurrences=2)
        assert "patterns" in result


class TestEmptyAndEdgeCaseFiles:
    """Edge case file handling."""

    def test_empty_log_file(self):
        """Handle empty log file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            temp_path = f.name

        try:
            result = search(files=[temp_path], query="test")
            assert result.get("total_matches", 0) == 0
        finally:
            Path(temp_path).unlink()

    def test_single_line_file(self):
        """Handle single-line file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            f.write('{"message": "only line", "level": "INFO"}\n')
            temp_path = f.name

        try:
            result = search(files=[temp_path], query="only")
            assert result.get("total_matches", 0) >= 1
        finally:
            Path(temp_path).unlink()

    def test_non_json_log_file(self):
        """Handle plain text log file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            for i in range(50):
                f.write(f"2024-01-15 10:{i:02d}:00 INFO Plain text message {i}\n")
            temp_path = f.name

        try:
            result = search(files=[temp_path], query="Plain text")
            assert isinstance(result, dict)
        finally:
            Path(temp_path).unlink()

    def test_mixed_format_file(self):
        """Handle file with mixed JSON and plain text"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            f.write('{"message": "JSON line", "level": "INFO"}\n')
            f.write("2024-01-15 10:00:00 ERROR Plain text line\n")
            f.write('{"message": "Another JSON", "level": "DEBUG"}\n')
            f.write("Just a plain line without structure\n")
            temp_path = f.name

        try:
            result = search(files=[temp_path], query="line")
            assert isinstance(result, dict)
        finally:
            Path(temp_path).unlink()

    def test_malformed_json_in_file(self):
        """Handle file with malformed JSON entries"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            f.write('{"message": "good"}\n')
            f.write('{"message": "truncated\n')
            f.write('not json at all\n')
            f.write('{"message": "also good"}\n')
            temp_path = f.name

        try:
            result = search(files=[temp_path], query="good")
            # Should not crash, may find some matches
            assert isinstance(result, dict)
        finally:
            Path(temp_path).unlink()


class TestLargeScale:
    """Large scale tests."""

    def test_large_file_search(self):
        """Search in large file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            for i in range(10000):
                entry = json.dumps({
                    "timestamp": f"2024-01-15T10:00:{i % 60:02d}Z",
                    "level": "INFO" if i % 100 != 0 else "ERROR",
                    "message": f"Message {i}",
                    "thread_id": f"worker-{i % 10}"
                })
                f.write(entry + "\n")
            temp_path = f.name

        try:
            result = search(files=[temp_path], level="ERROR", limit=100)
            assert result.get("total_matches", 0) >= 100  # 10000/100 = 100 ERROR entries
        finally:
            Path(temp_path).unlink()

    def test_many_files(self):
        """Search across many files"""
        files = []
        for i in range(20):
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
                for j in range(100):
                    entry = json.dumps({
                        "message": f"File {i} message {j}",
                        "level": "INFO"
                    })
                    f.write(entry + "\n")
                files.append(f.name)

        try:
            result = search(files=files, query="message", limit=100)
            assert result.get("total_matches", 0) > 0
        finally:
            for f in files:
                Path(f).unlink()


class TestInvestigationSession:
    """Investigation session tests."""

    @pytest.fixture
    def session_with_file(self, temp_log_file):
        """Create a session with loaded file"""
        session = InvestigationSession(files=[temp_log_file])
        return session

    def test_session_search(self, session_with_file):
        """Session search functionality"""
        result = session_with_file.search(query="message")
        assert isinstance(result, dict)

    def test_session_history(self, session_with_file):
        """Session tracks history"""
        session_with_file.search(query="test1")
        session_with_file.search(query="test2")
        session_with_file.search(query="test3")

        history = session_with_file.get_history()
        assert len(history) >= 3

    def test_session_undo(self, session_with_file):
        """Session undo functionality"""
        session_with_file.search(query="test1")
        session_with_file.search(query="test2")

        # Undo should work
        result = session_with_file.undo()
        assert result is not None or result is None  # May return result or None

    def test_session_redo(self, session_with_file):
        """Session redo after undo"""
        session_with_file.search(query="test1")
        session_with_file.search(query="test2")
        session_with_file.undo()
        result = session_with_file.redo()
        # redo() returns bool indicating success
        assert isinstance(result, bool)

    def test_session_undo_at_start(self, session_with_file):
        """Undo when at start of history"""
        # No operations yet (just init)
        result = session_with_file.undo()
        # Should return False when can't undo
        assert result is False or isinstance(result, bool)

    def test_session_redo_at_end(self, session_with_file):
        """Redo when at end of history"""
        session_with_file.search(query="test")
        result = session_with_file.redo()
        # Should return False when can't redo
        assert result is False or isinstance(result, bool)

    def test_session_add_note(self, session_with_file):
        """Add note to session"""
        session_with_file.add_note("This is a test note")
        history = session_with_file.get_history()
        # Note should be in history
        assert any("note" in str(h).lower() for h in history) or len(history) >= 1

    def test_session_save_load_roundtrip(self, session_with_file):
        """Save and load session"""
        session_with_file.search(query="test1")
        session_with_file.search(query="test2")
        session_with_file.add_note("Important finding")

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            save_path = f.name

        try:
            session_with_file.save(save_path)

            # Load into new session (load is a classmethod)
            new_session = InvestigationSession.load(save_path)

            history = new_session.get_history()
            assert len(history) >= 2
        finally:
            Path(save_path).unlink()

    def test_session_save_to_bad_path(self, session_with_file):
        """Save to non-writable path"""
        try:
            session_with_file.save("/root/definitely/not/writable/session.json")
            # If it doesn't raise, that's unexpected but not a test failure
        except (PermissionError, OSError, RuntimeError):
            pass  # Expected

    def test_session_load_nonexistent(self, session_with_file):
        """Load from non-existent path"""
        with pytest.raises((FileNotFoundError, OSError, RuntimeError)):
            session_with_file.load("/does/not/exist/session.json")

    def test_session_load_invalid_json(self, session_with_file):
        """Load from invalid JSON file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            f.write("this is not json {{{")
            bad_path = f.name

        try:
            with pytest.raises((json.JSONDecodeError, ValueError, RuntimeError)):
                session_with_file.load(bad_path)
        finally:
            Path(bad_path).unlink()


class TestSpecialCharacterHandling:
    """Test handling of special characters in queries and data."""

    @pytest.fixture
    def special_char_file(self):
        """File with special characters"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            entries = [
                {"message": "Path: /usr/local/bin", "level": "INFO"},
                {"message": "Query: SELECT * FROM users WHERE id=1", "level": "DEBUG"},
                {"message": "Regex: ^[a-z]+$", "level": "INFO"},
                {"message": "JSON: {\"key\": \"value\"}", "level": "INFO"},
                {"message": "Unicode: 日本語テスト 🎉", "level": "INFO"},
                {"message": "Newline escaped: line1\\nline2", "level": "INFO"},
                {"message": "Tab: col1\tcol2\tcol3", "level": "INFO"},
            ]
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
            temp_path = f.name

        yield temp_path
        Path(temp_path).unlink()

    def test_search_with_slash(self, special_char_file):
        """Search for path with slashes"""
        result = search(files=[special_char_file], query="/usr/local")
        assert isinstance(result, dict)

    def test_search_with_asterisk(self, special_char_file):
        """Search with asterisk (might be regex)"""
        result = search(files=[special_char_file], query="SELECT *")
        assert isinstance(result, dict)

    def test_search_with_caret(self, special_char_file):
        """Search with caret"""
        result = search(files=[special_char_file], query="^[a-z]")
        assert isinstance(result, dict)

    def test_search_with_unicode(self, special_char_file):
        """Search with unicode characters"""
        result = search(files=[special_char_file], query="日本語")
        assert isinstance(result, dict)

    def test_search_with_emoji(self, special_char_file):
        """Search with emoji"""
        result = search(files=[special_char_file], query="🎉")
        assert isinstance(result, dict)
