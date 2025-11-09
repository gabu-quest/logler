use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use uuid::Uuid;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
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
    pub fn from_str(s: &str) -> Self {
        match s.to_uppercase().as_str() {
            "TRACE" | "VERBOSE" => LogLevel::Trace,
            "DEBUG" => LogLevel::Debug,
            "INFO" | "INFORMATION" => LogLevel::Info,
            "WARN" | "WARNING" => LogLevel::Warn,
            "ERROR" | "ERR" => LogLevel::Error,
            "FATAL" | "CRITICAL" | "CRIT" => LogLevel::Fatal,
            _ => LogLevel::Unknown,
        }
    }

    pub fn severity(&self) -> u8 {
        match self {
            LogLevel::Trace => 0,
            LogLevel::Debug => 1,
            LogLevel::Info => 2,
            LogLevel::Warn => 3,
            LogLevel::Error => 4,
            LogLevel::Fatal => 5,
            LogLevel::Unknown => 0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum LogFormat {
    Json,
    Plain,
    Syslog,
    CommonLog,
    Logfmt,
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogEntry {
    /// Unique ID for this log entry
    pub id: Uuid,

    /// Line number in the source file
    pub line_number: usize,

    /// Timestamp of the log entry
    pub timestamp: Option<DateTime<Utc>>,

    /// Log level
    pub level: LogLevel,

    /// Main log message
    pub message: String,

    /// Original raw line
    pub raw: String,

    /// Detected format
    pub format: LogFormat,

    /// Thread ID or name
    pub thread_id: Option<String>,

    /// Correlation/Request ID for tracking across services
    pub correlation_id: Option<String>,

    /// Trace ID for distributed tracing
    pub trace_id: Option<String>,

    /// Span ID for distributed tracing
    pub span_id: Option<String>,

    /// Parent span ID
    pub parent_span_id: Option<String>,

    /// Service name
    pub service_name: Option<String>,

    /// Additional structured fields
    pub fields: HashMap<String, serde_json::Value>,

    /// Source file and line (if available in log)
    pub source_location: Option<SourceLocation>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SourceLocation {
    pub file: String,
    pub line: Option<u32>,
    pub function: Option<String>,
}

impl LogEntry {
    pub fn new(line_number: usize, raw: String) -> Self {
        Self {
            id: Uuid::new_v4(),
            line_number,
            timestamp: None,
            level: LogLevel::Unknown,
            message: String::new(),
            raw,
            format: LogFormat::Unknown,
            thread_id: None,
            correlation_id: None,
            trace_id: None,
            span_id: None,
            parent_span_id: None,
            service_name: None,
            fields: HashMap::new(),
            source_location: None,
        }
    }
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
    pub logs: Vec<Uuid>, // References to log entries
}
