"""Tests for correlation config schema and loading (M2.1)."""

from __future__ import annotations

import textwrap
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from logler.config import (
    CorrelationGroup,
    CorrelationsConfig,
    EventCondition,
    FieldMatchRule,
    FieldSelector,
    TemporalRule,
    find_correlations_config,
    load_correlations_config,
    parse_duration,
)


# =============================================================================
# Duration Parsing
# =============================================================================


class TestParseDuration:
    """Test the parse_duration utility for time window strings."""

    def test_parse_seconds(self) -> None:
        assert parse_duration("5s") == timedelta(seconds=5)

    def test_parse_milliseconds(self) -> None:
        assert parse_duration("500ms") == timedelta(milliseconds=500)

    def test_parse_minutes(self) -> None:
        assert parse_duration("1m") == timedelta(minutes=1)

    def test_parse_hours(self) -> None:
        assert parse_duration("2h") == timedelta(hours=2)

    def test_parse_fractional_seconds(self) -> None:
        assert parse_duration("1.5s") == timedelta(seconds=1.5)

    def test_parse_fractional_minutes(self) -> None:
        assert parse_duration("0.5m") == timedelta(seconds=30)

    def test_parse_with_whitespace(self) -> None:
        assert parse_duration("  5s  ") == timedelta(seconds=5)

    def test_invalid_unit_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("5d")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("")

    def test_no_number_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("s")

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("-5s")


# =============================================================================
# Model Construction (Unit Tests)
# =============================================================================


class TestFieldSelector:
    """Test FieldSelector model validation."""

    def test_minimal_field_only(self) -> None:
        sel = FieldSelector(field="batch_id")
        assert sel.field == "batch_id"
        assert sel.file_pattern is None

    def test_with_file_pattern(self) -> None:
        sel = FieldSelector(file_pattern="mes_*.log", field="batch_id")
        assert sel.file_pattern == "mes_*.log"
        assert sel.field == "batch_id"

    def test_missing_field_raises(self) -> None:
        with pytest.raises(ValidationError):
            FieldSelector()  # type: ignore[call-arg]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FieldSelector(field="x", unknown="bad")  # type: ignore[call-arg]


class TestEventCondition:
    """Test EventCondition model validation."""

    def test_field_with_condition(self) -> None:
        cond = EventCondition(field="pressure", condition="< 2.0")
        assert cond.field == "pressure"
        assert cond.condition == "< 2.0"

    def test_level_only(self) -> None:
        cond = EventCondition(level="ERROR")
        assert cond.level == "ERROR"

    def test_pattern_only(self) -> None:
        cond = EventCondition(pattern=r"timeout|connection refused")
        assert cond.pattern == r"timeout|connection refused"

    def test_file_pattern_with_level(self) -> None:
        cond = EventCondition(file_pattern="plc_*.log", level="ALARM")
        assert cond.file_pattern == "plc_*.log"
        assert cond.level == "ALARM"

    def test_empty_condition_raises(self) -> None:
        """Must specify at least one of field+condition, level, or pattern."""
        with pytest.raises(ValidationError, match="at least one"):
            EventCondition()

    def test_only_file_pattern_raises(self) -> None:
        """file_pattern alone is not enough - need a matching criterion."""
        with pytest.raises(ValidationError, match="at least one"):
            EventCondition(file_pattern="*.log")

    def test_invalid_regex_pattern_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid anchor pattern"):
            EventCondition(pattern="(?P<unclosed")

    def test_valid_complex_pattern(self) -> None:
        cond = EventCondition(
            file_pattern="sensor_*.log",
            field="pressure",
            condition="< 2.0",
            pattern=r"CRIT.*pressure",
        )
        assert cond.field == "pressure"
        assert cond.condition == "< 2.0"
        assert cond.pattern == r"CRIT.*pressure"


