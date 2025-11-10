use crate::types::{LogEntry, LogFormat, LogLevel, SourceLocation};
use chrono::{DateTime, Utc};
use regex::Regex;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::OnceLock;

static PATTERNS: OnceLock<ParserPatterns> = OnceLock::new();

struct ParserPatterns {
    timestamp_iso: Regex,
    #[allow(dead_code)]
    timestamp_rfc3339: Regex,
    #[allow(dead_code)]
    timestamp_common: Regex,
    log_level: Regex,
    thread_id: Regex,
    correlation_id: Regex,
    trace_id: Regex,
    span_id: Regex,
    source_location: Regex,
    syslog_priority: Regex,
    common_log: Regex,
    logfmt: Regex,
}

impl ParserPatterns {
    fn new() -> Self {
        Self {
            timestamp_iso: Regex::new(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?").unwrap(),
            timestamp_rfc3339: Regex::new(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})").unwrap(),
            timestamp_common: Regex::new(r"\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4}").unwrap(),
            log_level: Regex::new(r"\b(TRACE|VERBOSE|DEBUG|INFO|INFORMATION|WARN|WARNING|ERROR|ERR|FATAL|CRITICAL|CRIT)\b").unwrap(),
            thread_id: Regex::new(r"(?:thread[=:\s]+|tid[=:\s]+|TID[=:\s]+)([a-zA-Z0-9_-]+|\d+)").unwrap(),
            correlation_id: Regex::new(r"(?:correlation[_-]?id|request[_-]?id|req[_-]?id)[=:\s]+([a-zA-Z0-9_-]+)").unwrap(),
            trace_id: Regex::new(r"(?:trace[_-]?id|traceId)[=:\s]+([a-fA-F0-9]{16,32})").unwrap(),
            span_id: Regex::new(r"(?:span[_-]?id|spanId)[=:\s]+([a-fA-F0-9]{8,16})").unwrap(),
            source_location: Regex::new(r"([a-zA-Z_][\w./\\]*\.(?:rs|java|py|js|ts|go|cpp|c)):(\d+)").unwrap(),
            syslog_priority: Regex::new(r"^<(\d+)>").unwrap(),
            common_log: Regex::new(r#"^(\S+) \S+ \S+ \[([^\]]+)\] "([^"]+)" (\d+) (\S+)"#).unwrap(),
            logfmt: Regex::new(r#"(\w+)=(?:"([^"]*)"|([^\s]+))"#).unwrap(),
        }
    }
}

fn patterns() -> &'static ParserPatterns {
    PATTERNS.get_or_init(ParserPatterns::new)
}

pub struct LogParser {
    force_format: Option<LogFormat>,
}

pub type ParsedLog = LogEntry;

impl LogParser {
    pub fn new() -> Self {
        Self { force_format: None }
    }

    pub fn with_format(format: LogFormat) -> Self {
        Self {
            force_format: Some(format),
        }
    }

    pub fn parse(&self, line_number: usize, raw: String) -> ParsedLog {
        let mut entry = LogEntry::new(line_number, raw.clone());

        // Detect format
        entry.format = self.force_format.unwrap_or_else(|| self.detect_format(&raw));

        // Parse based on format
        match entry.format {
            LogFormat::Json => self.parse_json(&raw, &mut entry),
            LogFormat::Syslog => self.parse_syslog(&raw, &mut entry),
            LogFormat::CommonLog => self.parse_common_log(&raw, &mut entry),
            LogFormat::Logfmt => self.parse_logfmt(&raw, &mut entry),
            _ => self.parse_plain(&raw, &mut entry),
        }

        // Extract common fields from any format
        self.extract_common_fields(&raw, &mut entry);

        entry
    }

    fn detect_format(&self, line: &str) -> LogFormat {
        let trimmed = line.trim();

        // Check for JSON
        if trimmed.starts_with('{') {
            if serde_json::from_str::<Value>(trimmed).is_ok() {
                return LogFormat::Json;
            }
        }

        // Check for syslog
        if patterns().syslog_priority.is_match(line) {
            return LogFormat::Syslog;
        }

        // Check for common log format
        if patterns().common_log.is_match(line) {
            return LogFormat::CommonLog;
        }

        // Check for logfmt (key=value pairs)
        let logfmt_matches = patterns().logfmt.find_iter(line).count();
        if logfmt_matches >= 3 {
            return LogFormat::Logfmt;
        }

        LogFormat::Plain
    }

