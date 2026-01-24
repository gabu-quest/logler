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
    results: SearchResults = investigate.search(files=["app.log"], validated=True)
    for result in results.results:
        entry: LogEntry = result.entry
        print(f"{entry.timestamp} [{entry.level}] {entry.message}")
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class LogLevel(str, Enum):
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


class LogFormat(str, Enum):
    """Detected log format."""

    JSON = "Json"
    LOGFMT = "Logfmt"
    SYSLOG = "Syslog"
    PLAIN_TEXT = "PlainText"
    CUSTOM = "Custom"
    UNKNOWN = "Unknown"


class NodeType(str, Enum):
    """Type of hierarchy node."""

    THREAD = "Thread"
    SPAN = "Span"
    CORRELATION_GROUP = "CorrelationGroup"
    UNKNOWN = "Unknown"


class DetectionMethod(str, Enum):
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

    line_number: int = Field(description="Line number in source file")
    timestamp: Optional[str] = Field(None, description="ISO8601 timestamp")
    level: Optional[str] = Field(None, description="Log level (ERROR, WARN, INFO, etc.)")
    message: Optional[str] = Field(None, description="Log message content")
    raw: Optional[str] = Field(None, description="Raw original log line")
    file: Optional[str] = Field(None, description="Source file path")
    format: Optional[str] = Field(None, description="Detected log format")

    # Correlation/tracing fields
    thread_id: Optional[str] = Field(None, description="Thread identifier")
    correlation_id: Optional[str] = Field(None, description="Correlation/request ID")
    trace_id: Optional[str] = Field(None, description="Distributed trace ID")
    span_id: Optional[str] = Field(None, description="Span ID within trace")
    parent_span_id: Optional[str] = Field(None, description="Parent span ID")

    # OpenTelemetry fields
    service_name: Optional[str] = Field(None, description="Service name")
    operation_name: Optional[str] = Field(None, description="Operation/span name")
    duration_ms: Optional[float] = Field(None, description="Duration in milliseconds")

    # Additional structured fields
    fields: Dict[str, Any] = Field(default_factory=dict, description="Additional parsed fields")
    extra: Dict[str, Any] = Field(default_factory=dict, description="Extra/custom fields")

    model_config = ConfigDict(extra="allow")


# =============================================================================
# Search Models
# =============================================================================


class SearchResult(BaseModel):
    """A single search result with context."""

    entry: LogEntry = Field(description="The matching log entry")
    context_before: List[LogEntry] = Field(
        default_factory=list, description="Log entries before the match"
    )
    context_after: List[LogEntry] = Field(
        default_factory=list, description="Log entries after the match"
    )
    relevance_score: Optional[float] = Field(None, description="Search relevance score")


class SearchResults(BaseModel):
    """Results from a log search operation."""

    results: List[SearchResult] = Field(default_factory=list, description="Search results")
    total_matches: int = Field(0, description="Total number of matches")
    search_time_ms: Optional[int] = Field(None, description="Search duration in ms")

    # Aggregations
    by_level: Dict[str, int] = Field(default_factory=dict, description="Counts by log level")
    by_file: Dict[str, int] = Field(default_factory=dict, description="Counts by file")
    by_thread: Dict[str, int] = Field(default_factory=dict, description="Counts by thread")


class SearchSummary(BaseModel):
    """Summarized search results (output_format='summary')."""

    total_matches: int = Field(0, description="Total number of matches")
    unique_messages: int = Field(0, description="Number of unique message patterns")
    log_levels: Dict[str, int] = Field(default_factory=dict, description="Counts by level")
    top_messages: List[Dict[str, Any]] = Field(
        default_factory=list, description="Most common messages with counts"
    )
    sample_entries: List[LogEntry] = Field(
        default_factory=list, description="Sample matching entries"
    )


class SearchCount(BaseModel):
    """Count-only search results (output_format='count')."""

    total_matches: int = Field(0, description="Total number of matches")
    by_level: Dict[str, int] = Field(default_factory=dict, description="Counts by level")
    by_file: Dict[str, int] = Field(default_factory=dict, description="Counts by file")
    time_range: Optional[Dict[str, str]] = Field(None, description="Start/end timestamps")


