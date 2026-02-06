"""Correlation commands (M2.4, M3.4): correlation group + correlate-events."""

import click
import sys
from pathlib import Path
from typing import Optional, Dict, Any

from ._core import (
    llm,
    EXIT_SUCCESS,
    EXIT_NO_RESULTS,
    EXIT_USER_ERROR,
    EXIT_INTERNAL_ERROR,
    _output_json,
    _error_json,
    _expand_globs,
    _apply_max_bytes,
)
from ..config import find_correlations_config, load_correlations_config


@llm.group()
def correlation():
    """
    Manage and run correlation rules.

    Apply user-defined correlation rules from .logler/correlations.yaml
    to discover relationships between log entries across files.
    """
    pass


@correlation.command("list")
@click.option("--config-dir", help="Directory to search for .logler/correlations.yaml")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def correlation_list(config_dir: Optional[str], pretty: bool):
    """List available correlation rule groups.

    Shows all correlation groups defined in .logler/correlations.yaml
    with their rule types and descriptions.
    """
    try:
        search_dir = Path(config_dir) if config_dir else Path.cwd()
        config_path = find_correlations_config(search_dir)

        output: Dict[str, Any] = {
            "config_path": None,
            "groups": {},
        }

        if not config_path:
            output["error"] = "No .logler/correlations.yaml found"
            _output_json(output, pretty)
            sys.exit(EXIT_NO_RESULTS)

        output["config_path"] = str(config_path)

        try:
            config = load_correlations_config(config_path)
        except Exception as e:
            output["config_error"] = str(e)
            _output_json(output, pretty)
            sys.exit(EXIT_USER_ERROR)

        for name, group in config.correlations.items():
            rules_summary = []
            for rule in group.rules:
                if rule.type == "field_match":
                    rules_summary.append(
                        {
                            "type": "field_match",
                            "source_field": rule.source.field,
                            "target_field": rule.target.field,
                            "source_pattern": rule.source.file_pattern,
                            "target_pattern": rule.target.file_pattern,
                        }
                    )
                elif rule.type == "temporal":
                    anchor_desc = {}
                    if rule.anchor.level:
                        anchor_desc["level"] = rule.anchor.level
                    if rule.anchor.pattern:
                        anchor_desc["pattern"] = rule.anchor.pattern
                    if rule.anchor.field:
                        anchor_desc["field"] = rule.anchor.field
                        anchor_desc["condition"] = rule.anchor.condition
                    rules_summary.append(
                        {
                            "type": "temporal",
                            "anchor": anchor_desc,
                            "window": rule.window,
                        }
                    )

            output["groups"][name] = {
                "description": group.description,
                "rule_count": len(group.rules),
                "rules": rules_summary,
            }

        has_groups = bool(output["groups"])
        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS if has_groups else EXIT_NO_RESULTS)

    except SystemExit:
        raise
    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@correlation.command("run")
