"""
BRUTAL INVESTIGATOR TESTS - Integration Torture

These tests put the Investigator class through hell with
real file operations, edge cases, and adversarial inputs.
"""

import json
import pytest
import tempfile
from pathlib import Path


# Import with Rust backend check
try:
    from logler.investigate import (
        search,
        follow_thread,
        get_context,
        Investigator,
        InvestigationSession,
        RUST_AVAILABLE,
    )
except ImportError as e:
    if "logler_rs" in str(e):
        RUST_AVAILABLE = False
    else:
        raise


pytestmark = pytest.mark.skipif(
    not RUST_AVAILABLE, reason="Rust backend required for investigator tests"
)


@pytest.fixture
def temp_log_file():
    """Create a temporary log file with realistic content"""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        # Generate realistic log entries
        for i in range(100):
            entry = json.dumps(
                {
                    "timestamp": f"2024-01-15T10:{i // 60:02d}:{i % 60:02d}Z",
                    "level": ["INFO", "DEBUG", "WARN", "ERROR"][i % 4],
                    "message": f"Log message number {i}",
                    "thread_id": f"worker-{i % 5}",
                    "correlation_id": f"req-{i % 20}",
                    "service": "test-service",
                }
            )
            f.write(entry + "\n")
        temp_path = f.name

    yield temp_path
    Path(temp_path).unlink()


@pytest.fixture
def multi_log_files():
    """Create multiple log files for multi-file tests"""
    files = []
    for service in ["api", "worker", "db"]:
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            for i in range(50):
                entry = json.dumps(
                    {
                        "timestamp": f"2024-01-15T10:{i:02d}:00Z",
                        "level": "INFO" if i % 3 == 0 else "ERROR",
                        "message": f"{service} message {i}",
                        "thread_id": f"{service}-thread-{i % 3}",
                        "correlation_id": f"req-{i % 10}",
                        "service": service,
                    }
                )
                f.write(entry + "\n")
            files.append(f.name)

    yield files

    for f in files:
        Path(f).unlink()


