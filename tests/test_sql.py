"""
Tests for the SQL query feature (logler.sql.SqlEngine + Investigator.sql_*).

This tests logler's SQL escape hatch — the DuckDB-powered query interface.
These tests verify logler correctly loads, transforms, and exposes log data
via SQL. They do NOT use SQL to test non-SQL features.

Fixture: sql_log_file
- 40 entries total
- 4 levels: INFO (10), DEBUG (10), WARN (10), ERROR (10)
- 2 threads: worker-0 (20), worker-1 (20)
- 4 correlations: corr-0 through corr-3 (10 each)
- 2 services: api (20), db (20)
- Numeric fields: duration_ms=100+i*10 in message for every entry

Entry i:
  level    = [INFO, DEBUG, WARN, ERROR][i % 4]
  thread   = worker-{i % 2}
  service  = api if i < 20 else db
  corr     = corr-{i % 4}
  message  = "Request handled duration_ms={100+i*10}"
  timestamp = 2024-01-15T10:00:{ss}Z  (incrementing by 1s)
"""

import json
import tempfile
from pathlib import Path

import duckdb
import pytest

try:
    from logler.investigate import Investigator, RUST_AVAILABLE
except ImportError as e:
    if "logler_rs" in str(e):
        RUST_AVAILABLE = False
    else:
        raise

try:
    from logler.sql import SqlEngine
    from logler.parser import LogParser

    SQL_AVAILABLE = True
except ImportError:
    SQL_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not RUST_AVAILABLE or not SQL_AVAILABLE,
    reason="Rust backend and DuckDB required",
)

TOTAL_ENTRIES = 40
LEVELS = ["INFO", "DEBUG", "WARN", "ERROR"]
ENTRIES_PER_LEVEL = 10
ENTRIES_PER_THREAD = 20
ENTRIES_PER_CORR = 10
ENTRIES_PER_SERVICE = 20

LOGS_COLUMNS = [
    "file",
    "line_number",
    "timestamp",
    "level",
    "message",
    "thread_id",
    "correlation_id",
    "trace_id",
    "span_id",
    "raw",
]

METRICS_COLUMNS = [
    "file",
    "line_number",
    "timestamp",
    "field_name",
    "value",
    "unit",
]