@click.option(
    "--files", "-f", multiple=True, required=True, help="Log files to correlate (supports globs)"
)
@click.option("--rule", "-r", "rule_name", help="Run only this named correlation group")
@click.option("--config-dir", help="Directory to search for .logler/correlations.yaml")
@click.option("--limit", type=int, help="Max clusters to return")
@click.option("--max-bytes", type=int, help="Maximum output size in bytes")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def correlation_run(
    files: tuple,
    rule_name: Optional[str],
    config_dir: Optional[str],
    limit: Optional[int],
    max_bytes: Optional[int],
    pretty: bool,
):
    """Run correlation rules against log files.

    Applies rules from .logler/correlations.yaml to discover relationships
    between entries across files. Creates virtual trace IDs linking related
    entries that share field values or temporal proximity.

    Examples:
        logler llm correlation run -f "factory/*.log"
        logler llm correlation run -f "mes_*.log" -f "plc_*.log" --rule batch-tracking
    """
    from .. import investigate
    from ..correlator import correlate_by_rules

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {list(files)}")

        # Find and load correlation config
        search_dir = Path(config_dir) if config_dir else Path.cwd()
        config_path = find_correlations_config(search_dir)
        if not config_path:
            _error_json("No .logler/correlations.yaml found. Create one or specify --config-dir.")

        config = load_correlations_config(config_path)
        if not config.correlations:
            _error_json("No correlation rules defined in config.")

        # Load all entries from files
        all_entries = []
        for file_path in file_list:
            try:
                result = investigate.search(
                    files=[file_path],
                    output_format="full",
                )
                for item in result.get("results", []):
                    entry = item.get("entry", {})
                    if entry:
                        all_entries.append(entry)
            except Exception:
                # Skip files that fail to load
                pass

        if not all_entries:
            output = {
                "config_path": str(config_path),
                "files_searched": len(file_list),
                "entries_loaded": 0,
                "clusters": [],
                "total_clusters": 0,
            }
            _output_json(output, pretty)
            sys.exit(EXIT_NO_RESULTS)

        # Run correlation
        result = correlate_by_rules(
            entries=all_entries,
            config=config,
            group_name=rule_name,
        )

        # Strip full entries from clusters for output (keep counts and metadata)
        output_clusters = []
        for cluster in result["clusters"]:
            slim = {
                "virtual_trace_id": cluster["virtual_trace_id"],
                "group": cluster["group"],
                "rule_type": cluster["rule_type"],
                "entry_count": cluster["entry_count"],
            }
            if cluster["rule_type"] == "field_match":
                slim["shared_value"] = cluster["shared_value"]
                slim["source_field"] = cluster["source_field"]
                slim["target_field"] = cluster["target_field"]
                slim["source_count"] = cluster["source_count"]
                slim["target_count"] = cluster["target_count"]
            elif cluster["rule_type"] == "temporal":
                slim["anchor_timestamp"] = cluster["anchor_timestamp"]
                slim["anchor_message"] = cluster["anchor_message"]
                slim["window"] = cluster["window"]

            # Include condensed entry references
            slim["entries"] = [
                {
                    "file": Path(e.get("file", "")).name,
                    "line_number": e.get("line_number"),
                    "timestamp": e.get("timestamp"),
                    "level": e.get("level"),
                    "message": (e.get("message") or "")[:200],
                }
                for e in cluster["entries"]
            ]

            output_clusters.append(slim)

        if limit:
            output_clusters = output_clusters[:limit]

        output = {
            "config_path": str(config_path),
            "files_searched": len(file_list),
            "entries_loaded": len(all_entries),
            "groups_applied": result["groups_applied"],
            "total_clusters": result["total_clusters"],
            "total_entries_correlated": result["total_entries_correlated"],
            "clusters": output_clusters,
        }

        if max_bytes:
            output = _apply_max_bytes(output, max_bytes)

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS if result["total_clusters"] > 0 else EXIT_NO_RESULTS)

    except SystemExit:
        raise
    except Exception as e:
        _error_json(f"Internal error in correlation run: {str(e)}", EXIT_INTERNAL_ERROR)