class TestSearchFunction:
    """Search function edge cases."""

    def test_search_empty_query(self, temp_log_file):
        """Search with empty query - should return entries (matches everything)"""
        result = search(files=[temp_log_file], query="", limit=10)
        # Must have results structure
        assert "results" in result, "Search result must have 'results' key"
        assert "total_matches" in result, "Search result must have 'total_matches' key"
        # Empty query should match all 100 entries
        assert result["total_matches"] == 100, "Empty query should match all entries"
        assert len(result["results"]) == 10, "With limit=10, should return 10 results"

    def test_search_none_query(self, temp_log_file):
        """Search with None query - should return all entries"""
        result = search(files=[temp_log_file], query=None, limit=10)
        # Must have results structure
        assert "results" in result, "Search result must have 'results' key"
        assert "total_matches" in result, "Search result must have 'total_matches' key"
        # None query should match all 100 entries
        assert result["total_matches"] == 100, "None query should match all entries"
        assert "error" not in result

    def test_search_with_level_filter(self, temp_log_file):
        """Search filtered by level - should return only ERROR entries"""
        result = search(files=[temp_log_file], level="ERROR", limit=50)
        results = result.get("results", [])
        # MUST have results - ERROR appears every 4th entry (25 out of 100)
        assert len(results) > 0, "Should find ERROR entries in log file"
        # All returned entries should be ERROR level
        for item in results:
            entry = item.get("entry", {})
            assert entry.get("level", "").upper() == "ERROR"

    def test_search_with_thread_filter(self, temp_log_file):
        """Search filtered by thread - should return only matching thread entries"""
        result = search(files=[temp_log_file], thread_id="worker-0", limit=50)
        results = result.get("results", [])
        # MUST have results - worker-0 appears every 5th entry (20 out of 100)
        assert len(results) > 0, "Should find entries for worker-0"
        # All returned entries should have matching thread_id
        for item in results:
            entry = item.get("entry", {})
            assert "worker-0" in str(entry.get("thread_id", ""))

    def test_search_with_correlation_filter(self, temp_log_file):
        """Search filtered by correlation ID - should return matching entries"""
        result = search(files=[temp_log_file], correlation_id="req-0", limit=50)
        assert "results" in result, "Search result must have 'results' key"
        # req-0 appears in entries 0, 20, 40, 60, 80 (i % 20 == 0) = 5 entries
        assert result["total_matches"] == 5, "req-0 should appear in 5 entries"
        assert len(result["results"]) == 5
        # ALL results must match the correlation filter
        for item in result["results"]:
            entry = item.get("entry", {})
            assert entry.get("correlation_id") == "req-0"

    def test_search_output_format_summary(self, temp_log_file):
        """Search with summary output format - should include match count"""
        result = search(files=[temp_log_file], query="message", output_format="summary")
        assert "total_matches" in result
        # "message" appears in every entry, should have many matches
        assert result["total_matches"] > 0, "Summary should show matches for 'message'"

    def test_search_output_format_count(self, temp_log_file):
        """Search with count output format - should return count value"""
        result = search(files=[temp_log_file], query="message", output_format="count")
        assert "total_matches" in result
        # "message" appears in every entry (100 entries)
        assert result["total_matches"] >= 50, "Count should find many 'message' matches"

    def test_search_output_format_compact(self, temp_log_file):
        """Search with compact output format - should return simplified results"""
        result = search(files=[temp_log_file], query="message", output_format="compact")
        # Compact format returns 'matches' and 'total' per docstring
        assert "matches" in result or "total" in result or "results" in result
        # Should find matches for "message" which appears in every entry
        total = result.get(
            "total",
            result.get("total_matches", len(result.get("matches", result.get("results", [])))),
        )
        assert total > 0, "Should find 'message' matches"

    def test_search_with_context_lines(self, temp_log_file):
        """Search with context lines - should return matches with context"""
        result = search(files=[temp_log_file], query="number 50", context_lines=5, limit=5)
        results = result.get("results", [])
        # MUST find "number 50" - it's in entry 50
        assert len(results) >= 1, "Should find 'number 50' in log file"
        # First result should have context structure
        item = results[0]
        assert isinstance(item, dict)
        # Should contain the matched entry
        entry = item.get("entry", item)
        assert "50" in str(entry)

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
        """Search with regex-like pattern - should match entries with 'message' and '50'"""
        result = search(files=[temp_log_file], query="message.*50", limit=10)
        assert "results" in result or "total_matches" in result
        # Should find at least "Log message number 50"
        matches = result.get("results", [])
        if matches:
            # Verify matches contain expected pattern
            found_50 = any(
                "50" in str(item.get("entry", {}).get("message", "")) for item in matches
            )
            assert found_50, "Expected to find entry with '50' in message"

    def test_search_multiple_files(self, multi_log_files):
        """Search across multiple files"""
        result = search(files=multi_log_files, query="message", limit=50)
        assert result.get("total_matches", 0) > 0

    def test_search_empty_file_list(self):
        """Search with empty file list - should raise error or return empty"""
        try:
            result = search(files=[], query="test")
            # If it doesn't raise, should return empty results
            assert result.get("total_matches", 0) == 0, "Empty file list should return no matches"
        except (ValueError, RuntimeError):
            pass  # Also acceptable to raise an error

    def test_search_nonexistent_file(self):
        """Search in non-existent file"""
        with pytest.raises((FileNotFoundError, RuntimeError, OSError)):
            search(files=["/does/not/exist.log"], query="test")


