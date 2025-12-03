use crate::types::{LogEntry, LogLevel};
use chrono::{DateTime, Utc};
use regex::Regex;
use std::collections::HashMap;
use std::sync::OnceLock;

static TIMESTAMP_RE: OnceLock<Regex> = OnceLock::new();
static LOG_LEVEL_RE: OnceLock<Regex> = OnceLock::new();
static THREAD_ID_RE: OnceLock<Regex> = OnceLock::new();
static CORRELATION_ID_RE: OnceLock<Regex> = OnceLock::new();
static TRACE_ID_RE: OnceLock<Regex> = OnceLock::new();
static SPAN_ID_RE: OnceLock<Regex> = OnceLock::new();

fn init_regexes() {
    TIMESTAMP_RE.get_or_init(|| {
        Regex::new(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?").unwrap()
    });
    LOG_LEVEL_RE.get_or_init(|| {
        Regex::new(r"\b(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\b").unwrap()
    });
    THREAD_ID_RE.get_or_init(|| {
        Regex::new(r"(?:thread[=:\s]+|tid[=:\s]+|\[)([a-zA-Z0-9_-]+)(?:\])?").unwrap()
    });
    CORRELATION_ID_RE.get_or_init(|| {
        Regex::new(r"(?:correlation[_-]?id|request[_-]?id|req[_-]?id)[=:\s]+([a-zA-Z0-9_-]+)").unwrap()
    });
    TRACE_ID_RE.get_or_init(|| {
        Regex::new(r"(?:trace[_-]?id|traceId)[=:\s]+([a-fA-F0-9]{16,32})").unwrap()
    });
    SPAN_ID_RE.get_or_init(|| {
        Regex::new(r"(?:span[_-]?id|spanId)[=:\s]+([a-zA-Z0-9_-]+)").unwrap()
    });
}

/// Fast log parser supporting JSON and plain text formats
#[derive(Debug)]
pub struct LogParser {
    file_name: String,
}

impl LogParser {
    pub fn new(file_name: String) -> Self {
        init_regexes();
        Self { file_name }
    }

    /// Parse a single log line
    pub fn parse_line(&self, line_number: usize, raw: &str) -> anyhow::Result<LogEntry> {
        // Try JSON first
        if let Some(entry) = self.try_parse_json(line_number, raw) {
            return Ok(entry);
        }

        // Fall back to plain text parsing
        Ok(self.parse_plain(line_number, raw))
    }

    /// Try to parse as JSON
    fn try_parse_json(&self, line_number: usize, raw: &str) -> Option<LogEntry> {
        let trimmed = raw.trim();
        if !trimmed.starts_with('{') {
            return None;
        }

        let data: serde_json::Value = serde_json::from_str(trimmed).ok()?;
        let obj = data.as_object()?;

        let timestamp = self.extract_json_timestamp(obj);
        let level = self.extract_json_level(obj);
        let message = self.extract_json_message(obj);
        let thread_id = self.extract_json_field(obj, &["thread", "thread_id", "tid"]);
        let correlation_id = self.extract_json_field(obj, &["correlation_id", "request_id", "req_id"]);
        let trace_id = self.extract_json_field(obj, &["trace_id", "traceId"]);
        let span_id = self.extract_json_field(obj, &["span_id", "spanId"]);
        let service_name = self.extract_json_field(obj, &["service", "service_name", "serviceName"]);

        let mut fields = HashMap::new();
        for (key, value) in obj.iter() {
            if !matches!(key.as_str(), "timestamp" | "time" | "level" | "message" | "msg" | "thread" | "thread_id" | "service" | "service_name" | "serviceName" | "correlation_id" | "request_id" | "req_id" | "trace_id" | "traceId" | "span_id" | "spanId") {
                fields.insert(key.clone(), value.clone());
            }
        }

        Some(LogEntry {
            file: self.file_name.clone(),
            line_number,
            raw: raw.to_string(),
            timestamp,
            level,
            message,
            thread_id,
            correlation_id,
            trace_id,
            span_id,
            service_name,
            fields,
        })
    }

    /// Parse as plain text
    fn parse_plain(&self, line_number: usize, raw: &str) -> LogEntry {
        let timestamp = self.extract_timestamp(raw);
        let level = self.extract_level(raw);
        let thread_id = self.extract_thread_id(raw);
        let correlation_id = self.extract_correlation_id(raw);
        let trace_id = self.extract_trace_id(raw);
        let span_id = self.extract_span_id(raw);

        LogEntry {
            file: self.file_name.clone(),
            line_number,
            raw: raw.to_string(),
            timestamp,
            level,
            message: raw.to_string(),
            thread_id,
            correlation_id,
            trace_id,
            span_id,
            service_name: None,
            fields: HashMap::new(),
        }
    }

    /// Extract timestamp from JSON
    fn extract_json_timestamp(&self, obj: &serde_json::Map<String, serde_json::Value>) -> Option<DateTime<Utc>> {
        for field in &["timestamp", "time", "@timestamp", "ts"] {
            if let Some(value) = obj.get(*field) {
                if let Some(s) = value.as_str() {
                    if let Ok(dt) = DateTime::parse_from_rfc3339(s) {
                        return Some(dt.with_timezone(&Utc));
                    }
                }
            }
        }
        None
    }

    /// Extract log level from JSON
    fn extract_json_level(&self, obj: &serde_json::Map<String, serde_json::Value>) -> Option<LogLevel> {
        for field in &["level", "severity", "log_level"] {
            if let Some(value) = obj.get(*field) {
                if let Some(s) = value.as_str() {
                    return LogLevel::from_str(s);
                }
            }
        }
        None
    }

    /// Extract message from JSON
    fn extract_json_message(&self, obj: &serde_json::Map<String, serde_json::Value>) -> String {
        for field in &["message", "msg", "text"] {
            if let Some(value) = obj.get(*field) {
                if let Some(s) = value.as_str() {
                    return s.to_string();
                }
            }
        }
        // Fall back to stringifying the whole object
        serde_json::to_string(obj).unwrap_or_default()
    }

    /// Extract a field from JSON
    fn extract_json_field(&self, obj: &serde_json::Map<String, serde_json::Value>, keys: &[&str]) -> Option<String> {
        for key in keys {
            if let Some(value) = obj.get(*key) {
                if let Some(s) = value.as_str() {
                    return Some(s.to_string());
                }
            }
        }
        None
    }

    /// Extract timestamp from plain text
    fn extract_timestamp(&self, text: &str) -> Option<DateTime<Utc>> {
        let re = TIMESTAMP_RE.get()?;
        let cap = re.find(text)?;
        let ts_str = cap.as_str();

        // Try different datetime formats
        if let Ok(dt) = DateTime::parse_from_rfc3339(ts_str) {
            return Some(dt.with_timezone(&Utc));
        }

        // Try without timezone
        if let Ok(dt) = chrono::NaiveDateTime::parse_from_str(ts_str, "%Y-%m-%d %H:%M:%S") {
            return Some(DateTime::<Utc>::from_naive_utc_and_offset(dt, Utc));
        }

        if let Ok(dt) = chrono::NaiveDateTime::parse_from_str(ts_str, "%Y-%m-%dT%H:%M:%S") {
            return Some(DateTime::<Utc>::from_naive_utc_and_offset(dt, Utc));
        }

        None
    }

    /// Extract log level from plain text
    fn extract_level(&self, text: &str) -> Option<LogLevel> {
        let re = LOG_LEVEL_RE.get()?;
        let cap = re.find(text)?;
        LogLevel::from_str(cap.as_str())
    }

    /// Extract thread ID from plain text
    fn extract_thread_id(&self, text: &str) -> Option<String> {
        let re = THREAD_ID_RE.get()?;
        let cap = re.captures(text)?;
        Some(cap.get(1)?.as_str().to_string())
    }

    /// Extract correlation ID from plain text
    fn extract_correlation_id(&self, text: &str) -> Option<String> {
        let re = CORRELATION_ID_RE.get()?;
        let cap = re.captures(text)?;
        Some(cap.get(1)?.as_str().to_string())
    }

    /// Extract trace ID from plain text
    fn extract_trace_id(&self, text: &str) -> Option<String> {
        let re = TRACE_ID_RE.get()?;
        let cap = re.captures(text)?;
        Some(cap.get(1)?.as_str().to_string())
    }

    /// Extract span ID from plain text
    fn extract_span_id(&self, text: &str) -> Option<String> {
        let re = SPAN_ID_RE.get()?;
        let cap = re.captures(text)?;
        Some(cap.get(1)?.as_str().to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_json() {
        let parser = LogParser::new("test.log".to_string());
        let json_line = r#"{"timestamp":"2024-01-15T10:00:00Z","level":"ERROR","message":"Test error","thread_id":"worker-1"}"#;
        let entry = parser.parse_line(1, json_line).unwrap();

        assert_eq!(entry.line_number, 1);
        assert_eq!(entry.level, Some(LogLevel::Error));
        assert_eq!(entry.message, "Test error");
        assert_eq!(entry.thread_id, Some("worker-1".to_string()));
    }

    #[test]
    fn test_parse_plain_text() {
        let parser = LogParser::new("test.log".to_string());
        let plain_line = "2024-01-15 10:00:00 ERROR [worker-1] Test error message";
        let entry = parser.parse_line(1, plain_line).unwrap();

        assert_eq!(entry.line_number, 1);
        assert_eq!(entry.level, Some(LogLevel::Error));
        assert!(entry.timestamp.is_some());
        assert_eq!(entry.thread_id, Some("worker-1".to_string()));
    }
}