@llm.command("correlate-events")
@click.option(
    "--files",
    "-f",
    multiple=True,
    required=True,
    help="Log files to search across (supports globs)",
)
@click.option(
    "--anchor-timestamp",
    help="ISO8601 timestamp to correlate around",
)
@click.option(
    "--anchor-file",
    help="File path of the anchor entry",
)
@click.option(
    "--anchor-line",
    type=int,
    help="Line number of the anchor entry",
)
@click.option(
    "--trigger-level",
    help="Find trigger events by log level (e.g., ERROR)",
)
@click.option(
    "--trigger-pattern",
    help="Find trigger events by regex pattern",
)
@click.option(
    "--trigger-field",
    help="Field name for trigger condition",
)
@click.option(
    "--trigger-condition",
    help="Numeric condition for trigger field (e.g., '< 2.0')",
)
@click.option(
    "--window",
    "-w",
    default="5s",
    help="Time window around events (e.g., 5s, 1m, 500ms)",
)
@click.option("--limit", type=int, help="Max clusters to return")
@click.option("--max-bytes", type=int, help="Maximum output size in bytes")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def correlate_events_cmd(
    files: tuple,
    anchor_timestamp: Optional[str],
    anchor_file: Optional[str],
    anchor_line: Optional[int],
    trigger_level: Optional[str],
    trigger_pattern: Optional[str],
    trigger_field: Optional[str],
    trigger_condition: Optional[str],
    window: str,
    limit: Optional[int],
    max_bytes: Optional[int],
    pretty: bool,
):
    """Find all events across files within a time window of reference events.

    Three modes of operation:

    1. Anchor entry: Specify --anchor-file and --anchor-line to correlate
       around a specific log entry.

    2. Anchor timestamp: Specify --anchor-timestamp to correlate around
       a point in time.

    3. Trigger-based: Specify --trigger-level, --trigger-pattern, or
       --trigger-field/--trigger-condition to automatically find trigger
       events and correlate around each one.

    Examples:
        logler llm correlate-events -f "*.log" --anchor-timestamp "2024-01-15T10:00:13Z" -w 5s
        logler llm correlate-events -f "*.log" --trigger-level ERROR -w 3s
        logler llm correlate-events -f "sensor_*.log" -f "plc_*.log" --trigger-field pressure --trigger-condition "< 2.0" -w 10s
    """
    from .. import investigate
    from ..event_correlator import correlate_events

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {list(files)}")

        # Build anchor_entry if file+line specified
        anchor_entry = None
        if anchor_file and anchor_line:
            try:
                result = investigate.search(files=[anchor_file])
                for item in result.get("results", []):
                    entry = item.get("entry", {})
                    if entry.get("line_number") == anchor_line:
                        anchor_entry = entry
                        break
                if anchor_entry is None:
                    _error_json(f"Could not find entry at {anchor_file}:{anchor_line}")
            except Exception as e:
                _error_json(f"Failed to read anchor file: {e}")

        # Build trigger dict if trigger options specified
        trigger = None
        has_trigger = any([trigger_level, trigger_pattern, trigger_field])
        if has_trigger:
            trigger = {}
            if trigger_level:
                trigger["level"] = trigger_level
            if trigger_pattern:
                trigger["pattern"] = trigger_pattern
            if trigger_field:
                trigger["field"] = trigger_field
            if trigger_condition:
                trigger["condition"] = trigger_condition

        # Must have at least one mode
        if anchor_entry is None and anchor_timestamp is None and trigger is None:
            _error_json(
                "Must specify one of: --anchor-file/--anchor-line, "
                "--anchor-timestamp, or --trigger-level/--trigger-pattern/--trigger-field"
            )

        # Run correlation
        result = correlate_events(
            files=file_list,
            anchor_entry=anchor_entry,
            anchor_timestamp=anchor_timestamp,
            trigger=trigger,
            window=window,
            limit=limit,
        )

        if result.get("error"):
            _error_json(result["error"])

        # Slim down entries in clusters for output
        output_clusters = []
        for cluster in result.get("clusters", []):
            slim = {
                "virtual_trace_id": cluster["virtual_trace_id"],
                "rule_type": cluster["rule_type"],
                "anchor_timestamp": cluster.get("anchor_timestamp"),
                "anchor_message": cluster.get("anchor_message"),
                "anchor_file": cluster.get("anchor_file"),
                "window": cluster["window"],
                "entry_count": cluster["entry_count"],
            }

            if cluster["rule_type"] == "event_trigger":
                slim["trigger"] = cluster.get("trigger")

            # Condensed entry references
            slim["entries"] = [
                {
                    "file": Path(e.get("file", "")).name,
                    "line_number": e.get("line_number"),
                    "timestamp": e.get("timestamp"),
                    "level": e.get("level"),
                    "message": (e.get("message") or "")[:200],
                }
                for e in cluster["entries"]
            ]

            output_clusters.append(slim)

        output = {
            "files_searched": result["files_searched"],
            "window": result["window"],
            "total_clusters": result["total_clusters"],
            "total_entries_correlated": result["total_entries_correlated"],
            "clusters": output_clusters,
        }

        if max_bytes:
            output = _apply_max_bytes(output, max_bytes)

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS if result["total_clusters"] > 0 else EXIT_NO_RESULTS)

    except SystemExit:
        raise
    except Exception as e:
        _error_json(f"Internal error in correlate-events: {str(e)}", EXIT_INTERNAL_ERROR)