    fn parse_json(&self, raw: &str, entry: &mut LogEntry) {
        if let Ok(value) = serde_json::from_str::<Value>(raw.trim()) {
            if let Some(obj) = value.as_object() {
                // Timestamp
                for ts_field in ["timestamp", "time", "ts", "@timestamp", "datetime", "date"] {
                    if let Some(ts) = obj.get(ts_field) {
                        if let Some(ts_str) = ts.as_str() {
                            if let Ok(dt) = DateTime::parse_from_rfc3339(ts_str) {
                                entry.timestamp = Some(dt.with_timezone(&Utc));
                                break;
                            }
                        } else if let Some(ts_num) = ts.as_i64() {
                            if let Some(dt) = DateTime::from_timestamp(ts_num, 0) {
                                entry.timestamp = Some(dt);
                                break;
                            }
                        }
                    }
                }

                // Level
                for level_field in ["level", "severity", "loglevel", "lvl"] {
                    if let Some(level) = obj.get(level_field).and_then(|v| v.as_str()) {
                        entry.level = LogLevel::from_str(level);
                        break;
                    }
                }

                // Message
                for msg_field in ["message", "msg", "text", "content"] {
                    if let Some(msg) = obj.get(msg_field).and_then(|v| v.as_str()) {
                        entry.message = msg.to_string();
                        break;
                    }
                }

                // Thread ID
                for thread_field in ["thread", "thread_id", "threadId", "tid"] {
                    if let Some(thread) = obj.get(thread_field) {
                        entry.thread_id = Some(thread.to_string().trim_matches('"').to_string());
                        break;
                    }
                }

                // Correlation/Request ID
                for corr_field in ["correlation_id", "correlationId", "request_id", "requestId", "req_id"] {
                    if let Some(corr) = obj.get(corr_field).and_then(|v| v.as_str()) {
                        entry.correlation_id = Some(corr.to_string());
                        break;
                    }
                }

                // Trace ID
                for trace_field in ["trace_id", "traceId", "trace"] {
                    if let Some(trace) = obj.get(trace_field).and_then(|v| v.as_str()) {
                        entry.trace_id = Some(trace.to_string());
                        break;
                    }
                }

                // Span ID
                for span_field in ["span_id", "spanId", "span"] {
                    if let Some(span) = obj.get(span_field).and_then(|v| v.as_str()) {
                        entry.span_id = Some(span.to_string());
                        break;
                    }
                }

                // Parent Span ID
                for parent_field in ["parent_span_id", "parentSpanId", "parent_span"] {
                    if let Some(parent) = obj.get(parent_field).and_then(|v| v.as_str()) {
                        entry.parent_span_id = Some(parent.to_string());
                        break;
                    }
                }

                // Service name
                for service_field in ["service", "service_name", "serviceName"] {
                    if let Some(service) = obj.get(service_field).and_then(|v| v.as_str()) {
                        entry.service_name = Some(service.to_string());
                        break;
                    }
                }

                // Source location
                if let Some(file) = obj.get("file").or_else(|| obj.get("source_file")).and_then(|v| v.as_str()) {
                    let line = obj.get("line").or_else(|| obj.get("source_line")).and_then(|v| v.as_u64()).map(|v| v as u32);
                    let function = obj.get("function").or_else(|| obj.get("method")).and_then(|v| v.as_str()).map(|s| s.to_string());
                    entry.source_location = Some(SourceLocation {
                        file: file.to_string(),
                        line,
                        function,
                    });
                }

                // Store all other fields
                let skip_fields = [
                    "timestamp", "time", "ts", "@timestamp", "datetime", "date",
                    "level", "severity", "loglevel", "lvl",
                    "message", "msg", "text", "content",
                    "thread", "thread_id", "threadId", "tid",
                    "correlation_id", "correlationId", "request_id", "requestId", "req_id",
                    "trace_id", "traceId", "trace",
                    "span_id", "spanId", "span",
                    "parent_span_id", "parentSpanId", "parent_span",
                    "service", "service_name", "serviceName",
                    "file", "source_file", "line", "source_line", "function", "method",
                ];

                for (key, value) in obj.iter() {
                    if !skip_fields.contains(&key.as_str()) {
                        entry.fields.insert(key.clone(), value.clone());
                    }
                }
            }
        }
    }

    fn parse_plain(&self, raw: &str, entry: &mut LogEntry) {
        // Extract timestamp
        if let Some(cap) = patterns().timestamp_iso.find(raw) {
            if let Ok(dt) = DateTime::parse_from_rfc3339(cap.as_str()) {
                entry.timestamp = Some(dt.with_timezone(&Utc));
            } else if let Ok(dt) = chrono::NaiveDateTime::parse_from_str(cap.as_str(), "%Y-%m-%d %H:%M:%S") {
                entry.timestamp = Some(dt.and_utc());
            }
        }

        // Extract log level
        if let Some(cap) = patterns().log_level.captures(raw) {
            entry.level = LogLevel::from_str(&cap[1]);
        }

        // Message is the raw line for plain format
        entry.message = raw.to_string();
    }