# =============================================================================
# Thread/Timeline Models
# =============================================================================


class ThreadTimeline(BaseModel):
    """Timeline of entries for a thread/correlation/trace."""

    entries: List[LogEntry] = Field(default_factory=list, description="Chronological entries")
    total_entries: int = Field(0, description="Total number of entries")
    duration_ms: Optional[int] = Field(None, description="Total duration in ms")
    unique_spans: List[str] = Field(default_factory=list, description="Unique span IDs found")
    services: List[str] = Field(default_factory=list, description="Services involved")


# =============================================================================
# Hierarchy Models
# =============================================================================


class BottleneckInfo(BaseModel):
    """Information about a performance bottleneck."""

    node_id: str = Field(description="ID of the bottleneck node")
    duration_ms: int = Field(0, description="Duration in milliseconds")
    percentage: float = Field(0.0, description="Percentage of total time")
    depth: int = Field(0, description="Depth in hierarchy")


class SpanNode(BaseModel):
    """A node in the thread/span hierarchy tree."""

    id: str = Field(description="Node identifier (thread_id, span_id, or correlation_id)")
    node_type: str = Field("Unknown", description="Node type: Thread, Span, CorrelationGroup")
    name: Optional[str] = Field(None, description="Human-readable operation name")
    parent_id: Optional[str] = Field(None, description="Parent node ID")
    children: List[SpanNode] = Field(default_factory=list, description="Child nodes")

    # Entry references
    entry_ids: List[int] = Field(default_factory=list, description="Line numbers of entries")
    entry_count: int = Field(0, description="Number of log entries in this node")

    # Timing
    start_time: Optional[str] = Field(None, description="Start timestamp (ISO8601)")
    end_time: Optional[str] = Field(None, description="End timestamp (ISO8601)")
    duration_ms: Optional[int] = Field(None, description="Duration in milliseconds")

    # Statistics
    error_count: int = Field(0, description="Number of error entries")
    level_counts: Dict[str, int] = Field(default_factory=dict, description="Entries by level")

    # Hierarchy metadata
    depth: int = Field(0, description="Depth in tree (0 = root)")
    confidence: float = Field(1.0, description="Confidence score for relationship (0.0-1.0)")
    relationship_evidence: List[str] = Field(
        default_factory=list, description="Evidence for parent-child relationship"
    )

    model_config = ConfigDict(extra="allow")


# Allow recursive definition
SpanNode.model_rebuild()


class ThreadHierarchy(BaseModel):
    """Complete thread/span hierarchy tree."""

    roots: List[SpanNode] = Field(default_factory=list, description="Root nodes")
    total_nodes: int = Field(0, description="Total number of nodes")
    max_depth: int = Field(0, description="Maximum depth of tree")
    total_duration_ms: Optional[int] = Field(None, description="Total duration")
    concurrent_count: int = Field(0, description="Number of concurrent operations")
    bottleneck: Optional[BottleneckInfo] = Field(None, description="Performance bottleneck")
    error_nodes: List[str] = Field(default_factory=list, description="Node IDs with errors")
    detection_method: str = Field("Unknown", description="How relationships were detected")
    detection_methods: List[str] = Field(
        default_factory=list, description="Detection methods used (detailed)"
    )


# =============================================================================
# Pattern Detection Models
# =============================================================================


class PatternMatch(BaseModel):
    """A detected log pattern."""

    pattern: str = Field(description="Regex pattern or template")
    template: Optional[str] = Field(None, description="Human-readable template")
    count: int = Field(0, description="Number of occurrences")
    first_seen: Optional[str] = Field(None, description="First occurrence timestamp")
    last_seen: Optional[str] = Field(None, description="Last occurrence timestamp")
    examples: List[LogEntry] = Field(default_factory=list, description="Example entries")
    by_level: Dict[str, int] = Field(default_factory=dict, description="Counts by level")
    by_thread: Dict[str, int] = Field(default_factory=dict, description="Counts by thread")