class TestFieldMatchRule:
    """Test FieldMatchRule model validation."""

    def test_basic_field_match(self) -> None:
        rule = FieldMatchRule(
            type="field_match",
            source=FieldSelector(file_pattern="mes_*.log", field="batch_id"),
            target=FieldSelector(file_pattern="plc_*.log", field="lot_number"),
        )
        assert rule.type == "field_match"
        assert rule.source.field == "batch_id"
        assert rule.target.field == "lot_number"

    def test_wrong_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            FieldMatchRule(
                type="temporal",  # type: ignore[arg-type]
                source=FieldSelector(field="a"),
                target=FieldSelector(field="b"),
            )

    def test_missing_source_raises(self) -> None:
        with pytest.raises(ValidationError):
            FieldMatchRule(
                type="field_match",
                target=FieldSelector(field="b"),
            )  # type: ignore[call-arg]


class TestTemporalRule:
    """Test TemporalRule model validation."""

    def test_basic_temporal_rule(self) -> None:
        rule = TemporalRule(
            type="temporal",
            anchor=EventCondition(
                file_pattern="sensor_*.log",
                field="pressure",
                condition="< 2.0",
            ),
            window="5s",
        )
        assert rule.type == "temporal"
        assert rule.window == "5s"
        assert rule.anchor.field == "pressure"

    def test_invalid_window_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid duration"):
            TemporalRule(
                type="temporal",
                anchor=EventCondition(level="ERROR"),
                window="5days",
            )

    def test_millisecond_window(self) -> None:
        rule = TemporalRule(
            type="temporal",
            anchor=EventCondition(level="FATAL"),
            window="200ms",
        )
        assert rule.window == "200ms"


class TestCorrelationGroup:
    """Test CorrelationGroup model validation."""

    def test_group_with_description(self) -> None:
        group = CorrelationGroup(
            description="Track batches across MES and PLC",
            rules=[
                FieldMatchRule(
                    type="field_match",
                    source=FieldSelector(file_pattern="mes_*.log", field="batch_id"),
                    target=FieldSelector(file_pattern="plc_*.log", field="lot_number"),
                )
            ],
        )
        assert group.description == "Track batches across MES and PLC"
        assert len(group.rules) == 1

    def test_empty_rules_raises(self) -> None:
        with pytest.raises(ValidationError):
            CorrelationGroup(rules=[])

    def test_mixed_rule_types(self) -> None:
        group = CorrelationGroup(
            rules=[
                FieldMatchRule(
                    type="field_match",
                    source=FieldSelector(field="batch_id"),
                    target=FieldSelector(field="lot_number"),
                ),
                TemporalRule(
                    type="temporal",
                    anchor=EventCondition(level="ERROR"),
                    window="10s",
                ),
            ]
        )
        assert len(group.rules) == 2
        assert group.rules[0].type == "field_match"
        assert group.rules[1].type == "temporal"


# =============================================================================
# YAML Loading
# =============================================================================