class TestFollowThread:
    """Follow thread functionality tests."""

    def test_follow_thread_by_id(self, temp_log_file):
        """Follow specific thread - should return entries for the thread"""
        result = follow_thread(files=[temp_log_file], thread_id="worker-0")
        # Must have entries key
        assert "entries" in result, "Result must have 'entries' key"
        entries = result["entries"]
        # worker-0 appears in entries 0, 5, 10, 15... (every 5th entry) = 20 entries
        assert len(entries) == 20, f"worker-0 should have 20 entries, got {len(entries)}"
        # ALL entries must be from worker-0
        for entry in entries:
            assert entry["thread_id"] == "worker-0"

    def test_follow_thread_by_correlation(self, temp_log_file):
        """Follow by correlation ID - should return entries with matching correlation"""
        result = follow_thread(files=[temp_log_file], correlation_id="req-0")
        # Must have entries key
        assert "entries" in result, "Result must have 'entries' key"
        entries = result["entries"]
        # req-0 appears in entries 0, 20, 40, 60, 80 (i % 20 == 0) = 5 entries
        assert len(entries) == 5, f"req-0 should have 5 entries, got {len(entries)}"
        # ALL entries must have matching correlation_id
        for entry in entries:
            assert entry["correlation_id"] == "req-0"

    def test_follow_nonexistent_thread(self, temp_log_file):
        """Follow non-existent thread"""
        result = follow_thread(files=[temp_log_file], thread_id="does-not-exist")
        # Should return empty result, not crash
        entries = result.get("entries", [])
        assert len(entries) == 0

    def test_follow_no_id_specified(self, temp_log_file):
        """Follow with no ID specified - should return empty entries"""
        try:
            result = follow_thread(files=[temp_log_file])
            # If it doesn't raise, entries must be empty
            assert "entries" in result, "Result must have 'entries' key"
            assert len(result["entries"]) == 0, "No ID specified should return empty entries"
        except (ValueError, RuntimeError):
            pass  # Also acceptable to raise an error


class TestGetContext:
    """Get context around line tests."""

    def test_context_middle_of_file(self, temp_log_file):
        """Get context from middle of file - should have target and context"""
        result = get_context(file=temp_log_file, line_number=50, lines_before=5, lines_after=5)
        # Must have target line
        assert "target" in result, "Should have target line in result"
        # Should have context before and after (we're in middle of 100-line file)
        assert "context_before" in result, "Should have context_before"
        assert "context_after" in result, "Should have context_after"
        # Context should have content
        assert len(result.get("context_before", [])) > 0
        assert len(result.get("context_after", [])) > 0

    def test_context_start_of_file(self, temp_log_file):
        """Get context at start of file - should have truncated context_before"""
        result = get_context(file=temp_log_file, line_number=1, lines_before=10, lines_after=5)
        # Should have target line
        assert "target" in result or "line" in result
        # context_before should be empty or have fewer than requested lines (since we're at start)
        context_before = result.get("context_before", [])
        assert len(context_before) < 10, "At line 1, context_before should have <10 lines"
        # context_after should have content
        context_after = result.get("context_after", [])
        assert len(context_after) <= 5

    def test_context_end_of_file(self, temp_log_file):
        """Get context at end of file - should have truncated context_after"""
        result = get_context(file=temp_log_file, line_number=100, lines_before=5, lines_after=10)
        # Should have target line
        assert "target" in result or "line" in result
        # context_before should have content (we're not at start)
        context_before = result.get("context_before", [])
        assert len(context_before) <= 5
        # context_after should be empty or truncated (at end of 100-line file)
        context_after = result.get("context_after", [])
        assert len(context_after) < 10, "At line 100, context_after should have <10 lines"

    def test_context_line_zero(self, temp_log_file):
        """Get context at line 0 - should raise ValueError (lines are 1-indexed)"""
        with pytest.raises((ValueError, IndexError, RuntimeError)):
            get_context(file=temp_log_file, line_number=0, lines_before=5, lines_after=5)

    def test_context_negative_line(self, temp_log_file):
        """Get context at negative line - should raise ValueError"""
        with pytest.raises((ValueError, IndexError, RuntimeError, OverflowError)):
            get_context(file=temp_log_file, line_number=-1, lines_before=5, lines_after=5)

    def test_context_past_end_of_file(self, temp_log_file):
        """Get context past end of file - should raise IndexError"""
        with pytest.raises((RuntimeError, IndexError)):
            get_context(file=temp_log_file, line_number=99999, lines_before=5, lines_after=5)


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
        """Follow thread through investigator - should return entries for worker-0"""
        inv = Investigator()
        inv.load_files([temp_log_file])
        result = inv.follow_thread(thread_id="worker-0")
        # Must have entries key
        assert "entries" in result, "Result must have 'entries' key"
        entries = result["entries"]
        # worker-0 appears in entries 0, 5, 10, 15... (every 5th entry) = 20 entries
        assert len(entries) == 20, f"worker-0 should have 20 entries, got {len(entries)}"
        # ALL entries must be from worker-0
        for entry in entries:
            assert entry["thread_id"] == "worker-0"


