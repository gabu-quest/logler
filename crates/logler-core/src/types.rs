use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use uuid::Uuid;

/// Log entry representing a single log line
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogEntry {
    pub id: Uuid,
    pub file: String,
    pub line_number: usize,
    pub raw: String,
    pub timestamp: Option<DateTime<Utc>>,
    pub level: Option<LogLevel>,
    pub format: LogFormat,
    pub message: String,
    pub thread_id: Option<String>,
    pub correlation_id: Option<String>,
    pub trace_id: Option<String>,
    pub span_id: Option<String>,
    pub parent_span_id: Option<String>,
    pub service_name: Option<String>,
    pub fields: HashMap<String, serde_json::Value>,
}

/// Log level
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum LogLevel {
    Trace,
    Debug,
    Info,
    Warn,
    Error,
    Fatal,
    Unknown,
}

impl LogLevel {
    pub fn parse(s: &str) -> Option<Self> {
        match s.to_uppercase().as_str() {
            "TRACE" => Some(Self::Trace),
            "DEBUG" => Some(Self::Debug),
            "INFO" => Some(Self::Info),
            "WARN" | "WARNING" => Some(Self::Warn),
            "ERROR" => Some(Self::Error),
            "FATAL" | "CRITICAL" => Some(Self::Fatal),
            _ => Some(Self::Unknown),
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Trace => "TRACE",
            Self::Debug => "DEBUG",
            Self::Info => "INFO",
            Self::Warn => "WARN",
            Self::Error => "ERROR",
            Self::Fatal => "FATAL",
            Self::Unknown => "UNKNOWN",
        }
    }
}

/// Search query for filtering log entries
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchQuery {
    pub files: Vec<PathBuf>,
    pub query: Option<String>,
    pub filters: SearchFilters,
    pub limit: Option<usize>,
    pub context_lines: Option<usize>,
}

/// Filters for searching logs
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SearchFilters {
    pub levels: Vec<LogLevel>,
    pub time_range: Option<TimeRange>,
    pub thread_id: Option<String>,
    pub correlation_id: Option<String>,
    pub trace_id: Option<String>,
    pub has_correlation_id: Option<bool>,
}

/// Time range for filtering
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimeRange {
    pub start: Option<DateTime<Utc>>,
    pub end: Option<DateTime<Utc>>,
}

/// Search result with context
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResult {
    pub entry: LogEntry,
    pub context_before: Vec<LogEntry>,
    pub context_after: Vec<LogEntry>,
    pub relevance_score: f64,
}

/// Result of a search operation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResults {
    pub results: Vec<SearchResult>,
    pub total_matches: usize,
    pub search_time_ms: u64,
}

/// Thread timeline containing all entries for a thread
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThreadTimeline {
    pub entries: Vec<LogEntry>,
    pub total_entries: usize,
    pub duration_ms: Option<i64>,
    pub unique_spans: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThreadContext {
    pub thread_id: String,
    pub first_seen: DateTime<Utc>,
    pub last_seen: DateTime<Utc>,
    pub log_count: usize,
    pub error_count: usize,
    pub correlation_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraceContext {
    pub trace_id: String,
    pub spans: Vec<SpanInfo>,
    pub services: Vec<String>,
    pub start_time: DateTime<Utc>,
    pub end_time: Option<DateTime<Utc>>,
    pub duration_ms: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpanInfo {
    pub span_id: String,
    pub parent_span_id: Option<String>,
    pub operation_name: Option<String>,
    pub start_time: DateTime<Utc>,
    pub end_time: Option<DateTime<Utc>>,
    pub duration_ms: Option<f64>,
    pub logs: Vec<Uuid>,
}

/// Context around a specific log entry
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogContext {
    pub target: LogEntry,
    pub context_before: Vec<LogEntry>,
    pub context_after: Vec<LogEntry>,
    pub related_threads: Vec<ThreadEntries>,
}

/// Entries for a specific thread
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThreadEntries {
    pub thread_id: String,
    pub entries: Vec<LogEntry>,
}

/// Timeline reconstruction result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Timeline {
    pub events: Vec<TimelineEvent>,
    pub statistics: TimelineStatistics,
    pub anomalies: Vec<Anomaly>,
}

/// Single event in a timeline
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimelineEvent {
    pub timestamp: DateTime<Utc>,
    pub entries: Vec<LogEntry>,
}

/// Statistics about a timeline
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimelineStatistics {
    pub total_entries: usize,
    pub by_level: HashMap<String, usize>,
    pub by_thread: HashMap<String, usize>,
    pub errors_per_minute: Vec<usize>,
}

/// Detected anomaly
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Anomaly {
    pub timestamp: DateTime<Utc>,
    pub description: String,
    pub severity: AnomalySeverity,
    pub metric: String,
    pub value: f64,
    pub baseline: f64,
    pub deviation: f64,
}

/// Anomaly severity
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AnomalySeverity {
    Low,
    Medium,
    High,
    Critical,
}

/// Pattern detection result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PatternResults {
    pub patterns: Vec<Pattern>,
}

/// Detected pattern
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Pattern {
    pub pattern_type: PatternType,
    pub pattern: String,
    pub occurrences: usize,
    pub first_seen: DateTime<Utc>,
    pub last_seen: DateTime<Utc>,
    pub affected_threads: Vec<String>,
    pub examples: Vec<LogEntry>,
}

/// Type of detected pattern
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum PatternType {
    RepeatedError,
    CascadingFailure,
    PeriodicEvent,
}

/// Error analysis result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorAnalysis {
    pub error_groups: Vec<ErrorGroup>,
    pub unique_errors: usize,
    pub total_errors: usize,
}

/// Group of similar errors
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorGroup {
    pub signature: String,
    pub count: usize,
    pub first_seen: DateTime<Utc>,
    pub last_seen: DateTime<Utc>,
    pub affected_files: Vec<String>,
    pub affected_threads: Vec<String>,
    pub examples: Vec<LogEntry>,
    pub potential_cause: Option<String>,
}

/// Statistical analysis result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Statistics {
    pub metrics: HashMap<String, MetricStats>,
    pub insights: Vec<String>,
}

/// Statistics for a specific metric
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MetricStats {
    pub total: usize,
    pub by_level: Option<HashMap<String, usize>>,
    pub by_thread: Option<HashMap<String, usize>>,
    pub time_series: Vec<TimeSeriesPoint>,
    pub percentiles: Option<Percentiles>,
}

/// Time series data point
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimeSeriesPoint {
    pub timestamp: DateTime<Utc>,
    pub count: usize,
}

/// Percentile statistics
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Percentiles {
    pub p50: f64,
    pub p95: f64,
    pub p99: f64,
    pub max: f64,
}

/// File metadata
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileMetadata {
    pub path: String,
    pub size_bytes: u64,
    pub lines: usize,
    pub format: LogFormat,
    pub time_range: Option<TimeRange>,
    pub available_fields: Vec<String>,
    pub unique_threads: usize,
    pub unique_correlation_ids: usize,
    pub log_levels: HashMap<String, usize>,
}

/// Log file format
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum LogFormat {
    Json,
    PlainText,
    Syslog,
    CommonLog,
    Logfmt,
    Custom,
    Unknown,
}