class TestLoadCorrelationsConfig:
    """Test loading .logler/correlations.yaml files."""

    def test_load_field_match_correlations(self, tmp_path: Path) -> None:
        """Load a config with field-match correlation rules."""
        config_file = tmp_path / ".logler" / "correlations.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            textwrap.dedent(
                """\
            correlations:
              batch-tracking:
                description: "Link MES batch IDs to PLC lot numbers"
                rules:
                  - type: field_match
                    source:
                      file_pattern: "mes_*.log"
                      field: batch_id
                    target:
                      file_pattern: "plc_*.log"
                      field: lot_number
        """
            )
        )

        config = load_correlations_config(config_file)
        assert "batch-tracking" in config.correlations
        group = config.correlations["batch-tracking"]
        assert group.description == "Link MES batch IDs to PLC lot numbers"
        assert len(group.rules) == 1
        rule = group.rules[0]
        assert isinstance(rule, FieldMatchRule)
        assert rule.source.file_pattern == "mes_*.log"
        assert rule.source.field == "batch_id"
        assert rule.target.file_pattern == "plc_*.log"
        assert rule.target.field == "lot_number"

    def test_load_temporal_correlations(self, tmp_path: Path) -> None:
        """Load a config with temporal correlation rules."""
        config_file = tmp_path / ".logler" / "correlations.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            textwrap.dedent(
                """\
            correlations:
              pressure-events:
                rules:
                  - type: temporal
                    anchor:
                      file_pattern: "sensor_*.log"
                      field: pressure
                      condition: "< 2.0"
                    window: "5s"
        """
            )
        )

        config = load_correlations_config(config_file)
        group = config.correlations["pressure-events"]
        assert len(group.rules) == 1
        rule = group.rules[0]
        assert isinstance(rule, TemporalRule)
        assert rule.anchor.file_pattern == "sensor_*.log"
        assert rule.anchor.field == "pressure"
        assert rule.anchor.condition == "< 2.0"
        assert rule.window == "5s"

    def test_load_mixed_rule_types(self, tmp_path: Path) -> None:
        """Load a config with both field_match and temporal rules."""
        config_file = tmp_path / ".logler" / "correlations.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            textwrap.dedent(
                """\
            correlations:
              production-line:
                description: "Full production line correlation"
                rules:
                  - type: field_match
                    source:
                      file_pattern: "mes_*.log"
                      field: work_order
                    target:
                      file_pattern: "robot_*.log"
                      field: job_id
                  - type: temporal
                    anchor:
                      level: ERROR
                      pattern: "emergency stop"
                    window: "30s"
        """
            )
        )

        config = load_correlations_config(config_file)
        group = config.correlations["production-line"]
        assert len(group.rules) == 2
        assert isinstance(group.rules[0], FieldMatchRule)
        assert isinstance(group.rules[1], TemporalRule)
        assert group.rules[1].anchor.level == "ERROR"
        assert group.rules[1].anchor.pattern == "emergency stop"

    def test_load_multiple_groups(self, tmp_path: Path) -> None:
        """Load a config with multiple correlation groups."""
        config_file = tmp_path / ".logler" / "correlations.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            textwrap.dedent(
                """\
            correlations:
              batch-tracking:
                rules:
                  - type: field_match
                    source:
                      field: batch_id
                    target:
                      field: lot_number
              error-blast-radius:
                rules:
                  - type: temporal
                    anchor:
                      level: FATAL
                    window: "10s"
        """
            )
        )

        config = load_correlations_config(config_file)
        assert len(config.correlations) == 2
        assert "batch-tracking" in config.correlations
        assert "error-blast-radius" in config.correlations

    def test_load_empty_file_returns_empty_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".logler" / "correlations.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("")

        config = load_correlations_config(config_file)
        assert isinstance(config, CorrelationsConfig)
        assert config.correlations == {}

    def test_load_empty_correlations_returns_empty(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".logler" / "correlations.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("correlations: {}\n")

        config = load_correlations_config(config_file)
        assert config.correlations == {}

    def test_missing_file_raises_filenotfounderror(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_correlations_config(tmp_path / "nope.yaml")

    def test_invalid_yaml_raises_valueerror(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".logler" / "correlations.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("correlations:\n  bad:\n    - [invalid yaml {{{\n")

        with pytest.raises(ValueError, match="Invalid YAML"):
            load_correlations_config(config_file)

    def test_non_dict_yaml_raises_valueerror(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".logler" / "correlations.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("- item1\n- item2\n")

        with pytest.raises(ValueError, match="Expected a YAML mapping"):
            load_correlations_config(config_file)

    def test_extra_fields_rejected(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".logler" / "correlations.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            textwrap.dedent(
                """\
            correlations:
              test:
                rules:
                  - type: field_match
                    source:
                      field: a
                    target:
                      field: b
                unknown_field: "should fail"
        """
            )
        )

        with pytest.raises(ValidationError):
            load_correlations_config(config_file)

    def test_invalid_rule_type_rejected(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".logler" / "correlations.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            textwrap.dedent(
                """\
            correlations:
              test:
                rules:
                  - type: unknown_type
                    source:
                      field: a
        """
            )
        )

        with pytest.raises(ValidationError):
            load_correlations_config(config_file)


# =============================================================================
# Config File Discovery
# =============================================================================


class TestFindCorrelationsConfig:
    """Test .logler/correlations.yaml discovery."""

    def test_find_in_current_directory(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".logler" / "correlations.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("correlations: {}\n")

        result = find_correlations_config(tmp_path)
        assert result is not None
        assert result == config_file

    def test_find_in_parent_directory(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".logler" / "correlations.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("correlations: {}\n")

        nested = tmp_path / "project" / "logs"
        nested.mkdir(parents=True)

        result = find_correlations_config(nested)
        assert result is not None
        assert result == config_file

    def test_returns_none_when_no_config(self, tmp_path: Path) -> None:
        nested = tmp_path / "project" / "src"
        nested.mkdir(parents=True)

        result = find_correlations_config(nested)
        assert result is None

    def test_independent_of_formats_config(self, tmp_path: Path) -> None:
        """correlations.yaml discovery is independent of formats.yaml."""
        # Only formats.yaml exists, not correlations.yaml
        formats_file = tmp_path / ".logler" / "formats.yaml"
        formats_file.parent.mkdir(parents=True)
        formats_file.write_text("formats: {}\n")

        result = find_correlations_config(tmp_path)
        assert result is None


# =============================================================================
# Realistic Manufacturing Scenarios
# =============================================================================


class TestManufacturingCorrelationScenarios:
    """End-to-end tests with realistic industrial correlation configs."""

    def test_full_factory_floor_config(self, tmp_path: Path) -> None:
        """Load a realistic multi-group factory floor correlation config."""
        config_file = tmp_path / ".logler" / "correlations.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            textwrap.dedent(
                """\
            correlations:
              batch-tracking:
                description: "Track batches from MES through PLC and robot arms"
                rules:
                  - type: field_match
                    source:
                      file_pattern: "mes_*.log"
                      field: batch_id
                    target:
                      file_pattern: "plc_*.log"
                      field: lot_number
                  - type: field_match
                    source:
                      file_pattern: "mes_*.log"
                      field: batch_id
                    target:
                      file_pattern: "robot_*.log"
                      field: work_order

              pressure-alarm:
                description: "Correlate pressure drops with all system events"
                rules:
                  - type: temporal
                    anchor:
                      file_pattern: "sensor_*.log"
                      field: pressure
                      condition: "< 2.0"
                    window: "5s"

              emergency-stop:
                description: "Collect all events around emergency stops"
                rules:
                  - type: temporal
                    anchor:
                      level: FATAL
                      pattern: "emergency.stop|e-stop"
                    window: "30s"
        """
            )
        )

        config = load_correlations_config(config_file)

        assert len(config.correlations) == 3

        # Batch tracking has 2 field_match rules
        batch = config.correlations["batch-tracking"]
        assert len(batch.rules) == 2
        assert all(isinstance(r, FieldMatchRule) for r in batch.rules)
        assert batch.rules[0].source.field == "batch_id"
        assert batch.rules[0].target.field == "lot_number"
        assert batch.rules[1].target.field == "work_order"

        # Pressure alarm
        pressure = config.correlations["pressure-alarm"]
        assert len(pressure.rules) == 1
        rule = pressure.rules[0]
        assert isinstance(rule, TemporalRule)
        assert rule.anchor.condition == "< 2.0"
        assert rule.window == "5s"

        # Emergency stop
        estop = config.correlations["emergency-stop"]
        rule = estop.rules[0]
        assert isinstance(rule, TemporalRule)
        assert rule.anchor.level == "FATAL"
        assert rule.anchor.pattern == "emergency.stop|e-stop"
        assert rule.window == "30s"

    def test_full_workflow_find_load_correlations(self, tmp_path: Path) -> None:
        """Full workflow: find correlations config, load it, inspect rules."""
        config_dir = tmp_path / "factory" / ".logler"
        config_dir.mkdir(parents=True)
        (config_dir / "correlations.yaml").write_text(
            textwrap.dedent(
                """\
            correlations:
              conveyor-jam:
                description: "Detect conveyor jam cascades"
                rules:
                  - type: temporal
                    anchor:
                      file_pattern: "conveyor_*.log"
                      pattern: "jam detected"
                    window: "10s"
        """
            )
        )

        work_dir = tmp_path / "factory" / "line_3" / "logs"
        work_dir.mkdir(parents=True)

        config_path = find_correlations_config(work_dir)
        assert config_path is not None

        config = load_correlations_config(config_path)
        assert "conveyor-jam" in config.correlations
        group = config.correlations["conveyor-jam"]
        assert len(group.rules) == 1
        assert isinstance(group.rules[0], TemporalRule)
        assert group.rules[0].window == "10s"