@pytest.fixture
def sql_log_file():
    """40 entries across 2 services, 4 levels, 2 threads, 4 correlations."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        for i in range(TOTAL_ENTRIES):
            ss = i % 60
            duration = 100 + i * 10
            entry = json.dumps(
                {
                    "timestamp": f"2024-01-15T10:00:{ss:02d}Z",
                    "level": LEVELS[i % 4],
                    "message": f"Request handled duration_ms={duration}",
                    "thread_id": f"worker-{i % 2}",
                    "correlation_id": f"corr-{i % 4}",
                    "trace_id": f"trace-{i % 4}",
                    "span_id": f"span-{i:03d}",
                    "service_name": "api" if i < 20 else "db",
                }
            )
            f.write(entry + "\n")
        temp_path = f.name

    yield temp_path
    Path(temp_path).unlink()


def _build_index(file_path):
    """Parse a log file into a {path: LogIndex} mapping for SqlEngine."""
    parser = LogParser()
    entries = []
    with open(file_path, encoding="utf-8", errors="replace") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.rstrip("\n\r")
            if line:
                entries.append(parser.parse_line(line_number, line))

    class LogIndex:
        pass

    idx = LogIndex()
    idx.entries = entries
    return {file_path: idx}


@pytest.fixture
def loaded_engine(sql_log_file):
    """SqlEngine loaded with the sql_log_file."""
    engine = SqlEngine()
    engine.load_files(_build_index(sql_log_file))
    return engine


@pytest.fixture
def investigator(sql_log_file):
    """Investigator loaded with the sql_log_file."""
    inv = Investigator()
    inv.load_files([sql_log_file])
    return inv


# ---------------------------------------------------------------------------
# SqlEngine direct tests
# ---------------------------------------------------------------------------


class TestSqlEngineLoadFiles:
    """Verify SqlEngine.load_files populates the logs table correctly."""

    def test_logs_table_row_count(self, loaded_engine):
        result = json.loads(loaded_engine.query("SELECT COUNT(*) AS cnt FROM logs"))
        assert len(result) == 1
        assert result[0]["cnt"] == TOTAL_ENTRIES

    def test_level_distribution(self, loaded_engine):
        result = json.loads(
            loaded_engine.query(
                "SELECT level, COUNT(*) AS cnt FROM logs " "GROUP BY level ORDER BY level"
            )
        )
        level_counts = {row["level"]: row["cnt"] for row in result}
        assert len(level_counts) == 4
        for level in LEVELS:
            assert level_counts[level] == ENTRIES_PER_LEVEL

    def test_thread_distribution(self, loaded_engine):
        result = json.loads(
            loaded_engine.query(
                "SELECT thread_id, COUNT(*) AS cnt FROM logs "
                "GROUP BY thread_id ORDER BY thread_id"
            )
        )
        thread_counts = {row["thread_id"]: row["cnt"] for row in result}
        assert thread_counts["worker-0"] == ENTRIES_PER_THREAD
        assert thread_counts["worker-1"] == ENTRIES_PER_THREAD

    def test_first_row_exact_values(self, loaded_engine):
        """Entry i=0: INFO, worker-0, corr-0, trace-0, span-000, duration_ms=100."""
        result = json.loads(loaded_engine.query("SELECT * FROM logs ORDER BY line_number LIMIT 1"))
        assert len(result) == 1
        first = result[0]
        assert first["line_number"] == 1
        assert first["level"] == "INFO"
        assert first["message"] == "Request handled duration_ms=100"
        assert first["thread_id"] == "worker-0"
        assert first["correlation_id"] == "corr-0"
        assert first["trace_id"] == "trace-0"
        assert first["span_id"] == "span-000"

    def test_all_rows_have_required_columns(self, loaded_engine):
        """Every row should have all expected columns non-null."""
        result = json.loads(loaded_engine.query("SELECT * FROM logs ORDER BY line_number"))
        assert len(result) == TOTAL_ENTRIES
        for i, row in enumerate(result):
            assert row["line_number"] == i + 1
            assert row["level"] == LEVELS[i % 4]
            assert row["thread_id"] == f"worker-{i % 2}"
            assert row["correlation_id"] == f"corr-{i % 4}"

    def test_correlation_id_values(self, loaded_engine):
        result = json.loads(
            loaded_engine.query("SELECT DISTINCT correlation_id FROM logs ORDER BY correlation_id")
        )
        corr_ids = [row["correlation_id"] for row in result]
        assert corr_ids == ["corr-0", "corr-1", "corr-2", "corr-3"]


class TestSqlEngineMetricsTable:
    """Verify the auto-populated metrics table from numeric extraction."""

    def test_metrics_table_exists(self, loaded_engine):
        tables = loaded_engine.get_tables()
        assert "logs" in tables
        assert "metrics" in tables

    def test_metrics_has_duration_field(self, loaded_engine):
        result = json.loads(
            loaded_engine.query("SELECT DISTINCT field_name FROM metrics ORDER BY field_name")
        )
        field_names = [row["field_name"] for row in result]
        assert "duration_ms" in field_names

    def test_metrics_duration_values(self, loaded_engine):
        """duration_ms should be 100, 110, 120, ..., 490 (40 values)."""
        result = json.loads(
            loaded_engine.query(
                "SELECT MIN(value) AS mn, MAX(value) AS mx, COUNT(*) AS cnt "
                "FROM metrics WHERE field_name = 'duration_ms'"
            )
        )
        assert len(result) == 1
        assert result[0]["mn"] == 100.0
        assert result[0]["mx"] == 490.0
        assert result[0]["cnt"] == TOTAL_ENTRIES


class TestSqlEngineQuery:
    """Test SQL query capabilities (aggregation, filtering, ordering)."""

    def test_where_filter(self, loaded_engine):
        result = json.loads(
            loaded_engine.query("SELECT COUNT(*) AS cnt FROM logs WHERE level = 'ERROR'")
        )
        assert result[0]["cnt"] == ENTRIES_PER_LEVEL

    def test_group_by_with_having(self, loaded_engine):
        """Correlation IDs each have 10 entries; HAVING > 5 returns all 4."""
        result = json.loads(
            loaded_engine.query(
                "SELECT correlation_id, COUNT(*) AS cnt FROM logs "
                "GROUP BY correlation_id HAVING cnt > 5 "
                "ORDER BY correlation_id"
            )
        )
        assert len(result) == 4
        for row in result:
            assert row["cnt"] == ENTRIES_PER_CORR

    def test_order_by_line_number(self, loaded_engine):
        result = json.loads(
            loaded_engine.query("SELECT line_number FROM logs ORDER BY line_number LIMIT 5")
        )
        assert [row["line_number"] for row in result] == [1, 2, 3, 4, 5]

    def test_join_logs_and_metrics(self, loaded_engine):
        """Join logs and metrics to get message + numeric value."""
        result = json.loads(
            loaded_engine.query(
                "SELECT l.message, m.value FROM logs l "
                "JOIN metrics m ON l.file = m.file AND l.line_number = m.line_number "
                "WHERE m.field_name = 'duration_ms' "
                "ORDER BY l.line_number LIMIT 3"
            )
        )
        assert len(result) == 3
        assert result[0]["value"] == 100.0
        assert result[1]["value"] == 110.0
        assert result[2]["value"] == 120.0

    def test_empty_result(self, loaded_engine):
        result = json.loads(loaded_engine.query("SELECT * FROM logs WHERE level = 'NONEXISTENT'"))
        assert result == []


class TestSqlEngineGetSchema:
    """Test schema introspection."""

    def test_logs_schema_columns(self, loaded_engine):
        schema = json.loads(loaded_engine.get_schema("logs"))
        column_names = [col["name"] for col in schema]
        assert column_names == LOGS_COLUMNS

    def test_metrics_schema_columns(self, loaded_engine):
        schema = json.loads(loaded_engine.get_schema("metrics"))
        column_names = [col["name"] for col in schema]
        assert column_names == METRICS_COLUMNS


# ---------------------------------------------------------------------------
# Investigator.sql_* method tests
# ---------------------------------------------------------------------------


class TestInvestigatorSqlQuery:
    """Test the Investigator's SQL interface."""

    def test_sql_query_count(self, investigator):
        result = investigator.sql_query("SELECT COUNT(*) AS cnt FROM logs")
        assert len(result) == 1
        assert result[0]["cnt"] == TOTAL_ENTRIES

    def test_sql_query_level_aggregation(self, investigator):
        result = investigator.sql_query(
            "SELECT level, COUNT(*) AS cnt FROM logs GROUP BY level ORDER BY level"
        )
        level_counts = {row["level"]: row["cnt"] for row in result}
        assert len(level_counts) == 4
        for level in LEVELS:
            assert level_counts[level] == ENTRIES_PER_LEVEL

    def test_sql_query_thread_filter(self, investigator):
        result = investigator.sql_query(
            "SELECT COUNT(*) AS cnt FROM logs WHERE thread_id = 'worker-0'"
        )
        assert result[0]["cnt"] == ENTRIES_PER_THREAD


