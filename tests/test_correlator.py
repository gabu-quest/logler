"""Tests for logler.correlator - correlation engine (M2.2 + M2.3)."""

from __future__ import annotations


from logler.config import (
    CorrelationGroup,
    CorrelationsConfig,
    EventCondition,
    FieldMatchRule,
    FieldSelector,
    TemporalRule,
)
from logler.correlator import (
    _evaluate_condition,
    _get_field_value,
    _matches_anchor,
    _matches_file_pattern,
    correlate_by_rules,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_entry(
    file: str = "app.log",
    message: str = "test",
    level: str = "INFO",
    timestamp: str | None = "2024-01-15T10:00:00+00:00",
    fields: dict | None = None,
    **kwargs,
) -> dict:
    """Create a minimal log entry dict for testing."""
    entry = {
        "file": file,
        "message": message,
        "level": level,
        "timestamp": timestamp,
        "fields": fields or {},
    }
    entry.update(kwargs)
    return entry


# =============================================================================
# Field Value Extraction
# =============================================================================


class TestGetFieldValue:
    def test_top_level_key(self):
        entry = {"thread_id": "worker-1", "fields": {}}
        assert _get_field_value(entry, "thread_id") == "worker-1"

    def test_fields_dict_key(self):
        entry = {"fields": {"batch_id": "B-042"}}
        assert _get_field_value(entry, "batch_id") == "B-042"

    def test_top_level_takes_precedence(self):
        entry = {"level": "ERROR", "fields": {"level": "WARN"}}
        assert _get_field_value(entry, "level") == "ERROR"

    def test_missing_field_returns_none(self):
        entry = {"fields": {}}
        assert _get_field_value(entry, "nonexistent") is None

    def test_missing_fields_dict(self):
        entry = {"message": "hi"}
        assert _get_field_value(entry, "batch_id") is None


# =============================================================================
# File Pattern Matching
# =============================================================================


class TestMatchesFilePattern:
    def test_no_pattern_matches_everything(self):
        entry = _make_entry(file="/var/log/app.log")
        assert _matches_file_pattern(entry, None) is True

    def test_glob_matches(self):
        entry = _make_entry(file="/factory/logs/mes_production.log")
        assert _matches_file_pattern(entry, "mes_*.log") is True

    def test_glob_no_match(self):
        entry = _make_entry(file="/factory/logs/plc_motor.log")
        assert _matches_file_pattern(entry, "mes_*.log") is False

    def test_matches_filename_only(self):
        entry = _make_entry(file="/deep/nested/path/sensor_temp.csv")
        assert _matches_file_pattern(entry, "sensor_*.csv") is True

    def test_empty_file_path(self):
        entry = _make_entry(file="")
        assert _matches_file_pattern(entry, "*.log") is False


# =============================================================================
# Condition Evaluation
# =============================================================================


class TestEvaluateCondition:
    def test_less_than_true(self):
        assert _evaluate_condition(1.5, "< 2.0") is True

    def test_less_than_false(self):
        assert _evaluate_condition(3.0, "< 2.0") is False

    def test_greater_than(self):
        assert _evaluate_condition(150, "> 100") is True

    def test_less_than_or_equal(self):
        assert _evaluate_condition(2.0, "<= 2.0") is True

    def test_greater_than_or_equal(self):
        assert _evaluate_condition(100, ">= 100") is True

    def test_equal(self):
        assert _evaluate_condition(42, "== 42") is True

    def test_not_equal(self):
        assert _evaluate_condition(41, "!= 42") is True

    def test_string_number_coercion(self):
        assert _evaluate_condition("1.5", "< 2.0") is True

    def test_non_numeric_value_returns_false(self):
        assert _evaluate_condition("hello", "< 2.0") is False

    def test_none_value_returns_false(self):
        assert _evaluate_condition(None, "< 2.0") is False

    def test_invalid_condition_returns_false(self):
        assert _evaluate_condition(1.5, "contains foo") is False

    def test_negative_threshold(self):
        assert _evaluate_condition(-5, "< -2") is True


# =============================================================================
# Anchor Matching
# =============================================================================


class TestMatchesAnchor:
    def test_level_match(self):
        entry = _make_entry(level="ERROR")
        anchor = EventCondition(level="ERROR")
        assert _matches_anchor(entry, anchor) is True

    def test_level_case_insensitive(self):
        entry = _make_entry(level="error")
        anchor = EventCondition(level="ERROR")
        assert _matches_anchor(entry, anchor) is True

    def test_level_no_match(self):
        entry = _make_entry(level="INFO")
        anchor = EventCondition(level="ERROR")
        assert _matches_anchor(entry, anchor) is False

    def test_pattern_match(self):
        entry = _make_entry(message="Connection timeout after 30s")
        anchor = EventCondition(pattern="timeout")
        assert _matches_anchor(entry, anchor) is True

    def test_pattern_no_match(self):
        entry = _make_entry(message="Request completed successfully")
        anchor = EventCondition(pattern="timeout")
        assert _matches_anchor(entry, anchor) is False

    def test_field_condition_match(self):
        entry = _make_entry(fields={"pressure": 1.5})
        anchor = EventCondition(field="pressure", condition="< 2.0")
        assert _matches_anchor(entry, anchor) is True

    def test_field_condition_no_match(self):
        entry = _make_entry(fields={"pressure": 3.5})
        anchor = EventCondition(field="pressure", condition="< 2.0")
        assert _matches_anchor(entry, anchor) is False

    def test_file_pattern_filter(self):
        entry = _make_entry(file="/logs/plc_motor.log", level="ERROR")
        anchor = EventCondition(file_pattern="sensor_*.log", level="ERROR")
        assert _matches_anchor(entry, anchor) is False

    def test_combined_conditions_all_must_match(self):
        entry = _make_entry(
            file="/logs/sensor_temp.log",
            level="WARN",
            message="pressure drop detected",
            fields={"pressure": 1.8},
        )
        anchor = EventCondition(
            file_pattern="sensor_*.log",
            level="WARN",
            pattern="pressure",
            field="pressure",
            condition="< 2.0",
        )
        assert _matches_anchor(entry, anchor) is True

    def test_combined_conditions_one_fails(self):
        entry = _make_entry(
            file="/logs/sensor_temp.log",
            level="INFO",  # Wrong level
            fields={"pressure": 1.8},
        )
        anchor = EventCondition(
            level="WARN",
            field="pressure",
            condition="< 2.0",
        )
        assert _matches_anchor(entry, anchor) is False


# =============================================================================
# Field-Based Correlation (M2.2)
# =============================================================================


class TestFieldMatchCorrelation:
    """Test field_match rule correlation."""

    def _make_config(self, *rules) -> CorrelationsConfig:
        return CorrelationsConfig(correlations={"test-group": CorrelationGroup(rules=list(rules))})

    def test_basic_field_match(self):
        """Entries with matching field values across files are correlated."""
        entries = [
            _make_entry(
                file="mes_production.log",
                message="Batch started",
                fields={"batch_id": "B-042"},
            ),
            _make_entry(
                file="mes_production.log",
                message="Batch completed",
                fields={"batch_id": "B-042"},
            ),
            _make_entry(
                file="plc_motor.log",
                message="Motor running for lot",
                fields={"lot_number": "B-042"},
            ),
            _make_entry(
                file="plc_motor.log",
                message="Unrelated lot",
                fields={"lot_number": "B-999"},
            ),
        ]

        config = self._make_config(
            FieldMatchRule(
                type="field_match",
                source=FieldSelector(file_pattern="mes_*.log", field="batch_id"),
                target=FieldSelector(file_pattern="plc_*.log", field="lot_number"),
            )
        )

        result = correlate_by_rules(entries, config)

        assert result["total_clusters"] == 1
        cluster = result["clusters"][0]
        assert cluster["shared_value"] == "B-042"
        assert cluster["source_count"] == 2
        assert cluster["target_count"] == 1
        assert cluster["entry_count"] == 3
        assert cluster["rule_type"] == "field_match"
        assert cluster["virtual_trace_id"].startswith("vt-")

    def test_multiple_shared_values(self):
        """Each unique shared value creates a separate cluster."""
        entries = [
            _make_entry(file="mes.log", fields={"batch_id": "B-001"}),
            _make_entry(file="mes.log", fields={"batch_id": "B-002"}),
            _make_entry(file="plc.log", fields={"lot": "B-001"}),
            _make_entry(file="plc.log", fields={"lot": "B-002"}),
        ]

        config = self._make_config(
            FieldMatchRule(
                type="field_match",
                source=FieldSelector(file_pattern="mes*", field="batch_id"),
                target=FieldSelector(file_pattern="plc*", field="lot"),
            )
        )

        result = correlate_by_rules(entries, config)
        assert result["total_clusters"] == 2
        values = {c["shared_value"] for c in result["clusters"]}
        assert values == {"B-001", "B-002"}

    def test_no_matching_values(self):
        """No clusters when source and target values don't overlap."""
        entries = [
            _make_entry(file="mes.log", fields={"batch_id": "B-001"}),
            _make_entry(file="plc.log", fields={"lot": "B-999"}),
        ]

        config = self._make_config(
            FieldMatchRule(
                type="field_match",
                source=FieldSelector(file_pattern="mes*", field="batch_id"),
                target=FieldSelector(file_pattern="plc*", field="lot"),
            )
        )

        result = correlate_by_rules(entries, config)
        assert result["total_clusters"] == 0

    def test_no_file_pattern_matches_all_files(self):
        """When file_pattern is None, entries from any file are considered."""
        entries = [
            _make_entry(file="any1.log", fields={"order_id": "ORD-1"}),
            _make_entry(file="any2.log", fields={"ref_id": "ORD-1"}),
        ]

        config = self._make_config(
            FieldMatchRule(
                type="field_match",
                source=FieldSelector(field="order_id"),
                target=FieldSelector(field="ref_id"),
            )
        )

        result = correlate_by_rules(entries, config)
        assert result["total_clusters"] == 1

    def test_top_level_fields_used(self):
        """Top-level entry keys (like thread_id) work as field selectors."""
        entries = [
            _make_entry(file="app.log", thread_id="worker-1", fields={}),
            _make_entry(file="worker.log", fields={"handler_thread": "worker-1"}),
        ]

        config = self._make_config(
            FieldMatchRule(
                type="field_match",
                source=FieldSelector(file_pattern="app*", field="thread_id"),
                target=FieldSelector(file_pattern="worker*", field="handler_thread"),
            )
        )

        result = correlate_by_rules(entries, config)
        assert result["total_clusters"] == 1
        assert result["clusters"][0]["shared_value"] == "worker-1"

    def test_missing_field_entries_skipped(self):
        """Entries without the specified field are silently skipped."""
        entries = [
            _make_entry(file="mes.log", fields={"batch_id": "B-001"}),
            _make_entry(file="mes.log", fields={}),  # No batch_id
            _make_entry(file="plc.log", fields={"lot": "B-001"}),
        ]

        config = self._make_config(
            FieldMatchRule(
                type="field_match",
                source=FieldSelector(file_pattern="mes*", field="batch_id"),
                target=FieldSelector(file_pattern="plc*", field="lot"),
            )
        )

        result = correlate_by_rules(entries, config)
        assert result["total_clusters"] == 1
        assert result["clusters"][0]["source_count"] == 1

    def test_virtual_trace_ids_are_deterministic(self):
        """Same inputs produce the same virtual_trace_id."""
        entries = [
            _make_entry(file="a.log", fields={"k": "v"}),
            _make_entry(file="b.log", fields={"k2": "v"}),
        ]

        config = self._make_config(
            FieldMatchRule(
                type="field_match",
                source=FieldSelector(file_pattern="a*", field="k"),
                target=FieldSelector(file_pattern="b*", field="k2"),
            )
        )

        r1 = correlate_by_rules(entries, config)
        r2 = correlate_by_rules(entries, config)
        assert r1["clusters"][0]["virtual_trace_id"] == r2["clusters"][0]["virtual_trace_id"]


# =============================================================================
# Temporal Correlation (M2.3)
# =============================================================================


class TestTemporalCorrelation:
    """Test temporal rule correlation."""

    def _make_config(self, *rules) -> CorrelationsConfig:
        return CorrelationsConfig(correlations={"test-group": CorrelationGroup(rules=list(rules))})

    def test_basic_temporal_window(self):
        """Entries within the time window of an anchor are correlated."""
        entries = [
            _make_entry(
                file="sensor.log",
                timestamp="2024-01-15T10:00:00+00:00",
                level="INFO",
                message="Normal reading",
            ),
            _make_entry(
                file="sensor.log",
                timestamp="2024-01-15T10:00:03+00:00",
                level="WARN",
                message="Pressure drop",
                fields={"pressure": 1.5},
            ),
            _make_entry(
                file="plc.log",
                timestamp="2024-01-15T10:00:04+00:00",
                level="ERROR",
                message="Motor stall detected",
            ),
            _make_entry(
                file="sensor.log",
                timestamp="2024-01-15T10:00:05+00:00",
                level="INFO",
                message="Pressure recovering",
                fields={"pressure": 2.1},
            ),
            _make_entry(
                file="other.log",
                timestamp="2024-01-15T10:05:00+00:00",
                level="INFO",
                message="Unrelated event far away",
            ),
        ]

        config = self._make_config(
            TemporalRule(
                type="temporal",
                anchor=EventCondition(field="pressure", condition="< 2.0"),
                window="5s",
            )
        )

        result = correlate_by_rules(entries, config)

        assert result["total_clusters"] == 1
        cluster = result["clusters"][0]
        assert cluster["rule_type"] == "temporal"
        assert cluster["window"] == "5s"
        # Entries within 5s of the anchor (10:00:03): 10:00:00, 10:00:03, 10:00:04, 10:00:05
        assert cluster["entry_count"] == 4
        # The far-away event at 10:05:00 should NOT be included
        messages = [e["message"] for e in cluster["entries"]]
        assert "Unrelated event far away" not in messages

    def test_level_anchor(self):
        """Anchor by log level collects surrounding entries."""
        entries = [
            _make_entry(timestamp="2024-01-15T10:00:00+00:00", level="INFO", message="Normal"),
            _make_entry(timestamp="2024-01-15T10:00:05+00:00", level="FATAL", message="Crash!"),
            _make_entry(
                timestamp="2024-01-15T10:00:06+00:00", level="ERROR", message="Cleanup failed"
            ),
            _make_entry(timestamp="2024-01-15T10:10:00+00:00", level="INFO", message="Restarted"),
        ]

        config = self._make_config(
            TemporalRule(
                type="temporal",
                anchor=EventCondition(level="FATAL"),
                window="10s",
            )
        )

        result = correlate_by_rules(entries, config)
        assert result["total_clusters"] == 1
        assert result["clusters"][0]["entry_count"] == 3
        assert result["clusters"][0]["anchor_message"] == "Crash!"

    def test_pattern_anchor(self):
        """Anchor by message pattern regex."""
        entries = [
            _make_entry(timestamp="2024-01-15T10:00:00+00:00", message="Starting up"),
            _make_entry(
                timestamp="2024-01-15T10:00:02+00:00", message="E-STOP activated on line 3"
            ),
            _make_entry(timestamp="2024-01-15T10:00:03+00:00", message="All motors halted"),
        ]

        config = self._make_config(
            TemporalRule(
                type="temporal",
                anchor=EventCondition(pattern=r"E-STOP"),
                window="5s",
            )
        )

        result = correlate_by_rules(entries, config)
        assert result["total_clusters"] == 1
        assert result["clusters"][0]["entry_count"] == 3

    def test_no_anchor_matches(self):
        """No clusters when no entries match the anchor condition."""
        entries = [
            _make_entry(timestamp="2024-01-15T10:00:00+00:00", level="INFO"),
            _make_entry(timestamp="2024-01-15T10:00:01+00:00", level="DEBUG"),
        ]

        config = self._make_config(
            TemporalRule(
                type="temporal",
                anchor=EventCondition(level="FATAL"),
                window="10s",
            )
        )

        result = correlate_by_rules(entries, config)
        assert result["total_clusters"] == 0

    def test_entries_without_timestamps_excluded(self):
        """Entries with no timestamp cannot be temporally correlated."""
        entries = [
            _make_entry(timestamp="2024-01-15T10:00:00+00:00", level="ERROR", message="Anchor"),
            _make_entry(timestamp=None, level="INFO", message="No timestamp"),
        ]

        config = self._make_config(
            TemporalRule(
                type="temporal",
                anchor=EventCondition(level="ERROR"),
                window="10s",
            )
        )

        result = correlate_by_rules(entries, config)
        # Only anchor has a timestamp, so cluster has just 1 entry -> skipped
        assert result["total_clusters"] == 0

    def test_multiple_anchors_create_separate_clusters(self):
        """Each anchor match creates its own cluster."""
        entries = [
            _make_entry(
                timestamp="2024-01-15T10:00:00+00:00", level="ERROR", message="First error"
            ),
            _make_entry(timestamp="2024-01-15T10:00:01+00:00", level="INFO", message="Near first"),
            _make_entry(
                timestamp="2024-01-15T10:10:00+00:00", level="ERROR", message="Second error"
            ),
            _make_entry(timestamp="2024-01-15T10:10:01+00:00", level="INFO", message="Near second"),
        ]

        config = self._make_config(
            TemporalRule(
                type="temporal",
                anchor=EventCondition(level="ERROR"),
                window="5s",
            )
        )

        result = correlate_by_rules(entries, config)
        assert result["total_clusters"] == 2


# =============================================================================
# Multi-Group and Mixed Rules
# =============================================================================


class TestMultiGroupCorrelation:
    """Test correlation across multiple groups and mixed rule types."""

    def test_multiple_groups(self):
        """Rules from multiple groups are all applied."""
        entries = [
            _make_entry(file="mes.log", fields={"batch_id": "B-1"}),
            _make_entry(file="plc.log", fields={"lot": "B-1"}),
            _make_entry(
                file="sensor.log",
                timestamp="2024-01-15T10:00:00+00:00",
                level="FATAL",
                message="Overheat",
            ),
            _make_entry(
                file="plc.log",
                timestamp="2024-01-15T10:00:02+00:00",
                level="ERROR",
                message="Shutdown",
            ),
        ]

        config = CorrelationsConfig(
            correlations={
                "batch-link": CorrelationGroup(
                    rules=[
                        FieldMatchRule(
                            type="field_match",
                            source=FieldSelector(file_pattern="mes*", field="batch_id"),
                            target=FieldSelector(file_pattern="plc*", field="lot"),
                        )
                    ]
                ),
                "overheat-blast": CorrelationGroup(
                    rules=[
                        TemporalRule(
                            type="temporal",
                            anchor=EventCondition(level="FATAL"),
                            window="5s",
                        )
                    ]
                ),
            }
        )

        result = correlate_by_rules(entries, config)
        assert result["total_clusters"] == 2
        groups = {c["group"] for c in result["clusters"]}
        assert groups == {"batch-link", "overheat-blast"}

    def test_filter_by_group_name(self):
        """Only rules from the specified group are applied."""
        entries = [
            _make_entry(file="mes.log", fields={"batch_id": "B-1"}),
            _make_entry(file="plc.log", fields={"lot": "B-1"}),
            _make_entry(timestamp="2024-01-15T10:00:00+00:00", level="FATAL", message="Crash"),
            _make_entry(timestamp="2024-01-15T10:00:01+00:00", level="ERROR", message="Aftermath"),
        ]

        config = CorrelationsConfig(
            correlations={
                "batches": CorrelationGroup(
                    rules=[
                        FieldMatchRule(
                            type="field_match",
                            source=FieldSelector(file_pattern="mes*", field="batch_id"),
                            target=FieldSelector(file_pattern="plc*", field="lot"),
                        )
                    ]
                ),
                "crashes": CorrelationGroup(
                    rules=[
                        TemporalRule(
                            type="temporal",
                            anchor=EventCondition(level="FATAL"),
                            window="5s",
                        )
                    ]
                ),
            }
        )

        result = correlate_by_rules(entries, config, group_name="batches")
        assert result["total_clusters"] == 1
        assert result["groups_applied"] == ["batches"]
        assert result["clusters"][0]["group"] == "batches"

    def test_unknown_group_name_returns_error(self):
        config = CorrelationsConfig(correlations={})
        result = correlate_by_rules([], config, group_name="nonexistent")
        assert result["total_clusters"] == 0
        assert "error" in result

    def test_empty_config_returns_empty_result(self):
        config = CorrelationsConfig(correlations={})
        result = correlate_by_rules([_make_entry(fields={"x": "1"})], config)
        assert result["total_clusters"] == 0
        assert result["total_entries_correlated"] == 0

    def test_empty_entries_returns_empty_result(self):
        config = CorrelationsConfig(
            correlations={
                "g": CorrelationGroup(
                    rules=[
                        FieldMatchRule(
                            type="field_match",
                            source=FieldSelector(field="a"),
                            target=FieldSelector(field="b"),
                        )
                    ]
                )
            }
        )
        result = correlate_by_rules([], config)
        assert result["total_clusters"] == 0


# =============================================================================
# Realistic Manufacturing Scenario
# =============================================================================


class TestManufacturingCorrelation:
    """End-to-end test with a realistic factory floor scenario."""

    def test_batch_tracking_across_factory(self):
        """Track a batch through MES, PLC, and robot arm logs."""
        entries = [
            # MES system logs batch start and completion
            _make_entry(
                file="/factory/mes_line3.log",
                timestamp="2024-01-15T08:00:00+00:00",
                level="INFO",
                message="Batch B-042 started on line 3",
                fields={"batch_id": "B-042", "product": "Widget-A"},
            ),
            _make_entry(
                file="/factory/mes_line3.log",
                timestamp="2024-01-15T08:30:00+00:00",
                level="INFO",
                message="Batch B-042 quality check passed",
                fields={"batch_id": "B-042"},
            ),
            # PLC logs use "lot_number" for the same concept
            _make_entry(
                file="/factory/plc_conveyor.log",
                timestamp="2024-01-15T08:05:00+00:00",
                level="INFO",
                message="Conveyor started for lot B-042",
                fields={"lot_number": "B-042", "speed_rpm": 120},
            ),
            _make_entry(
                file="/factory/plc_conveyor.log",
                timestamp="2024-01-15T08:15:00+00:00",
                level="WARN",
                message="Conveyor speed reduced",
                fields={"lot_number": "B-042", "speed_rpm": 80},
            ),
            # Robot arm logs use "work_order" for the same batch
            _make_entry(
                file="/factory/robot_arm1.log",
                timestamp="2024-01-15T08:10:00+00:00",
                level="INFO",
                message="Picking parts for work order B-042",
                fields={"work_order": "B-042", "axis": "J2"},
            ),
            # Different batch - should NOT be correlated with B-042
            _make_entry(
                file="/factory/mes_line3.log",
                timestamp="2024-01-15T09:00:00+00:00",
                level="INFO",
                message="Batch B-043 started",
                fields={"batch_id": "B-043"},
            ),
            _make_entry(
                file="/factory/plc_conveyor.log",
                timestamp="2024-01-15T09:05:00+00:00",
                level="INFO",
                message="Conveyor for lot B-043",
                fields={"lot_number": "B-043"},
            ),
        ]

        config = CorrelationsConfig(
            correlations={
                "batch-tracking": CorrelationGroup(
                    description="Track batches across MES, PLC, robot",
                    rules=[
                        FieldMatchRule(
                            type="field_match",
                            source=FieldSelector(file_pattern="mes_*.log", field="batch_id"),
                            target=FieldSelector(file_pattern="plc_*.log", field="lot_number"),
                        ),
                        FieldMatchRule(
                            type="field_match",
                            source=FieldSelector(file_pattern="mes_*.log", field="batch_id"),
                            target=FieldSelector(file_pattern="robot_*.log", field="work_order"),
                        ),
                    ],
                )
            }
        )

        result = correlate_by_rules(entries, config)

        # B-042: MES↔PLC cluster + MES↔Robot cluster
        # B-043: MES↔PLC cluster
        assert result["total_clusters"] == 3

        b042_clusters = [c for c in result["clusters"] if c["shared_value"] == "B-042"]
        assert len(b042_clusters) == 2

        # First rule: MES↔PLC for B-042
        plc_cluster = [c for c in b042_clusters if c["target_field"] == "lot_number"][0]
        assert plc_cluster["source_count"] == 2  # 2 MES entries
        assert plc_cluster["target_count"] == 2  # 2 PLC entries

        # Second rule: MES↔Robot for B-042
        robot_cluster = [c for c in b042_clusters if c["target_field"] == "work_order"][0]
        assert robot_cluster["source_count"] == 2  # 2 MES entries
        assert robot_cluster["target_count"] == 1  # 1 Robot entry

    def test_pressure_alarm_temporal_correlation(self):
        """Collect all events around a pressure drop across files."""
        entries = [
            # Normal readings
            _make_entry(
                file="/factory/sensor_pressure.log",
                timestamp="2024-01-15T14:29:55+00:00",
                level="INFO",
                message="Pressure normal",
                fields={"pressure": 3.2},
            ),
            # Pressure drop!
            _make_entry(
                file="/factory/sensor_pressure.log",
                timestamp="2024-01-15T14:30:00+00:00",
                level="WARN",
                message="Pressure below threshold",
                fields={"pressure": 1.5},
            ),
            # PLC reacts within window
            _make_entry(
                file="/factory/plc_valve.log",
                timestamp="2024-01-15T14:30:02+00:00",
                level="ERROR",
                message="Emergency valve closure",
            ),
            # Robot within window
            _make_entry(
                file="/factory/robot_arm2.log",
                timestamp="2024-01-15T14:30:03+00:00",
                level="WARN",
                message="Pausing operation due to pressure alarm",
            ),
            # Far outside window
            _make_entry(
                file="/factory/sensor_pressure.log",
                timestamp="2024-01-15T15:00:00+00:00",
                level="INFO",
                message="System recovered",
                fields={"pressure": 3.0},
            ),
        ]

        config = CorrelationsConfig(
            correlations={
                "pressure-events": CorrelationGroup(
                    description="Correlate pressure drops with all events",
                    rules=[
                        TemporalRule(
                            type="temporal",
                            anchor=EventCondition(
                                file_pattern="sensor_*.log",
                                field="pressure",
                                condition="< 2.0",
                            ),
                            window="5s",
                        )
                    ],
                )
            }
        )

        result = correlate_by_rules(entries, config)

        assert result["total_clusters"] == 1
        cluster = result["clusters"][0]
        assert cluster["rule_type"] == "temporal"
        assert cluster["window"] == "5s"
        # Should include: normal (14:29:55), drop (14:30:00), valve (14:30:02), robot (14:30:03)
        assert cluster["entry_count"] == 4
        # Should NOT include: recovered (15:00:00)
        messages = [e["message"] for e in cluster["entries"]]
        assert "System recovered" not in messages
        assert "Pressure below threshold" in messages
        assert "Emergency valve closure" in messages