class PatternResults(BaseModel):
    """Results from pattern detection."""

    patterns: List[PatternMatch] = Field(default_factory=list, description="Detected patterns")
    total_entries: int = Field(0, description="Total entries analyzed")
    unique_patterns: int = Field(0, description="Number of unique patterns")
    coverage: float = Field(0.0, description="Percentage of entries matching patterns")


# =============================================================================
# Sampling Models
# =============================================================================


class SamplingResult(BaseModel):
    """Results from log sampling."""

    entries: List[LogEntry] = Field(default_factory=list, description="Sampled entries")
    total_population: int = Field(0, description="Total entries in source")
    sample_size: int = Field(0, description="Number of sampled entries")
    strategy: str = Field("random", description="Sampling strategy used")
    level_distribution: Dict[str, int] = Field(
        default_factory=dict, description="Level distribution in sample"
    )
    unique_threads: int = Field(0, description="Number of unique threads in sample")
    time_range: Optional[Dict[str, str]] = Field(None, description="Time range covered")


# =============================================================================
# Error Analysis Models
# =============================================================================


class RootCause(BaseModel):
    """A potential root cause of errors."""

    node_id: str = Field(description="Node ID of root cause")
    node_type: str = Field("Unknown", description="Type of node")
    error_count: int = Field(0, description="Number of errors")
    depth: int = Field(0, description="Depth in hierarchy")
    timestamp: Optional[str] = Field(None, description="First error timestamp")
    path: List[str] = Field(default_factory=list, description="Path from root to this node")
    is_leaf: bool = Field(False, description="Whether this is a leaf node")
    confidence: float = Field(0.0, description="Confidence this is root cause")


class PropagationChain(BaseModel):
    """Error propagation chain through hierarchy."""

    root_cause: str = Field(description="Root cause node ID")
    chain: List[Dict[str, Any]] = Field(default_factory=list, description="Chain of affected nodes")
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
    root_causes: List[RootCause] = Field(default_factory=list, description="Identified root causes")
    propagation_chains: List[PropagationChain] = Field(
        default_factory=list, description="Error propagation chains"
    )
    impact_summary: ImpactSummary = Field(
        default_factory=ImpactSummary, description="Impact summary"
    )
    recommendations: List[str] = Field(default_factory=list, description="Suggested actions")


# =============================================================================
# File/Context Models
# =============================================================================


class FileMetadata(BaseModel):
    """Metadata about a log file."""

    path: str = Field(description="File path")
    size_bytes: int = Field(0, description="File size in bytes")
    line_count: int = Field(0, description="Total line count")
    entry_count: int = Field(0, description="Parsed entry count")
    format: str = Field("Unknown", description="Detected log format")
    time_range: Optional[Dict[str, str]] = Field(None, description="Time range of entries")
    level_distribution: Dict[str, int] = Field(
        default_factory=dict, description="Distribution by level"
    )


class ContextResult(BaseModel):
    """Context around a specific log line."""

    target: LogEntry = Field(description="The target log entry")
    context_before: List[LogEntry] = Field(
        default_factory=list, description="Entries before target"
    )
    context_after: List[LogEntry] = Field(default_factory=list, description="Entries after target")


# =============================================================================
# Cross-Service Timeline Models
# =============================================================================


class TimelineEntry(BaseModel):
    """An entry in a cross-service timeline."""

    service: str = Field(description="Service name")
    timestamp: Optional[str] = Field(None, description="Entry timestamp")
    entry: LogEntry = Field(description="The log entry")
    relative_time_ms: int = Field(0, description="Time offset from start in ms")


