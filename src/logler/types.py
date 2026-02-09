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

from typing import Any, Dict, List, Optional

from typing_extensions import NotRequired, TypedDict


# ---------------------------------------------------------------------------
# Search types
# ---------------------------------------------------------------------------


class LogEntryDict(TypedDict, total=False):
    """A single parsed log entry as returned by the Rust backend."""

    line_number: int
    timestamp: Optional[str]
    level: str
    message: str
    thread_id: Optional[str]
    correlation_id: Optional[str]
    trace_id: Optional[str]
    span_id: Optional[str]
    service_name: Optional[str]
    file: str
    fields: Dict[str, Any]
    duration_ms: NotRequired[Optional[float]]


class SearchResultItem(TypedDict):
    """One hit inside ``SearchResult.results``."""

    entry: LogEntryDict
    context_before: NotRequired[List[LogEntryDict]]
    context_after: NotRequired[List[LogEntryDict]]


class SearchResult(TypedDict, total=False):
    """Return type of :func:`search` with ``output_format="full"``."""

    total_matches: int
    results: List[SearchResultItem]
    query: Optional[str]
    files: List[str]
    filters: Dict[str, Any]
    metadata: Dict[str, Any]


class SearchSummaryResult(TypedDict, total=False):
    """Return type of :func:`search` with ``output_format="summary"``."""

    total_matches: int
    unique_messages: int
    log_levels: Dict[str, int]
    by_file: Dict[str, int]
    top_messages: List[Dict[str, Any]]
    sample_entries: List[LogEntryDict]
    full_results_available: bool


class SearchCountResult(TypedDict):
    """Return type of :func:`search` with ``output_format="count"``."""

    total_matches: int
    by_level: Dict[str, int]
    by_file: Dict[str, int]
    time_range: Optional[Dict[str, str]]


class SearchCompactResult(TypedDict):
    """Return type of :func:`search` with ``output_format="compact"``."""

    matches: List[Dict[str, Any]]
    total: int


class ExtractedIds(TypedDict, total=False):
    """Return type of :func:`extract_ids`."""

    thread_ids: List[str]
    correlation_ids: List[str]
    trace_ids: List[str]
    services: List[str]
    total_entries: int
    time_range: NotRequired[Dict[str, str]]


class FollowThreadResult(TypedDict, total=False):
    """Return type of :func:`follow_thread`."""

    entries: List[LogEntryDict]
    total_entries: int
    duration_ms: NotRequired[Optional[int]]
    unique_spans: NotRequired[List[str]]


class ContextResult(TypedDict):
    """Return type of :func:`get_context`."""

    target: LogEntryDict
    context_before: List[LogEntryDict]
    context_after: List[LogEntryDict]


# ---------------------------------------------------------------------------
# Hierarchy types
# ---------------------------------------------------------------------------


class HierarchyNode(TypedDict, total=False):
    """A single node in a thread/span hierarchy tree."""

    id: str
    node_type: str  # "Thread" | "Span" | "CorrelationGroup"
    name: str
    parent_id: Optional[str]
    children: List[HierarchyNode]
    entry_ids: List[int]
    start_time: Optional[str]
    end_time: Optional[str]
    duration_ms: Optional[int]
    entry_count: int
    error_count: int
    level_counts: Dict[str, int]
    depth: int
    confidence: float
    relationship_evidence: List[str]


class BottleneckInfo(TypedDict, total=False):
    """Bottleneck detected within a hierarchy."""

    node_id: str
    duration_ms: int
    percentage: float
    depth: int


class HierarchyResult(TypedDict, total=False):
    """Return type of :func:`follow_thread_hierarchy`."""

    roots: List[HierarchyNode]
    total_nodes: int
    max_depth: int
    total_duration_ms: Optional[int]
    concurrent_count: int
    bottleneck: Optional[BottleneckInfo]
    error_nodes: List[str]
    detection_method: str
    detection_methods: NotRequired[List[str]]
    # Added by build_hierarchy_with_correlation_chains
    correlation_chains: NotRequired[List[Dict[str, Any]]]
    chained_correlation_ids: NotRequired[List[str]]
    has_correlation_chains: NotRequired[bool]
    correlation_chain_count: NotRequired[int]
    related_correlation_ids: NotRequired[List[str]]


class RootCauseInfo(TypedDict, total=False):
    """A root cause identified by :func:`analyze_error_flow`."""

    node_id: str
    node_type: str
    error_count: int
    depth: int
    timestamp: Optional[str]
    path: List[str]
    is_leaf: bool
    confidence: float


class PropagationChainInfo(TypedDict):
    """An error propagation chain."""

    root_cause: str
    chain: List[Dict[str, Any]]
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
    root_causes: List[RootCauseInfo]
    propagation_chains: List[PropagationChainInfo]
    impact_summary: ImpactSummaryInfo
    recommendations: List[str]


class BottleneckAnalysis(TypedDict, total=False):
    """Return type of :func:`analyze_bottlenecks`."""

    primary_bottleneck: Optional[BottleneckInfo]
    secondary_bottlenecks: List[Dict[str, Any]]
    optimization_suggestions: List[str]
    parallelization_opportunities: List[Dict[str, Any]]
    caching_opportunities: List[str]
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
    improved_nodes: List[Dict[str, Any]]
    degraded_nodes: List[Dict[str, Any]]
    new_nodes: List[Dict[str, Any]]
    removed_nodes: List[Dict[str, Any]]
    error_changes: Dict[str, List[str]]


