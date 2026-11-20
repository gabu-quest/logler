"""
Logler Pydantic Models - Type-safe data structures for log analysis.

This module provides Pydantic models for all data structures returned by
the logler investigate module. These models provide:
- Full type safety with IDE autocomplete
- Runtime validation
- JSON serialization/deserialization
- Clear documentation of all fields

Example:
    from logler.models import SearchResults, LogEntry

    # Type-safe access to search results
    results = SearchResults.model_validate(investigate.search(files=["app.log"]))
    for result in results.results:
        entry: LogEntry = result.entry
        print(f"{entry.timestamp} [{entry.level}] {entry.message}")
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LogLevel(str, Enum):  # noqa: UP042 - StrEnum changes str() and format() of a member
    """Log severity levels."""

    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class LogFormat(str, Enum):  # noqa: UP042 - StrEnum changes str() and format() of a member
    """Detected log format."""

    JSON = "Json"
    LOGFMT = "Logfmt"
    SYSLOG = "Syslog"
    PLAIN_TEXT = "PlainText"
    CUSTOM = "Custom"
    UNKNOWN = "Unknown"


class NodeType(str, Enum):  # noqa: UP042 - StrEnum changes str() and format() of a member
    """Type of hierarchy node."""

    THREAD = "Thread"
    SPAN = "Span"
    CORRELATION_GROUP = "CorrelationGroup"
    UNKNOWN = "Unknown"


class DetectionMethod(str, Enum):  # noqa: UP042 - StrEnum changes str() and format() of a member
    """How hierarchy relationships were detected."""

    EXPLICIT_PARENT_ID = "ExplicitParentId"
    NAMING_PATTERN = "NamingPattern"
    TEMPORAL_INFERENCE = "TemporalInference"
    CORRELATION_CHAIN = "CorrelationChain"
    MIXED = "Mixed"
    UNKNOWN = "Unknown"


# =============================================================================
# Core Log Entry Models
# =============================================================================


class LogEntry(BaseModel):
    """A single parsed log entry."""

    id: str | None = Field(None, description="Entry identifier")
    line_number: int = Field(description="Line number in source file")
    timestamp: str | None = Field(None, description="ISO8601 timestamp")
    level: str | None = Field(None, description="Log level (ERROR, WARN, INFO, etc.)")
    message: str | None = Field(None, description="Log message content")
    raw: str | None = Field(None, description="Raw original log line")
    file: str | None = Field(None, description="Source file path")
    format: str | None = Field(None, description="Detected log format")

    # Correlation/tracing fields
    thread_id: str | None = Field(None, description="Thread identifier")
    correlation_id: str | None = Field(None, description="Correlation/request ID")
    trace_id: str | None = Field(None, description="Distributed trace ID")
    span_id: str | None = Field(None, description="Span ID within trace")
    parent_span_id: str | None = Field(None, description="Parent span ID")

    # OpenTelemetry fields
    service_name: str | None = Field(None, description="Service name")
    operation_name: str | None = Field(None, description="Operation/span name")
    duration_ms: float | None = Field(None, description="Duration in milliseconds")

    # Additional structured fields
    fields: dict[str, Any] = Field(default_factory=dict, description="Additional parsed fields")
    extra: dict[str, Any] = Field(default_factory=dict, description="Extra/custom fields")

    model_config = ConfigDict(extra="allow")


# =============================================================================
# Search Models
# =============================================================================


class SearchResult(BaseModel):
    """A single search result with context."""

    entry: LogEntry = Field(description="The matching log entry")
    context_before: list[LogEntry] = Field(
        default_factory=list, description="Log entries before the match"
    )
    context_after: list[LogEntry] = Field(
        default_factory=list, description="Log entries after the match"
    )
    relevance_score: float | None = Field(None, description="Search relevance score")


class SearchResults(BaseModel):
    """Results from a log search operation."""

    results: list[SearchResult] = Field(default_factory=list, description="Search results")
    total_matches: int = Field(0, description="Total number of matches")
    search_time_ms: int | None = Field(None, description="Search duration in ms")

    # Aggregations
    by_level: dict[str, int] = Field(default_factory=dict, description="Counts by log level")
    by_file: dict[str, int] = Field(default_factory=dict, description="Counts by file")
    by_thread: dict[str, int] = Field(default_factory=dict, description="Counts by thread")


class SearchSummary(BaseModel):
    """Summarized search results (output_format='summary')."""

    total_matches: int = Field(0, description="Total number of matches")
    unique_messages: int = Field(0, description="Number of unique message patterns")
    log_levels: dict[str, int] = Field(default_factory=dict, description="Counts by level")
    by_file: dict[str, int] = Field(default_factory=dict, description="Counts by file")
    full_results_available: bool | None = Field(
        None, description="Whether the full results can be asked for"
    )
    top_messages: list[dict[str, Any]] = Field(
        default_factory=list, description="Most common messages with counts"
    )
    sample_entries: list[LogEntry] = Field(
        default_factory=list, description="Sample matching entries"
    )


class SearchCount(BaseModel):
    """Count-only search results (output_format='count')."""

    total_matches: int = Field(0, description="Total number of matches")
    by_level: dict[str, int] = Field(default_factory=dict, description="Counts by level")
    by_file: dict[str, int] = Field(default_factory=dict, description="Counts by file")
    time_range: dict[str, str] | None = Field(None, description="Start/end timestamps")


# =============================================================================
# Thread/Timeline Models
# =============================================================================


class ThreadTimeline(BaseModel):
    """Timeline of entries for a thread/correlation/trace."""

    entries: list[LogEntry] = Field(default_factory=list, description="Chronological entries")
    total_entries: int = Field(0, description="Total number of entries")
    duration_ms: int | None = Field(None, description="Total duration in ms")
    unique_spans: list[str] = Field(default_factory=list, description="Unique span IDs found")
    services: list[str] = Field(default_factory=list, description="Services involved")


# =============================================================================
# Hierarchy Models
# =============================================================================


class BottleneckInfo(BaseModel):
    """Information about a performance bottleneck."""

    node_id: str = Field(description="ID of the bottleneck node")
    node_name: str | None = Field(None, description="Name of the bottleneck node")
    duration_ms: int = Field(0, description="Duration in milliseconds")
    percentage: float = Field(0.0, description="Percentage of total time")
    depth: int = Field(0, description="Depth in hierarchy")


class SpanNode(BaseModel):
    """A node in the thread/span hierarchy tree."""

    id: str = Field(description="Node identifier (thread_id, span_id, or correlation_id)")
    node_type: str = Field("Unknown", description="Node type: Thread, Span, CorrelationGroup")
    name: str | None = Field(None, description="Human-readable operation name")
    parent_id: str | None = Field(None, description="Parent node ID")
    children: list[SpanNode] = Field(default_factory=list, description="Child nodes")

    # Entry references
    entry_ids: list[str] = Field(default_factory=list, description="Identifiers of entries")
    entry_count: int = Field(0, description="Number of log entries in this node")
    service: str | None = Field(
        None, description="Service of the first entry that names one; None when none does"
    )

    # Timing
    start_time: str | None = Field(None, description="Start timestamp (ISO8601)")
    end_time: str | None = Field(None, description="End timestamp (ISO8601)")
    duration_ms: int | None = Field(None, description="Duration in milliseconds")

    # Statistics
    error_count: int = Field(0, description="Number of error entries")
    level_counts: dict[str, int] = Field(default_factory=dict, description="Entries by level")

    # Hierarchy metadata
    depth: int = Field(0, description="Depth in tree (0 = root)")
    confidence: float = Field(1.0, description="Confidence score for relationship (0.0-1.0)")
    relationship_evidence: list[str] = Field(
        default_factory=list, description="Evidence for parent-child relationship"
    )

    model_config = ConfigDict(extra="allow")


# Allow recursive definition
SpanNode.model_rebuild()


class ThreadHierarchy(BaseModel):
    """Complete thread/span hierarchy tree."""

    roots: list[SpanNode] = Field(default_factory=list, description="Root nodes")
    total_nodes: int = Field(0, description="Total number of nodes")
    max_depth: int = Field(0, description="Maximum depth of tree")
    total_duration_ms: int | None = Field(None, description="Total duration")
    concurrent_count: int = Field(0, description="Number of concurrent operations")
    bottleneck: BottleneckInfo | None = Field(None, description="Performance bottleneck")
    error_nodes: list[str] = Field(default_factory=list, description="Node IDs with errors")
    detection_method: str = Field("Unknown", description="How relationships were detected")
    detection_methods: list[str] = Field(
        default_factory=list, description="Detection methods used (detailed)"
    )


# =============================================================================
# Pattern Detection Models
# =============================================================================


class PatternMatch(BaseModel):
    """A detected log pattern."""

    pattern: str = Field(description="Regex pattern or template")
    pattern_type: str | None = Field(None, description="Kind of pattern, such as RepeatedError")
    template: str | None = Field(None, description="Human-readable template")
    occurrences: int = Field(0, description="Number of occurrences")
    affected_threads: list[str] = Field(default_factory=list, description="Threads it occurs in")
    first_seen: str | None = Field(None, description="First occurrence timestamp")
    last_seen: str | None = Field(None, description="Last occurrence timestamp")
    examples: list[LogEntry] = Field(default_factory=list, description="Example entries")
    by_level: dict[str, int] = Field(default_factory=dict, description="Counts by level")
    by_thread: dict[str, int] = Field(default_factory=dict, description="Counts by thread")


class PatternResults(BaseModel):
    """Results from pattern detection."""

    patterns: list[PatternMatch] = Field(default_factory=list, description="Detected patterns")
    total_entries: int = Field(0, description="Total entries analyzed")
    unique_patterns: int = Field(0, description="Number of unique patterns")
    coverage: float = Field(0.0, description="Percentage of entries matching patterns")


# =============================================================================
# Sampling Models
# =============================================================================


class SamplingResult(BaseModel):
    """Results from log sampling."""

    samples: list[LogEntry] = Field(default_factory=list, description="Sampled entries")
    coverage: dict[str, Any] = Field(default_factory=dict, description="What the sample covers")
    total_population: int = Field(0, description="Total entries in source")
    sample_size: int = Field(0, description="Number of sampled entries")
    strategy: str = Field("random", description="Sampling strategy used")
    level_distribution: dict[str, int] = Field(
        default_factory=dict, description="Level distribution in sample"
    )
    unique_threads: int = Field(0, description="Number of unique threads in sample")
    time_range: dict[str, str] | None = Field(None, description="Time range covered")


# =============================================================================
# Error Analysis Models
# =============================================================================


class RootCause(BaseModel):
    """A potential root cause of errors."""

    node_id: str = Field(description="Node ID of root cause")
    node_type: str = Field("Unknown", description="Type of node")
    error_count: int = Field(0, description="Number of errors")
    depth: int = Field(0, description="Depth in hierarchy")
    timestamp: str | None = Field(None, description="First error timestamp")
    path: list[str] = Field(default_factory=list, description="Path from root to this node")
    is_leaf: bool = Field(False, description="Whether this is a leaf node")
    confidence: float = Field(0.0, description="Confidence this is root cause")


class PropagationChain(BaseModel):
    """Error propagation chain through hierarchy."""

    root_cause: str = Field(description="Root cause node ID")
    chain: list[dict[str, Any]] = Field(default_factory=list, description="Chain of affected nodes")
    total_affected: int = Field(0, description="Total nodes affected")
    propagation_type: str = Field("upward", description="Direction of propagation")


class ImpactSummary(BaseModel):
    """Summary of error impact."""

    total_affected_nodes: int = Field(0, description="Total nodes with errors")
    affected_percentage: float = Field(0.0, description="Percentage of hierarchy affected")
    max_propagation_depth: int = Field(0, description="Maximum depth of error propagation")
    concurrent_failures: int = Field(0, description="Number of concurrent failures")


class ErrorAnalysis(BaseModel):
    """Complete error flow analysis."""

    has_errors: bool = Field(False, description="Whether any errors were found")
    total_error_nodes: int = Field(0, description="Total nodes with errors")
    root_causes: list[RootCause] = Field(default_factory=list, description="Identified root causes")
    propagation_chains: list[PropagationChain] = Field(
        default_factory=list, description="Error propagation chains"
    )
    impact_summary: ImpactSummary = Field(
        default_factory=ImpactSummary, description="Impact summary"
    )
    recommendations: list[str] = Field(default_factory=list, description="Suggested actions")


# =============================================================================
# File/Context Models
# =============================================================================


class FileMetadata(BaseModel):
    """Metadata about a log file."""

    path: str = Field(description="File path")
    size_bytes: int = Field(0, description="File size in bytes")
    lines: int = Field(0, description="Total line count")
    entry_count: int = Field(0, description="Parsed entry count")
    format: str = Field("Unknown", description="Detected log format")
    time_range: dict[str, str] | None = Field(None, description="Time range of entries")
    log_levels: dict[str, int] = Field(default_factory=dict, description="Counts by level")
    available_fields: list[str] = Field(default_factory=list, description="Fields the entries have")
    unique_threads: int = Field(0, description="Number of distinct threads")
    unique_correlation_ids: int = Field(0, description="Number of distinct correlation IDs")


class ContextResult(BaseModel):
    """Context around a specific log line."""

    target: LogEntry = Field(description="The target log entry")
    context_before: list[LogEntry] = Field(
        default_factory=list, description="Entries before target"
    )
    context_after: list[LogEntry] = Field(default_factory=list, description="Entries after target")
    related_threads: list[Any] = Field(default_factory=list, description="Threads related to it")


# =============================================================================
# Cross-Service Timeline Models
# =============================================================================


class TimelineEntry(BaseModel):
    """An entry in a cross-service timeline."""

    service: str = Field(description="Service name")
    timestamp: str | None = Field(None, description="Entry timestamp")
    entry: LogEntry = Field(description="The log entry")
    relative_time_ms: int = Field(0, description="Time offset from start in ms")


class CrossServiceTimeline(BaseModel):
    """Timeline spanning multiple services."""

    timeline: list[TimelineEntry] = Field(default_factory=list, description="Chronological entries")
    services: list[str] = Field(default_factory=list, description="Services involved")
    total_entries: int = Field(0, description="Total number of entries")
    duration_ms: int | None = Field(None, description="Total duration")
    service_breakdown: dict[str, int] = Field(
        default_factory=dict, description="Entry count by service"
    )


# =============================================================================
# Correlation Chain Models
# =============================================================================


class CorrelationLink(BaseModel):
    """A link between correlated requests."""

    parent_correlation_id: str = Field(description="Parent correlation ID")
    child_correlation_id: str = Field(description="Child correlation ID")
    evidence: str = Field(description="Evidence for the link")
    timestamp: str | None = Field(None, description="When link was detected")
    confidence: float = Field(0.0, description="Confidence score")


class CorrelationChains(BaseModel):
    """Detected correlation ID chains."""

    chains: list[CorrelationLink] = Field(default_factory=list, description="Correlation links")
    root_ids: list[str] = Field(default_factory=list, description="Root correlation IDs")
    hierarchy: dict[str, list[str]] = Field(
        default_factory=dict, description="Parent to children mapping"
    )
    total_unique_ids: int = Field(0, description="Total unique correlation IDs")
    total_chains: int = Field(0, description="Number of chains")
    total_correlation_ids: int = Field(0, description="Number of correlation IDs seen")


# =============================================================================
# Export Models
# =============================================================================


class TraceSpan(BaseModel):
    """A span for trace export (Jaeger/Zipkin compatible)."""

    trace_id: str = Field(description="Trace ID")
    span_id: str = Field(description="Span ID")
    operation_name: str = Field(description="Operation name")
    parent_span_id: str | None = Field(None, description="Parent span ID")
    service_name: str = Field(description="Service name")
    start_time: str = Field(description="Start timestamp (ISO8601)")
    duration_us: int = Field(0, description="Duration in microseconds")
    tags: dict[str, str] = Field(default_factory=dict, description="Span tags")
    logs: list[dict[str, Any]] = Field(default_factory=list, description="Span logs/events")


class TraceExport(BaseModel):
    """Exported trace data."""

    format: str = Field(description="Export format (jaeger, zipkin)")
    traces: list[dict[str, Any]] = Field(default_factory=list, description="Trace data")
    span_count: int = Field(0, description="Total number of spans")


# =============================================================================
# AI Insights Models
# =============================================================================


class Insight(BaseModel):
    """An AI-generated insight about logs."""

    type: str = Field(description="Insight type")
    severity: str = Field("info", description="Severity: info, warning, critical")
    description: str = Field(description="Human-readable description")
    count: int | None = Field(None, description="Related count if applicable")
    suggestion: str | None = Field(None, description="Suggested action")
    evidence: list[str] = Field(default_factory=list, description="Supporting evidence")


class InsightsResult(BaseModel):
    """Results from AI insights analysis."""

    overview: dict[str, Any] = Field(default_factory=dict, description="Overview statistics")
    insights: list[Insight] = Field(default_factory=list, description="Generated insights")
    next_steps: list[str] = Field(default_factory=list, description="Recommended next steps")


# =============================================================================
# Schema Inference Models
# =============================================================================


class SchemaField(BaseModel):
    """Information about a detected schema field."""

    present: float = Field(description="Fraction of entries with this field (0.0-1.0)")
    values: list[str] | None = Field(None, description="Sample values (for enums)")
    patterns: list[str] | None = Field(None, description="Detected patterns")


class LogSchema(BaseModel):
    """Inferred schema of log files."""

    model_config = ConfigDict(populate_by_name=True)

    files_analyzed: int = Field(0, description="Number of files analyzed")
    files: list[str] = Field(default_factory=list, description="Analyzed file paths")
    total_entries: int = Field(0, description="Total entries analyzed")
    sample_size: int = Field(0, description="Sample size used")
    fields_schema: dict[str, SchemaField] = Field(
        default_factory=dict, description="Field information", alias="schema"
    )
    detected_formats: dict[str, float] = Field(
        default_factory=dict, description="Format distribution"
    )
    custom_fields: list[str] = Field(default_factory=list, description="Custom field names")
    time_range: dict[str, str] | None = Field(None, description="Time range of data")


# =============================================================================
# Helper Functions
# =============================================================================


def parse_log_entry(data: dict[str, Any]) -> LogEntry:
    """Parse a dictionary into a LogEntry model."""
    return LogEntry.model_validate(data)


def parse_search_results(data: dict[str, Any]) -> SearchResults:
    """Parse search results dictionary into SearchResults model."""
    return SearchResults.model_validate(data)


def parse_thread_hierarchy(data: dict[str, Any]) -> ThreadHierarchy:
    """Parse hierarchy dictionary into ThreadHierarchy model."""
    return ThreadHierarchy.model_validate(data)


def parse_error_analysis(data: dict[str, Any]) -> ErrorAnalysis:
    """Parse error analysis dictionary into ErrorAnalysis model."""
    return ErrorAnalysis.model_validate(data)