class CrossServiceTimeline(BaseModel):
    """Timeline spanning multiple services."""

    timeline: List[TimelineEntry] = Field(default_factory=list, description="Chronological entries")
    services: List[str] = Field(default_factory=list, description="Services involved")
    total_entries: int = Field(0, description="Total number of entries")
    duration_ms: Optional[int] = Field(None, description="Total duration")
    service_breakdown: Dict[str, int] = Field(
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
    timestamp: Optional[str] = Field(None, description="When link was detected")
    confidence: float = Field(0.0, description="Confidence score")


class CorrelationChains(BaseModel):
    """Detected correlation ID chains."""

    chains: List[CorrelationLink] = Field(default_factory=list, description="Correlation links")
    root_ids: List[str] = Field(default_factory=list, description="Root correlation IDs")
    hierarchy: Dict[str, List[str]] = Field(
        default_factory=dict, description="Parent to children mapping"
    )
    total_unique_ids: int = Field(0, description="Total unique correlation IDs")


# =============================================================================
# Export Models
# =============================================================================


class TraceSpan(BaseModel):
    """A span for trace export (Jaeger/Zipkin compatible)."""

    trace_id: str = Field(description="Trace ID")
    span_id: str = Field(description="Span ID")
    operation_name: str = Field(description="Operation name")
    parent_span_id: Optional[str] = Field(None, description="Parent span ID")
    service_name: str = Field(description="Service name")
    start_time: str = Field(description="Start timestamp (ISO8601)")
    duration_us: int = Field(0, description="Duration in microseconds")
    tags: Dict[str, str] = Field(default_factory=dict, description="Span tags")
    logs: List[Dict[str, Any]] = Field(default_factory=list, description="Span logs/events")


class TraceExport(BaseModel):
    """Exported trace data."""

    format: str = Field(description="Export format (jaeger, zipkin)")
    traces: List[Dict[str, Any]] = Field(default_factory=list, description="Trace data")
    span_count: int = Field(0, description="Total number of spans")


# =============================================================================
# AI Insights Models
# =============================================================================


class Insight(BaseModel):
    """An AI-generated insight about logs."""

    type: str = Field(description="Insight type")
    severity: str = Field("info", description="Severity: info, warning, critical")
    description: str = Field(description="Human-readable description")
    count: Optional[int] = Field(None, description="Related count if applicable")
    suggestion: Optional[str] = Field(None, description="Suggested action")
    evidence: List[str] = Field(default_factory=list, description="Supporting evidence")


class InsightsResult(BaseModel):
    """Results from AI insights analysis."""

    overview: Dict[str, Any] = Field(default_factory=dict, description="Overview statistics")
    insights: List[Insight] = Field(default_factory=list, description="Generated insights")
    next_steps: List[str] = Field(default_factory=list, description="Recommended next steps")


# =============================================================================
# Schema Inference Models
# =============================================================================


class SchemaField(BaseModel):
    """Information about a detected schema field."""

    present: float = Field(description="Fraction of entries with this field (0.0-1.0)")
    values: Optional[List[str]] = Field(None, description="Sample values (for enums)")
    patterns: Optional[List[str]] = Field(None, description="Detected patterns")


class LogSchema(BaseModel):
    """Inferred schema of log files."""

    model_config = ConfigDict(populate_by_name=True)

    files_analyzed: int = Field(0, description="Number of files analyzed")
    files: List[str] = Field(default_factory=list, description="Analyzed file paths")
    total_entries: int = Field(0, description="Total entries analyzed")
    sample_size: int = Field(0, description="Sample size used")
    fields_schema: Dict[str, SchemaField] = Field(
        default_factory=dict, description="Field information", alias="schema"
    )
    detected_formats: Dict[str, float] = Field(
        default_factory=dict, description="Format distribution"
    )
    custom_fields: List[str] = Field(default_factory=list, description="Custom field names")
    time_range: Optional[Dict[str, str]] = Field(None, description="Time range of data")


# =============================================================================
# Helper Functions
# =============================================================================


def parse_log_entry(data: Dict[str, Any]) -> LogEntry:
    """Parse a dictionary into a LogEntry model."""
    return LogEntry.model_validate(data)


def parse_search_results(data: Dict[str, Any]) -> SearchResults:
    """Parse search results dictionary into SearchResults model."""
    return SearchResults.model_validate(data)


def parse_thread_hierarchy(data: Dict[str, Any]) -> ThreadHierarchy:
    """Parse hierarchy dictionary into ThreadHierarchy model."""
    return ThreadHierarchy.model_validate(data)


def parse_error_analysis(data: Dict[str, Any]) -> ErrorAnalysis:
    """Parse error analysis dictionary into ErrorAnalysis model."""
    return ErrorAnalysis.model_validate(data)