class CorrelationChainLink(TypedDict, total=False):
    """A single parent-child correlation chain link."""

    parent_correlation_id: str
    child_correlation_id: str
    evidence: str
    timestamp: Optional[str]
    confidence: float


class CorrelationChainResult(TypedDict):
    """Return type of :func:`detect_correlation_chains`."""

    chains: List[CorrelationChainLink]
    root_ids: List[str]
    hierarchy: Dict[str, List[str]]
    total_chains: int
    total_correlation_ids: int


# ---------------------------------------------------------------------------
# Comparison types
# ---------------------------------------------------------------------------


class ThreadAnalysis(TypedDict, total=False):
    """Analysis of a single thread for comparison."""

    id: str
    entries: List[LogEntryDict]
    entry_count: int
    duration_ms: int
    error_count: int
    log_levels: Dict[str, int]
    unique_messages: int
    messages: List[str]
    services: List[str]


class ThreadDifferences(TypedDict, total=False):
    """Differences between two threads."""

    duration_diff_ms: int
    error_diff: int
    only_in_a: List[str]
    only_in_b: List[str]
    level_changes: Dict[str, int]
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
    log_levels: Dict[str, int]
    top_errors: List[str]
    unique_threads: int


class PeriodChanges(TypedDict, total=False):
    """Changes between two time periods."""

    log_volume_change_pct: float
    error_rate_multiplier: float
    error_count_change: int
    new_errors: List[str]
    resolved_errors: List[str]
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
    timestamp: Optional[str]
    entry: LogEntryDict
    relative_time_ms: Optional[int]


class CrossServiceTimelineResult(TypedDict):
    """Return type of :func:`cross_service_timeline`."""

    timeline: List[TimelineEvent]
    services: List[str]
    total_entries: int
    duration_ms: Optional[int]
    service_breakdown: Dict[str, int]


# ---------------------------------------------------------------------------
# Pattern types
# ---------------------------------------------------------------------------


class PatternInfo(TypedDict, total=False):
    """A single repeated log pattern."""

    pattern: str
    occurrences: int
    first_seen: Optional[str]
    last_seen: Optional[str]
    affected_threads: List[str]
    examples: List[LogEntryDict]


class PatternResult(TypedDict, total=False):
    """Return type of :func:`find_patterns`."""

    patterns: List[PatternInfo]
    total_entries: NotRequired[int]
    total_patterns: NotRequired[int]
    files: NotRequired[List[str]]


# ---------------------------------------------------------------------------
# Metadata types
# ---------------------------------------------------------------------------


class FileMetadataInfo(TypedDict, total=False):
    """Metadata for a single log file."""

    path: str
    size_bytes: int
    lines: int
    format: str
    time_range: Optional[Dict[str, str]]
    available_fields: List[str]
    unique_threads: int
    unique_correlation_ids: int
    log_levels: Dict[str, int]


# ---------------------------------------------------------------------------
# Sampling types
# ---------------------------------------------------------------------------


class CoverageInfo(TypedDict, total=False):
    """Coverage statistics for a sample."""

    time_coverage: float
    level_coverage: Dict[str, int]
    unique_threads_in_sample: int
    unique_threads_in_population: int
    thread_coverage_pct: float


class SampleResult(TypedDict):
    """Return type of :func:`smart_sample`."""

    samples: List[LogEntryDict]
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
    references: List[Dict[str, str]]
    startTime: int
    duration: int
    tags: List[Dict[str, Any]]
    logs: List[Any]
    processID: str
    warnings: List[str]


class JaegerTrace(TypedDict):
    """A single trace within a Jaeger export."""

    traceID: str
    spans: List[JaegerSpan]
    processes: Dict[str, Any]
    warnings: List[str]


class JaegerExport(TypedDict):
    """Return type of :func:`export_to_jaeger`."""

    data: List[JaegerTrace]


class ZipkinSpan(TypedDict, total=False):
    """A single span in Zipkin V2 format."""

    traceId: str
    id: str
    name: str
    timestamp: int
    duration: int
    localEndpoint: Dict[str, str]
    tags: Dict[str, str]
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
    anomalies: List[Dict[str, Any]]
    values: List[float]
    timestamps: List[Optional[str]]
    buckets: NotRequired[List[Dict[str, Any]]]


class MetricsExtractionResult(TypedDict, total=False):
    """Return type of :func:`extract_metrics`."""

    fields: Dict[str, MetricsFieldStats]
    entries_scanned: int
    files_searched: int


class FormatDetectionInfo(TypedDict, total=False):
    """Detection result for a single file."""

    format: str
    confidence: float
    sample_size: int
    match_rate: float
    alternatives: List[Dict[str, Any]]
    detected_fields: List[str]
    sample_lines: List[str]
    mixed: bool


class FormatDetectionResult(TypedDict):
    """Return type of :func:`detect_formats`."""

    files: Dict[str, FormatDetectionInfo]


class TemplateMiningResult(TypedDict):
    """Return type of :func:`mine_log_templates`."""

    templates: List[Dict[str, Any]]
    total_lines: int
    unique_templates: int
    coverage: float
    files_searched: int