class TestEmptyAndEdgeCaseFiles:
    """Edge case file handling."""

    def test_empty_log_file(self):
        """Handle empty log file"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            temp_path = f.name

        try:
            result = search(files=[temp_path], query="test")
            assert result.get("total_matches", 0) == 0
        finally:
            Path(temp_path).unlink()

    def test_single_line_file(self):
        """Handle single-line file"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            f.write('{"message": "only line", "level": "INFO"}\n')
            temp_path = f.name

        try:
            result = search(files=[temp_path], query="only")
            assert result.get("total_matches", 0) >= 1
        finally:
            Path(temp_path).unlink()

    def test_non_json_log_file(self):
        """Handle plain text log file - should find text matches"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            for i in range(50):
                f.write(f"2024-01-15 10:{i:02d}:00 INFO Plain text message {i}\n")
            temp_path = f.name

        try:
            result = search(files=[temp_path], query="Plain text")
            # Should find matches in plain text logs
            assert "results" in result or "total_matches" in result
            total = result.get("total_matches", len(result.get("results", [])))
            assert total > 0, "Should find 'Plain text' in plain text log file"
        finally:
            Path(temp_path).unlink()

    def test_mixed_format_file(self):
        """Handle file with mixed JSON and plain text - should find matches in both"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            f.write('{"message": "JSON line", "level": "INFO"}\n')
            f.write("2024-01-15 10:00:00 ERROR Plain text line\n")
            f.write('{"message": "Another JSON", "level": "DEBUG"}\n')
            f.write("Just a plain line without structure\n")
            temp_path = f.name

        try:
            result = search(files=[temp_path], query="line")
            # Should find matches across both formats
            assert "results" in result or "total_matches" in result
            total = result.get("total_matches", len(result.get("results", [])))
            # "line" appears in 3 of the 4 lines
            assert total >= 1, "Should find 'line' in mixed format file"
        finally:
            Path(temp_path).unlink()

    def test_malformed_json_in_file(self):
        """Handle file with malformed JSON - should find good entries, skip bad ones"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            f.write('{"message": "good"}\n')
            f.write('{"message": "truncated\n')
            f.write("not json at all\n")
            f.write('{"message": "also good"}\n')
            temp_path = f.name

        try:
            result = search(files=[temp_path], query="good")
            # Should find the valid "good" entries
            assert "results" in result or "total_matches" in result
            total = result.get("total_matches", len(result.get("results", [])))
            # Should find at least the 2 valid JSON entries with "good"
            assert total >= 1, "Should find 'good' in valid JSON entries"
        finally:
            Path(temp_path).unlink()


class TestLargeScale:
    """Large scale tests."""

    def test_large_file_search(self):
        """Search in large file"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            for i in range(10000):
                entry = json.dumps(
                    {
                        "timestamp": f"2024-01-15T10:00:{i % 60:02d}Z",
                        "level": "INFO" if i % 100 != 0 else "ERROR",
                        "message": f"Message {i}",
                        "thread_id": f"worker-{i % 10}",
                    }
                )
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
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
                for j in range(100):
                    entry = json.dumps({"message": f"File {i} message {j}", "level": "INFO"})
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
        """Session search functionality - should return search results"""
        result = session_with_file.search(query="message")
        # Should have results structure
        assert "results" in result or "total_matches" in result
        # "message" appears in every log entry, should find many
        total = result.get("total_matches", len(result.get("results", [])))
        assert total > 0, "Should find 'message' in log entries"

    def test_session_history(self, session_with_file):
        """Session tracks history"""
        session_with_file.search(query="test1")
        session_with_file.search(query="test2")
        session_with_file.search(query="test3")

        history = session_with_file.get_history()
        assert len(history) >= 3

    def test_session_undo(self, session_with_file):
        """Session undo functionality - should return previous state or success indicator"""
        session_with_file.search(query="test1")
        session_with_file.search(query="test2")

        # Undo should succeed after 2 operations
        result = session_with_file.undo()
        # undo() should return a truthy value or the previous result on success
        assert result is not False, "Undo should succeed after search operations"

    def test_session_redo(self, session_with_file):
        """Session redo after undo"""
        session_with_file.search(query="test1")
        session_with_file.search(query="test2")
        session_with_file.undo()
        result = session_with_file.redo()
        # redo() returns bool indicating success
        assert isinstance(result, bool)

    def test_session_undo_at_start(self, session_with_file):
        """Undo when at start of history - should return False"""
        # No operations yet (just init)
        result = session_with_file.undo()
        # Should return False when can't undo
        assert result is False, "Undo at start of history should return False"

    def test_session_redo_at_end(self, session_with_file):
        """Redo when at end of history - should return False"""
        session_with_file.search(query="test")
        result = session_with_file.redo()
        # Should return False when can't redo (nothing to redo)
        assert result is False, "Redo at end of history should return False"

    def test_session_add_note(self, session_with_file):
        """Add note to session - note should appear in history"""
        session_with_file.add_note("This is a test note")
        history = session_with_file.get_history()
        # History should have at least one entry (the note)
        assert len(history) >= 1, "History should contain the note"
        # The note content should be findable in history
        history_str = str(history).lower()
        assert "note" in history_str or "test" in history_str, "Note should be in history"

    def test_session_save_load_roundtrip(self, session_with_file):
        """Save and load session"""
        session_with_file.search(query="test1")
        session_with_file.search(query="test2")
        session_with_file.add_note("Important finding")

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
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
        """Save to non-writable path - should raise PermissionError"""
        with pytest.raises((PermissionError, OSError, RuntimeError)):
            session_with_file.save("/root/definitely/not/writable/session.json")

    def test_session_load_nonexistent(self, session_with_file):
        """Load from non-existent path"""
        with pytest.raises((FileNotFoundError, OSError, RuntimeError)):
            session_with_file.load("/does/not/exist/session.json")

    def test_session_load_invalid_json(self, session_with_file):
        """Load from invalid JSON file"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
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
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            entries = [
                {"message": "Path: /usr/local/bin", "level": "INFO"},
                {"message": "Query: SELECT * FROM users WHERE id=1", "level": "DEBUG"},
                {"message": "Regex: ^[a-z]+$", "level": "INFO"},
                {"message": 'JSON: {"key": "value"}', "level": "INFO"},
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
        """Search for path with slashes - should find the path entry"""
        result = search(files=[special_char_file], query="/usr/local")
        assert "results" in result or "total_matches" in result
        total = result.get("total_matches", len(result.get("results", [])))
        assert total >= 1, "Should find entry containing '/usr/local'"

    def test_search_with_asterisk(self, special_char_file):
        """Search with asterisk - should find SQL query entry"""
        result = search(files=[special_char_file], query="SELECT *")
        assert "results" in result or "total_matches" in result
        total = result.get("total_matches", len(result.get("results", [])))
        assert total >= 1, "Should find entry containing 'SELECT *'"

    def test_search_with_caret(self, special_char_file):
        """Search with caret - should find regex entry"""
        result = search(files=[special_char_file], query="^[a-z]")
        assert "results" in result or "total_matches" in result
        total = result.get("total_matches", len(result.get("results", [])))
        assert total >= 1, "Should find entry containing '^[a-z]'"

    def test_search_with_unicode(self, special_char_file):
        """Search with unicode characters - should find Japanese text"""
        result = search(files=[special_char_file], query="日本語")
        assert "results" in result or "total_matches" in result
        total = result.get("total_matches", len(result.get("results", [])))
        assert total >= 1, "Should find entry containing '日本語'"

    def test_search_with_emoji(self, special_char_file):
        """Search with emoji - should find emoji entry"""
        result = search(files=[special_char_file], query="🎉")
        assert "results" in result or "total_matches" in result
        total = result.get("total_matches", len(result.get("results", [])))
        assert total >= 1, "Should find entry containing '🎉'"
