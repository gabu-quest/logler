"""
Logler - Beautiful local log viewer with thread tracking and real-time updates.
"""

__version__ = "1.1.2"
__author__ = "Logler Contributors"

from .parser import LogParser, LogEntry
from .tracker import ThreadTracker
from .log_reader import LogReader
from .tree_formatter import format_tree, format_waterfall, print_tree, print_waterfall

# Pydantic models for type-safe log analysis
from .models import (
    # Core entry models
    LogEntry as TypedLogEntry,
    LogLevel,
    LogFormat,
    # Search models
    SearchResult,
    SearchResults,
    SearchSummary,
    SearchCount,
    # Timeline models
    ThreadTimeline,
    # Hierarchy models
    SpanNode,
    ThreadHierarchy,
    BottleneckInfo,
    NodeType,
    DetectionMethod,
    # Pattern models
    PatternMatch,
    PatternResults,
    # Sampling
    SamplingResult,
    # Error analysis
    ErrorAnalysis,
    RootCause,
    PropagationChain,
    ImpactSummary,
    # File/context
    FileMetadata,
    ContextResult,
    # Cross-service
    TimelineEntry,
    CrossServiceTimeline,
    # Correlation
    CorrelationLink,
    CorrelationChains,
    # Export
    TraceSpan,
    TraceExport,
    # Insights
    Insight,
    InsightsResult,
    # Schema
    SchemaField,
    LogSchema,
    # Helper functions
    parse_log_entry,
    parse_search_results,
    parse_thread_hierarchy,
    parse_error_analysis,
)

__all__ = [
    # Original exports
    "LogParser",
    "LogEntry",
    "ThreadTracker",
    "LogReader",
    "format_tree",
    "format_waterfall",
    "print_tree",
    "print_waterfall",
    # Pydantic models - Core
    "TypedLogEntry",
    "LogLevel",
    "LogFormat",
    # Pydantic models - Search
    "SearchResult",
    "SearchResults",
    "SearchSummary",
    "SearchCount",
    # Pydantic models - Timeline
    "ThreadTimeline",
    # Pydantic models - Hierarchy
    "SpanNode",
    "ThreadHierarchy",
    "BottleneckInfo",
    "NodeType",
    "DetectionMethod",
    # Pydantic models - Patterns
    "PatternMatch",
    "PatternResults",
    # Pydantic models - Sampling
    "SamplingResult",
    # Pydantic models - Error analysis
    "ErrorAnalysis",
    "RootCause",
    "PropagationChain",
    "ImpactSummary",
    # Pydantic models - File/context
    "FileMetadata",
    "ContextResult",
    # Pydantic models - Cross-service
    "TimelineEntry",
    "CrossServiceTimeline",
    # Pydantic models - Correlation
    "CorrelationLink",
    "CorrelationChains",
    # Pydantic models - Export
    "TraceSpan",
    "TraceExport",
    # Pydantic models - Insights
    "Insight",
    "InsightsResult",
    # Pydantic models - Schema
    "SchemaField",
    "LogSchema",
    # Helper functions
    "parse_log_entry",
    "parse_search_results",
    "parse_thread_hierarchy",
    "parse_error_analysis",
]