    fn parse_syslog(&self, raw: &str, entry: &mut LogEntry) {
        let mut line = raw;

        // Remove priority if present
        if let Some(cap) = patterns().syslog_priority.captures(raw) {
            let priority: u32 = cap[1].parse().unwrap_or(0);
            let severity = priority & 0x07;
            entry.level = match severity {
                0 => LogLevel::Fatal,
                1..=3 => LogLevel::Error,
                4 => LogLevel::Warn,
                5..=6 => LogLevel::Info,
                7 => LogLevel::Debug,
                _ => LogLevel::Unknown,
            };
            line = &raw[cap.get(0).unwrap().end()..];
        }

        // Parse the rest as plain
        self.parse_plain(line, entry);
    }

    fn parse_common_log(&self, raw: &str, entry: &mut LogEntry) {
        if let Some(cap) = patterns().common_log.captures(raw) {
            let timestamp_str = &cap[2];
            if let Ok(dt) = DateTime::parse_from_str(timestamp_str, "%d/%b/%Y:%H:%M:%S %z") {
                entry.timestamp = Some(dt.with_timezone(&Utc));
            }

            let status: u16 = cap[4].parse().unwrap_or(0);
            entry.level = if status >= 500 {
                LogLevel::Error
            } else if status >= 400 {
                LogLevel::Warn
            } else {
                LogLevel::Info
            };

            entry.message = format!("{} {} {}", &cap[1], &cap[3], &cap[4]);
            entry.fields.insert("remote_addr".to_string(), Value::String(cap[1].to_string()));
            entry.fields.insert("request".to_string(), Value::String(cap[3].to_string()));
            entry.fields.insert("status".to_string(), Value::Number(status.into()));
            entry.fields.insert("size".to_string(), Value::String(cap[5].to_string()));
        }
    }

    fn parse_logfmt(&self, raw: &str, entry: &mut LogEntry) {
        let mut fields = HashMap::new();

        for cap in patterns().logfmt.captures_iter(raw) {
            let key = &cap[1];
            let value = cap.get(2).or_else(|| cap.get(3)).map(|m| m.as_str()).unwrap_or("");

            // Try to parse as JSON value
            let json_value = if value.parse::<i64>().is_ok() {
                Value::Number(value.parse().unwrap())
            } else if value.parse::<f64>().is_ok() {
                Value::Number(serde_json::Number::from_f64(value.parse().unwrap()).unwrap())
            } else if value == "true" || value == "false" {
                Value::Bool(value == "true")
            } else {
                Value::String(value.to_string())
            };

            fields.insert(key.to_string(), json_value);
        }

        // Extract known fields
        if let Some(Value::String(level)) = fields.get("level") {
            entry.level = LogLevel::from_str(level);
        }
        if let Some(Value::String(msg)) = fields.get("msg").or_else(|| fields.get("message")) {
            entry.message = msg.clone();
        }

        entry.fields = fields;
    }

    fn extract_common_fields(&self, raw: &str, entry: &mut LogEntry) {
        // Thread ID
        if entry.thread_id.is_none() {
            if let Some(cap) = patterns().thread_id.captures(raw) {
                entry.thread_id = Some(cap[1].to_string());
            }
        }

        // Correlation ID
        if entry.correlation_id.is_none() {
            if let Some(cap) = patterns().correlation_id.captures(raw) {
                entry.correlation_id = Some(cap[1].to_string());
            }
        }

        // Trace ID
        if entry.trace_id.is_none() {
            if let Some(cap) = patterns().trace_id.captures(raw) {
                entry.trace_id = Some(cap[1].to_string());
            }
        }

        // Span ID
        if entry.span_id.is_none() {
            if let Some(cap) = patterns().span_id.captures(raw) {
                entry.span_id = Some(cap[1].to_string());
            }
        }

        // Source location
        if entry.source_location.is_none() {
            if let Some(cap) = patterns().source_location.captures(raw) {
                entry.source_location = Some(SourceLocation {
                    file: cap[1].to_string(),
                    line: cap[2].parse().ok(),
                    function: None,
                });
            }
        }
    }
}

impl Default for LogParser {
    fn default() -> Self {
        Self::new()
    }
}

impl Clone for LogParser {
    fn clone(&self) -> Self {
        Self {
            force_format: self.force_format,
        }
    }
}
