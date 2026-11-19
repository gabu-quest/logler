use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use uuid::Uuid;

use serde::Serializer;
use std::collections::BTreeMap;

/// A map that can be written as a JSON object with its keys in order.
/// A `HashMap` has a different order in every process; this is the one place that
/// fixes it, used with `#[serde(serialize_with = "sorted_map")]` on each map field.
pub trait SortedMap {
    fn serialize_sorted<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error>;
}

impl<K: Serialize + Ord, V: Serialize> SortedMap for HashMap<K, V> {
    fn serialize_sorted<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_map(self.iter().collect::<BTreeMap<_, _>>())
    }
}

impl<M: SortedMap> SortedMap for Option<M> {
    fn serialize_sorted<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self {
            Some(map) => map.serialize_sorted(serializer),
            None => serializer.serialize_none(),
        }
    }
}

pub fn sorted_map<S: Serializer, M: SortedMap>(map: &M, serializer: S) -> Result<S::Ok, S::Error> {
    map.serialize_sorted(serializer)
}

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
    #[serde(serialize_with = "sorted_map")]
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

/// The one table of level words: every word a log may use for a level, in capitals.
/// `LogLevel::parse`, `LogLevel::from_word` and the plain-text level patterns all read it.
pub const LEVEL_WORDS: &[(LogLevel, &[&str])] = &[
    (LogLevel::Trace, &["TRACE", "VERBOSE"]),
    (LogLevel::Debug, &["DEBUG"]),
    (LogLevel::Info, &["INFO", "INFORMATION", "NOTICE"]),
    (LogLevel::Warn, &["WARN", "WARNING"]),
    (LogLevel::Error, &["ERROR", "ERR", "SEVERE"]),
    (
        LogLevel::Fatal,
        &[
            "FATAL",
            "CRITICAL",
            "CRIT",
            "EMERG",
            "EMERGENCY",
            "ALERT",
            "PANIC",
        ],
    ),
];

impl LogLevel {
    /// The byte length of the longest word in `LEVEL_WORDS`.
    pub const LONGEST_WORD: usize = {
        let (mut longest, mut level) = (0, 0);
        while level < LEVEL_WORDS.len() {
            let words = LEVEL_WORDS[level].1;
            let mut word = 0;
            while word < words.len() {
                if words[word].len() > longest {
                    longest = words[word].len();
                }
                word += 1;
            }
            level += 1;
        }
        longest
    };

    /// The level a word names, ignoring letter case; `None` for a word not in the table.
    pub fn from_word(s: &str) -> Option<Self> {
        LEVEL_WORDS
            .iter()
            .find(|(_, words)| words.iter().any(|w| w.eq_ignore_ascii_case(s)))
            .map(|(level, _)| *level)
    }

    /// Like `from_word`, but any other word answers `Some(Unknown)`.
    pub fn parse(s: &str) -> Option<Self> {
        Some(Self::from_word(s).unwrap_or(Self::Unknown))
    }

    /// Every level word as a regex alternation, longest first, built from `LEVEL_WORDS`.
    pub fn words_pattern() -> String {
        let mut words: Vec<&str> = LEVEL_WORDS
            .iter()
            .flat_map(|(_, words)| words.iter().copied())
            .collect();
        words.sort_by_key(|w| std::cmp::Reverse(w.len()));
        words.join("|")
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
    #[serde(default)]
    pub tail: Option<usize>,
    pub context_lines: Option<usize>,
    /// When true, skip Phase 2 (materialization) and return only the count.
    #[serde(default)]
    pub count_only: Option<bool>,
    /// Number of sorted candidates to skip before taking `limit`.
    /// Enables pagination: page 2 with 100/page → offset=100, limit=100.
    #[serde(default)]
    pub offset: Option<usize>,
    /// When set, also count every match (`SearchResults::aggregates`), whatever the
    /// limit, tail, offset or `count_only`.
    #[serde(default)]
    pub aggregate: Option<Aggregate>,
}

/// What a search counts over every match, beside the page of entries it returns.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Aggregate {
    /// Levels, files and the time range.
    Counts,
    /// Those, and the messages.
    Messages,
}

/// Filters for searching logs
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SearchFilters {
    #[serde(default)]
    pub levels: Vec<LogLevel>,
    #[serde(default)]
    pub exclude_levels: Vec<LogLevel>,
    pub time_range: Option<TimeRange>,
    pub thread_id: Option<String>,
    #[serde(default)]
    pub thread_ids: Option<Vec<String>>,
    pub correlation_id: Option<String>,
    #[serde(default)]
    pub correlation_ids: Option<Vec<String>>,
    pub trace_id: Option<String>,
    #[serde(default)]
    pub trace_ids: Option<Vec<String>>,
    #[serde(default)]
    pub service_name: Option<String>,
    #[serde(default)]
    pub service_names: Option<Vec<String>>,
    pub has_correlation_id: Option<bool>,
    #[serde(default)]
    pub exclude_pattern: Option<String>,
}

