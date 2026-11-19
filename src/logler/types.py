"""
TypedDict definitions for all investigate module return shapes.

These provide static type information for functions that return raw dicts
(typically from Rust FFI or JSON deserialization). Use these for type hints
on function signatures and for IDE autocompletion.

Note: These complement the Pydantic models in ``models.py``.  Pydantic models
are validated *runtime* representations; TypedDicts describe the *wire format*
returned by functions before any validation.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

# ---------------------------------------------------------------------------
# Search types
# ---------------------------------------------------------------------------


class LogEntryDict(TypedDict, total=False):
    """A single parsed log entry as returned by the Rust backend."""

    line_number: int
    timestamp: str | None
    level: str
    message: str
    thread_id: str | None
    correlation_id: str | None
    trace_id: str | None
    span_id: str | None
    service_name: str | None
    file: str
    fields: dict[str, Any]
    duration_ms: NotRequired[float | None]


class SearchResultItem(TypedDict):
    """One hit inside ``SearchResult.results``."""

    entry: LogEntryDict
    context_before: NotRequired[list[LogEntryDict]]
    context_after: NotRequired[list[LogEntryDict]]


class SearchResult(TypedDict, total=False):
    """Return type of :func:`search` with ``output_format="full"``."""

    total_matches: int
    results: list[SearchResultItem]
    query: str | None
    files: list[str]
    filters: dict[str, Any]
    metadata: dict[str, Any]


class SearchSummaryResult(TypedDict, total=False):
    """Return type of :func:`search` with ``output_format="summary"``."""

    total_matches: int
    unique_messages: int
    log_levels: dict[str, int]
    by_file: dict[str, int]
    top_messages: list[dict[str, Any]]
    sample_entries: list[LogEntryDict]
    full_results_available: bool


class SearchCountResult(TypedDict):
    """Return type of :func:`search` with ``output_format="count"``."""

    total_matches: int
    by_level: dict[str, int]
    by_file: dict[str, int]
    time_range: dict[str, str] | None


class SearchCompactResult(TypedDict):
    """Return type of :func:`search` with ``output_format="compact"``."""

    matches: list[dict[str, Any]]
    total: int


class ExtractedIds(TypedDict, total=False):
    """Return type of :func:`extract_ids`."""

    thread_ids: list[str]
    correlation_ids: list[str]
    trace_ids: list[str]
    services: list[str]
    total_entries: int
    time_range: NotRequired[dict[str, str]]


class FollowThreadResult(TypedDict, total=False):
    """Return type of :func:`follow_thread`."""

    entries: list[LogEntryDict]
    total_entries: int
    duration_ms: NotRequired[int | None]
    unique_spans: NotRequired[list[str]]


class ContextResult(TypedDict):
    """Return type of :func:`get_context`."""

    target: LogEntryDict
    context_before: list[LogEntryDict]
    context_after: list[LogEntryDict]


# ---------------------------------------------------------------------------
# Hierarchy types
# ---------------------------------------------------------------------------


class HierarchyNode(TypedDict, total=False):
    """A single node in a thread/span hierarchy tree."""

    id: str
    node_type: str  # "Thread" | "Span" | "CorrelationGroup"
    name: str
    parent_id: str | None
    children: list[HierarchyNode]
    entry_ids: list[str]
    start_time: str | None
    end_time: str | None
    duration_ms: int | None
    entry_count: int
    error_count: int
    level_counts: dict[str, int]
    depth: int
    confidence: float
    relationship_evidence: list[str]


class BottleneckInfo(TypedDict, total=False):
    """Bottleneck detected within a hierarchy."""

    node_id: str
    duration_ms: int
    percentage: float
    depth: int


class HierarchyResult(TypedDict, total=False):
    """Return type of :func:`follow_thread_hierarchy`."""

    roots: list[HierarchyNode]
    total_nodes: int
    max_depth: int
    total_duration_ms: int | None
    concurrent_count: int
    bottleneck: BottleneckInfo | None
    error_nodes: list[str]
    detection_method: str
    detection_methods: NotRequired[list[str]]
    # Added by build_hierarchy_with_correlation_chains
    correlation_chains: NotRequired[list[dict[str, Any]]]
    chained_correlation_ids: NotRequired[list[str]]
    has_correlation_chains: NotRequired[bool]
    correlation_chain_count: NotRequired[int]
    related_correlation_ids: NotRequired[list[str]]


class RootCauseInfo(TypedDict, total=False):
    """A root cause identified by :func:`analyze_error_flow`."""

    node_id: str
    node_type: str
    error_count: int
    depth: int
    timestamp: str | None
    path: list[str]
    is_leaf: bool
    confidence: float


class PropagationChainInfo(TypedDict):
    """An error propagation chain."""

    root_cause: str
    chain: list[dict[str, Any]]
    total_affected: int
    propagation_type: str


class ImpactSummaryInfo(TypedDict):
    """Impact assessment from error flow analysis."""

    total_affected_nodes: int
    affected_percentage: float
    max_propagation_depth: int
    concurrent_failures: int


class ErrorFlowResult(TypedDict):
    """Return type of :func:`analyze_error_flow`."""

    has_errors: bool
    total_error_nodes: int
    root_causes: list[RootCauseInfo]
    propagation_chains: list[PropagationChainInfo]
    impact_summary: ImpactSummaryInfo
    recommendations: list[str]


class BottleneckAnalysis(TypedDict, total=False):
    """Return type of :func:`analyze_bottlenecks`."""

    primary_bottleneck: BottleneckInfo | None
    secondary_bottlenecks: list[dict[str, Any]]
    optimization_suggestions: list[str]
    parallelization_opportunities: list[dict[str, Any]]
    caching_opportunities: list[str]
    estimated_improvement_ms: float


class HierarchyDiffSummary(TypedDict):
    """Summary section of :class:`HierarchyDiffResult`."""

    total_duration_change_ms: float
    total_duration_change_pct: float
    node_count_change: int
    new_errors: int
    resolved_errors: int


class HierarchyDiffResult(TypedDict):
    """Return type of :func:`diff_hierarchies`."""

    label_a: str
    label_b: str
    summary: HierarchyDiffSummary
    improved_nodes: list[dict[str, Any]]
    degraded_nodes: list[dict[str, Any]]
    new_nodes: list[dict[str, Any]]
    removed_nodes: list[dict[str, Any]]
    error_changes: dict[str, list[str]]


class CorrelationChainLink(TypedDict, total=False):
    """A single parent-child correlation chain link."""

    parent_correlation_id: str
    child_correlation_id: str
    evidence: str
    timestamp: str | None
    confidence: float


class CorrelationChainResult(TypedDict):
    """Return type of :func:`detect_correlation_chains`."""

    chains: list[CorrelationChainLink]
    root_ids: list[str]
    hierarchy: dict[str, list[str]]
    total_chains: int
    total_correlation_ids: int


# ---------------------------------------------------------------------------
# Comparison types
# ---------------------------------------------------------------------------


class ThreadAnalysis(TypedDict, total=False):
    """Analysis of a single thread for comparison."""

    id: str
    entries: list[LogEntryDict]
    entry_count: int
    duration_ms: int
    error_count: int
    log_levels: dict[str, int]
    unique_messages: int
    messages: list[str]
    services: list[str]


class ThreadDifferences(TypedDict, total=False):
    """Differences between two threads."""

    duration_diff_ms: int
    error_diff: int
    only_in_a: list[str]
    only_in_b: list[str]
    level_changes: dict[str, int]
    entry_count_diff: int


class ThreadComparison(TypedDict):
    """Return type of :func:`compare_threads`."""

    thread_a: ThreadAnalysis
    thread_b: ThreadAnalysis
    differences: ThreadDifferences
    summary: str


class PeriodAnalysis(TypedDict, total=False):
    """Analysis of a single time period for comparison."""

    start: str
    end: str
    total_logs: int
    error_count: int
    error_rate: float
    log_levels: dict[str, int]
    top_errors: list[str]
    unique_threads: int


class PeriodChanges(TypedDict, total=False):
    """Changes between two time periods."""

    log_volume_change_pct: float
    error_rate_multiplier: float
    error_count_change: int
    new_errors: list[str]
    resolved_errors: list[str]
    thread_count_change: int


class PeriodComparison(TypedDict):
    """Return type of :func:`compare_time_periods`."""

    period_a: PeriodAnalysis
    period_b: PeriodAnalysis
    changes: PeriodChanges
    summary: str


# ---------------------------------------------------------------------------
# Timeline types
# ---------------------------------------------------------------------------


class TimelineEvent(TypedDict, total=False):
    """A single event in a cross-service timeline."""

    service: str
    timestamp: str | None
    entry: LogEntryDict
    relative_time_ms: int | None


class CrossServiceTimelineResult(TypedDict):
    """Return type of :func:`cross_service_timeline`."""

    timeline: list[TimelineEvent]
    services: list[str]
    total_entries: int
    duration_ms: int | None
    service_breakdown: dict[str, int]


# ---------------------------------------------------------------------------
# Pattern types
# ---------------------------------------------------------------------------


class PatternInfo(TypedDict, total=False):
    """A single repeated log pattern."""

    pattern: str
    occurrences: int
    first_seen: str | None
    last_seen: str | None
    affected_threads: list[str]
    examples: list[LogEntryDict]


class PatternResult(TypedDict, total=False):
    """Return type of :func:`find_patterns`."""

    patterns: list[PatternInfo]
    total_entries: NotRequired[int]
    total_patterns: NotRequired[int]
    files: NotRequired[list[str]]


# ---------------------------------------------------------------------------
# Metadata types
# ---------------------------------------------------------------------------


class FileMetadataInfo(TypedDict, total=False):
    """Metadata for a single log file."""

    path: str
    size_bytes: int
    lines: int
    format: str
    time_range: dict[str, str] | None
    available_fields: list[str]
    unique_threads: int
    unique_correlation_ids: int
    log_levels: dict[str, int]


# ---------------------------------------------------------------------------
# Sampling types
# ---------------------------------------------------------------------------


class CoverageInfo(TypedDict, total=False):
    """Coverage statistics for a sample."""

    time_coverage: float
    level_coverage: dict[str, int]
    unique_threads_in_sample: int
    unique_threads_in_population: int
    thread_coverage_pct: float


class SampleResult(TypedDict):
    """Return type of :func:`smart_sample`."""

    samples: list[LogEntryDict]
    total_population: int
    sample_size: int
    strategy: str
    coverage: CoverageInfo


# ---------------------------------------------------------------------------
# Export types
# ---------------------------------------------------------------------------


class JaegerSpan(TypedDict, total=False):
    """A single span in Jaeger format."""

    traceID: str
    spanID: str
    operationName: str
    references: list[dict[str, str]]
    startTime: int
    duration: int
    tags: list[dict[str, Any]]
    logs: list[Any]
    processID: str
    warnings: list[str]


class JaegerTrace(TypedDict):
    """A single trace within a Jaeger export."""

    traceID: str
    spans: list[JaegerSpan]
    processes: dict[str, Any]
    warnings: list[str]


class JaegerExport(TypedDict):
    """Return type of :func:`export_to_jaeger`."""

    data: list[JaegerTrace]


class ZipkinSpan(TypedDict, total=False):
    """A single span in Zipkin V2 format."""

    traceId: str
    id: str
    name: str
    timestamp: int
    duration: int
    localEndpoint: dict[str, str]
    tags: dict[str, str]
    parentId: NotRequired[str]


# ---------------------------------------------------------------------------
# Metrics / Detection types (thin wrappers)
# ---------------------------------------------------------------------------


class MetricsFieldStats(TypedDict, total=False):
    """Statistics for a single extracted metric field."""

    count: int
    min: float
    max: float
    mean: float
    median: float
    stddev: float
    p95: float
    p99: float
    anomalies: list[dict[str, Any]]
    values: list[float]
    timestamps: list[str | None]
    buckets: NotRequired[list[dict[str, Any]]]


class MetricsExtractionResult(TypedDict, total=False):
    """Return type of :func:`extract_metrics`."""

    fields: dict[str, MetricsFieldStats]
    entries_scanned: int
    files_searched: int


class FormatDetectionInfo(TypedDict, total=False):
    """Detection result for a single file."""

    format: str
    confidence: float
    sample_size: int
    match_rate: float
    alternatives: list[dict[str, Any]]
    detected_fields: list[str]
    sample_lines: list[str]
    mixed: bool


class FormatDetectionResult(TypedDict):
    """Return type of :func:`detect_formats`."""

    files: dict[str, FormatDetectionInfo]


class TemplateMiningResult(TypedDict):
    """Return type of :func:`mine_log_templates`."""

    templates: list[dict[str, Any]]
    total_lines: int
    unique_templates: int
    coverage: float
    files_searched: int