class TestInvestigatorSqlTables:
    """Test the Investigator's table listing."""

    def test_tables_include_logs_and_metrics(self, investigator):
        tables = investigator.sql_tables()
        assert "logs" in tables
        assert "metrics" in tables


class TestInvestigatorSqlSchema:
    """Test the Investigator's schema introspection."""

    def test_schema_exact_columns(self, investigator):
        schema = investigator.sql_schema("logs")
        column_names = [col["name"] for col in schema]
        assert column_names == LOGS_COLUMNS

    def test_schema_nonexistent_table(self, investigator):
        schema = investigator.sql_schema("nonexistent_table")
        assert schema == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestSqlErrorHandling:
    """Verify SQL errors propagate correctly."""

    def test_invalid_sql_syntax(self, loaded_engine):
        with pytest.raises(duckdb.ParserException):
            loaded_engine.query("SELECT COUNT(*) AS cnt FROM")

    def test_nonexistent_table(self, loaded_engine):
        with pytest.raises(duckdb.CatalogException):
            loaded_engine.query("SELECT * FROM nonexistent_table")

    def test_nonexistent_column(self, loaded_engine):
        with pytest.raises(duckdb.BinderException):
            loaded_engine.query("SELECT nonexistent_column FROM logs")

    def test_investigator_propagates_sql_errors(self, investigator):
        with pytest.raises(duckdb.CatalogException):
            investigator.sql_query("SELECT * FROM nonexistent_table")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestSqlEdgeCases:
    """Edge cases and error handling."""

    def test_empty_file(self):
        """SqlEngine with no entries should create empty tables."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            f.write("")
            temp_path = f.name

        try:

            class LogIndex:
                pass

            idx = LogIndex()
            idx.entries = []
            engine = SqlEngine()
            engine.load_files({temp_path: idx})

            result = json.loads(engine.query("SELECT COUNT(*) AS cnt FROM logs"))
            assert result[0]["cnt"] == 0

            tables = engine.get_tables()
            assert "logs" in tables
            assert "metrics" in tables
        finally:
            Path(temp_path).unlink()

    def test_sql_injection_in_schema(self, loaded_engine):
        """get_schema rejects invalid table names (no SQL injection)."""
        result = json.loads(loaded_engine.get_schema("logs'; DROP TABLE logs; --"))
        assert result == []

        # Verify logs table still exists after injection attempt
        count = json.loads(loaded_engine.query("SELECT COUNT(*) AS cnt FROM logs"))
        assert count[0]["cnt"] == TOTAL_ENTRIES

    def test_schema_empty_string(self, loaded_engine):
        """Empty table name should return empty result."""
        result = json.loads(loaded_engine.get_schema(""))
        assert result == []

    def test_get_tables_returns_both(self, loaded_engine):
        """get_tables should return exactly logs and metrics."""
        tables = sorted(loaded_engine.get_tables())
        assert tables == ["logs", "metrics"]


# ---------------------------------------------------------------------------
# Disk-backed DuckDB + engine caching
# ---------------------------------------------------------------------------


class TestSqlEngineDiskBacked:
    """Verify SqlEngine works with a disk-backed DuckDB database."""

    def test_disk_backed_query_matches_memory(self, sql_log_file, tmp_path):
        """Disk-backed engine should produce identical results to in-memory."""
        db_file = str(tmp_path / "test.duckdb")
        index = _build_index(sql_log_file)

        engine_disk = SqlEngine(db_path=db_file)
        engine_disk.load_files(index)

        engine_mem = SqlEngine()
        engine_mem.load_files(index)

        disk_result = json.loads(
            engine_disk.query(
                "SELECT level, COUNT(*) AS cnt FROM logs GROUP BY level ORDER BY level"
            )
        )
        mem_result = json.loads(
            engine_mem.query(
                "SELECT level, COUNT(*) AS cnt FROM logs GROUP BY level ORDER BY level"
            )
        )
        assert disk_result == mem_result
        # Verify exact values, not just equality between two unknowns
        level_counts = {row["level"]: row["cnt"] for row in disk_result}
        assert len(level_counts) == 4
        for level in LEVELS:
            assert level_counts[level] == ENTRIES_PER_LEVEL

        engine_disk.close()
        engine_mem.close()

    def test_disk_backed_creates_file(self, sql_log_file, tmp_path):
        """Disk-backed mode should create a file on disk."""
        db_file = tmp_path / "test.duckdb"
        assert not db_file.exists()

        engine = SqlEngine(db_path=str(db_file))
        engine.load_files(_build_index(sql_log_file))
        engine.close()

        assert db_file.exists()

    def test_disk_backed_persists_after_close(self, sql_log_file, tmp_path):
        """Data written to disk survives close and re-open."""
        db_file = str(tmp_path / "persist.duckdb")
        engine = SqlEngine(db_path=db_file)
        engine.load_files(_build_index(sql_log_file))
        engine.close()

        # Re-open the same file — data should still be there
        engine2 = SqlEngine(db_path=db_file)
        result = json.loads(engine2.query("SELECT COUNT(*) AS cnt FROM logs"))
        assert result[0]["cnt"] == TOTAL_ENTRIES

        metrics = json.loads(engine2.query("SELECT COUNT(*) AS cnt FROM metrics"))
        assert metrics[0]["cnt"] == TOTAL_ENTRIES  # one duration_ms per entry
        engine2.close()

    def test_close_releases_file_lock(self, sql_log_file, tmp_path):
        """After close(), another engine can open the same file."""
        db_file = str(tmp_path / "lock.duckdb")
        engine1 = SqlEngine(db_path=db_file)
        engine1.load_files(_build_index(sql_log_file))
        engine1.close()

        # Should not raise — file lock must be released
        engine2 = SqlEngine(db_path=db_file)
        result = json.loads(engine2.query("SELECT COUNT(*) AS cnt FROM logs"))
        assert result[0]["cnt"] == TOTAL_ENTRIES
        engine2.close()

    def test_close_idempotent(self, sql_log_file):
        """Calling close() twice should not raise."""
        engine = SqlEngine()
        engine.load_files(_build_index(sql_log_file))
        engine.close()
        engine.close()  # should not raise


class TestInvestigatorSqlEngineCaching:
    """Verify the Investigator caches the SQL engine instead of rebuilding."""

    def test_engine_cached_across_queries(self, investigator):
        """Two sql_query() calls should reuse the same engine instance."""
        investigator.sql_query("SELECT COUNT(*) AS cnt FROM logs")
        engine_after_first = investigator._sql_engine
        assert engine_after_first is not None

        # Capture reference BEFORE second call — if caching is broken and a
        # new engine is built, engine_after_first will differ from the attr
        investigator.sql_query("SELECT COUNT(*) AS cnt FROM logs")

        # The attribute must still point to the SAME object
        assert investigator._sql_engine is engine_after_first

    def test_engine_invalidated_on_load(self, sql_log_file):
        """load_files() should invalidate the cached engine."""
        inv = Investigator()
        inv.load_files([sql_log_file])

        inv.sql_query("SELECT COUNT(*) AS cnt FROM logs")
        engine1 = inv._sql_engine
        assert engine1 is not None

        # Re-load the same file — engine should be invalidated
        inv.load_files([sql_log_file])
        assert inv._sql_engine is None

        # Next query builds a fresh engine
        inv.sql_query("SELECT COUNT(*) AS cnt FROM logs")
        engine2 = inv._sql_engine
        assert engine2 is not None
        assert engine2 is not engine1

    def test_engine_rebuild_count(self, sql_log_file):
        """Cache warm: zero new constructions. After load_files: exactly one."""
        from unittest.mock import patch

        inv = Investigator()
        inv.load_files([sql_log_file])

        # Warm the cache
        inv.sql_query("SELECT 1")
        assert inv._sql_engine is not None

        # Patch SqlEngine at the import site used by _get_sql_engine().
        # With cache warm, no construction should happen.
        with patch("logler.sql.SqlEngine") as mock_cls:
            inv.sql_query("SELECT 1")
            inv.sql_query("SELECT 1")
            assert mock_cls.call_count == 0, (
                f"SqlEngine constructed {mock_cls.call_count} time(s) "
                "while cache was warm"
            )

        # load_files invalidates — next query must rebuild exactly once
        inv.load_files([sql_log_file])
        assert inv._sql_engine is None

        with patch("logler.sql.SqlEngine", wraps=SqlEngine) as mock_cls:
            inv.sql_query("SELECT 1")
            assert mock_cls.call_count == 1, (
                f"Expected exactly 1 rebuild after load_files, got {mock_cls.call_count}"
            )

    def test_load_files_closes_old_engine(self, sql_log_file, tmp_path):
        """load_files() must call close() on the old cached engine."""
        from unittest.mock import patch

        db_file = str(tmp_path / "close_test.duckdb")
        inv = Investigator(sql_db_path=db_file)
        inv.load_files([sql_log_file])
        inv.sql_query("SELECT 1")

        old_engine = inv._sql_engine
        assert old_engine is not None

        with patch.object(old_engine, "close", wraps=old_engine.close) as mock_close:
            inv.load_files([sql_log_file])
            assert mock_close.call_count == 1

    def test_disk_backed_investigator(self, sql_log_file, tmp_path):
        """Investigator with sql_db_path should use disk-backed DuckDB."""
        db_file = tmp_path / "inv.duckdb"
        inv = Investigator(sql_db_path=str(db_file))
        inv.load_files([sql_log_file])

        result = inv.sql_query("SELECT COUNT(*) AS cnt FROM logs")
        assert result[0]["cnt"] == TOTAL_ENTRIES
        assert db_file.exists()

        # Prove data actually went to disk: close investigator's engine,
        # re-open the file independently, verify data survived
        inv._sql_engine.close()
        inv._sql_engine = None

        verify_engine = SqlEngine(db_path=str(db_file))
        verify_result = json.loads(
            verify_engine.query("SELECT COUNT(*) AS cnt FROM logs")
        )
        assert verify_result[0]["cnt"] == TOTAL_ENTRIES
        verify_engine.close()


# ---------------------------------------------------------------------------
# Security: external access disabled
# ---------------------------------------------------------------------------


class TestSqlEngineExternalAccessDisabled:
    """Verify DuckDB connections block filesystem operations."""

    def test_read_csv_auto_blocked(self, loaded_engine):
        """read_csv_auto must be blocked by enable_external_access=false."""
        with pytest.raises(duckdb.PermissionException, match="file system operations are disabled"):
            loaded_engine.query("SELECT * FROM read_csv_auto('/etc/passwd')")

    def test_read_json_auto_blocked(self, loaded_engine):
        """read_json_auto must be blocked."""
        with pytest.raises(duckdb.PermissionException, match="file system operations are disabled"):
            loaded_engine.query("SELECT * FROM read_json_auto('/etc/passwd')")

    def test_copy_to_blocked(self, loaded_engine):
        """COPY ... TO must be blocked — prevents data exfiltration."""
        with pytest.raises(duckdb.PermissionException, match="file system operations are disabled"):
            loaded_engine.query("COPY logs TO '/tmp/exfil.csv'")

    def test_normal_queries_still_work(self, loaded_engine):
        """SELECT, aggregate, JOIN on logs/metrics still function."""
        # Basic SELECT
        result = json.loads(loaded_engine.query("SELECT COUNT(*) AS cnt FROM logs"))
        assert result[0]["cnt"] == TOTAL_ENTRIES

        # Aggregate
        result = json.loads(
            loaded_engine.query(
                "SELECT level, COUNT(*) AS cnt FROM logs GROUP BY level ORDER BY level"
            )
        )
        assert len(result) == 4

        # JOIN
        result = json.loads(
            loaded_engine.query(
                "SELECT l.line_number, m.value FROM logs l "
                "JOIN metrics m ON l.file = m.file AND l.line_number = m.line_number "
                "ORDER BY l.line_number LIMIT 1"
            )
        )
        assert len(result) == 1
        assert result[0]["line_number"] == 1
        assert result[0]["value"] == 100.0


class TestSqlEngineGeneratorEntries:
    """Verify load_files works when index.entries is a one-shot generator."""

    def test_generator_entries_populate_both_tables(self, sql_log_file):
        """If entries is a generator, both logs and metrics should be populated."""
        parser = LogParser()
        raw_entries = []
        with open(sql_log_file, encoding="utf-8", errors="replace") as f:
            for line_number, line in enumerate(f, start=1):
                line = line.rstrip("\n\r")
                if line:
                    raw_entries.append(parser.parse_line(line_number, line))

        class GeneratorIndex:
            """Index whose .entries is a generator (exhausted after one pass)."""
            def __init__(self, items):
                self._items = items
            @property
            def entries(self):
                return (e for e in self._items)

        engine = SqlEngine()
        engine.load_files({sql_log_file: GeneratorIndex(raw_entries)})

        logs_count = json.loads(engine.query("SELECT COUNT(*) AS cnt FROM logs"))
        assert logs_count[0]["cnt"] == TOTAL_ENTRIES

        metrics_count = json.loads(engine.query("SELECT COUNT(*) AS cnt FROM metrics"))
        assert metrics_count[0]["cnt"] == TOTAL_ENTRIES