/// Information about a discovered ID
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IdInfo {
    pub id: String,
    pub count: usize,
    pub first_seen: Option<DateTime<Utc>>,
    pub last_seen: Option<DateTime<Utc>>,
}

/// Result of ID extraction
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IdsResult {
    pub thread_ids: Vec<IdInfo>,
    pub correlation_ids: Vec<IdInfo>,
    pub trace_ids: Vec<IdInfo>,
    pub services: Vec<IdInfo>,
    pub total_entries: usize,
    pub time_range: Option<TimeRange>,
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
    /// Counts over every match; only when the query asked for them (`aggregate`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub aggregates: Option<SearchAggregates>,
}

/// Counts by name, written as a JSON object whose keys come in the order each name was
/// first counted (the order of the matches), never in hash order.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct OrderedCounts(pub Vec<(String, usize)>);

impl Serialize for OrderedCounts {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_map(self.0.iter().map(|(k, v)| (k, v)))
    }
}

impl<'de> Deserialize<'de> for OrderedCounts {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct Visitor;
        impl<'de> serde::de::Visitor<'de> for Visitor {
            type Value = OrderedCounts;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("a map of names to counts")
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(
                self,
                mut map: A,
            ) -> Result<Self::Value, A::Error> {
                let mut out = Vec::new();
                while let Some(pair) = map.next_entry()? {
                    out.push(pair);
                }
                Ok(OrderedCounts(out))
            }
        }
        deserializer.deserialize_map(Visitor)
    }
}

/// What the summary and count formats report, counted over every match of a search in
/// the order the search sorts them (by relevance then time; with `tail`, by time).
///
/// A level is its text in capitals (`LogLevel::as_str`); a line with no level is
/// `UNKNOWN`. A message is the entry's message with white space cut from both ends.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchAggregates {
    pub by_level: OrderedCounts,
    /// Matches per file (the entry's `file`).
    pub by_file: OrderedCounts,
    /// How many different messages the matches hold (with `Aggregate::Messages`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unique_messages: Option<usize>,
    /// The most frequent messages, at most `TOP_MESSAGES`, most frequent first; two of
    /// equal count in the order their first match comes (with `Aggregate::Messages`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub top_messages: Option<Vec<MessageSummary>>,
    /// The earliest and latest timestamp of a match; `None` when no match has one.
    pub time_range: Option<TimeRange>,
}

/// One message of `SearchAggregates::top_messages`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MessageSummary {
    /// The message, cut to its first `MESSAGE_CHARS` characters.
    pub message: String,
    pub count: usize,
    /// The earliest and latest timestamp of its matches; `None` when none has one.
    pub first_seen: Option<DateTime<Utc>>,
    pub last_seen: Option<DateTime<Utc>>,
    pub levels: OrderedCounts,
    /// Its first `MESSAGE_EXAMPLES` matches.
    pub examples: Vec<MessageExample>,
}

/// Where one match of a message is.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MessageExample {
    pub file: String,
    pub line: usize,
    pub timestamp: Option<DateTime<Utc>>,
    pub level: String,
}

/// Page of raw entries for bulk export (no search/filter/sort overhead).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EntriesPage {
    pub entries: Vec<LogEntry>,
    pub total_entries: usize,
    pub has_more: bool,
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
    #[serde(serialize_with = "sorted_map")]
    pub by_level: HashMap<String, usize>,
    #[serde(serialize_with = "sorted_map")]
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
    #[serde(serialize_with = "sorted_map")]
    pub metrics: HashMap<String, MetricStats>,
    pub insights: Vec<String>,
}

/// Statistics for a specific metric
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MetricStats {
    pub total: usize,
    #[serde(serialize_with = "sorted_map")]
    pub by_level: Option<HashMap<String, usize>>,
    #[serde(serialize_with = "sorted_map")]
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
    #[serde(serialize_with = "sorted_map")]
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_level_word_table_maps_every_word_in_any_letter_case() {
        let table: &[(LogLevel, &[&str])] = &[
            (LogLevel::Trace, &["TRACE", "VERBOSE"]),
            (LogLevel::Debug, &["DEBUG"]),
            (LogLevel::Info, &["INFO", "INFORMATION", "NOTICE"]),
            (LogLevel::Warn, &["WARN", "WARNING"]),
            (LogLevel::Error, &["ERROR", "ERR", "SEVERE"]),
            (
                LogLevel::Fatal,
                &[
                    "FATAL",
                    "CRITICAL",
                    "CRIT",
                    "EMERG",
                    "EMERGENCY",
                    "ALERT",
                    "PANIC",
                ],
            ),
        ];
        for (level, words) in table {
            for word in *words {
                for spelling in [word.to_string(), word.to_lowercase()] {
                    assert_eq!(
                        LogLevel::parse(&spelling),
                        Some(*level),
                        "word {spelling:?} should read as {level:?}"
                    );
                }
            }
        }
        assert_eq!(
            LogLevel::parse("bogus"),
            Some(LogLevel::Unknown),
            "an unlisted word answers Some(Unknown)"
        );
    }
}
