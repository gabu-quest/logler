use crate::types::{LogEntry, LogFormat, LogLevel};
use chrono::{DateTime, Utc};
use regex::Regex;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::OnceLock;
use uuid::Uuid;

static TIMESTAMP_RE: OnceLock<Regex> = OnceLock::new();
static LOG_LEVEL_RE: OnceLock<Regex> = OnceLock::new();
static THREAD_ID_RE: OnceLock<Regex> = OnceLock::new();
static CORRELATION_ID_RE: OnceLock<Regex> = OnceLock::new();
static TRACE_ID_RE: OnceLock<Regex> = OnceLock::new();
static SPAN_ID_RE: OnceLock<Regex> = OnceLock::new();
static SYSLOG_PRIORITY_RE: OnceLock<Regex> = OnceLock::new();
static COMMON_LOG_RE: OnceLock<Regex> = OnceLock::new();
static LOGFMT_PAIR_RE: OnceLock<Regex> = OnceLock::new();

fn init_regexes() {
    TIMESTAMP_RE.get_or_init(|| {
        Regex::new(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
            .unwrap()
    });
    LOG_LEVEL_RE.get_or_init(|| {
        Regex::new(r"\b(TRACE|VERBOSE|DEBUG|INFO|INFORMATION|WARN|WARNING|ERROR|ERR|FATAL|CRITICAL|CRIT)\b")
            .unwrap()
    });
    THREAD_ID_RE.get_or_init(|| {
        Regex::new(r"(?:thread[=:\s]+|tid[=:\s]+|\[)([a-zA-Z0-9_-]+)(?:\])?").unwrap()
    });
    CORRELATION_ID_RE.get_or_init(|| {
        Regex::new(r"(?:correlation[_-]?id|request[_-]?id|req[_-]?id)[=:\s]+([a-zA-Z0-9_-]+)")
            .unwrap()
    });
    TRACE_ID_RE.get_or_init(|| {
        Regex::new(r"(?:trace[_-]?id|traceId)[=:\s]+([a-fA-F0-9]{16,32})").unwrap()
    });
    SPAN_ID_RE
        .get_or_init(|| Regex::new(r"(?:span[_-]?id|spanId)[=:\s]+([a-zA-Z0-9_-]+)").unwrap());
    SYSLOG_PRIORITY_RE.get_or_init(|| Regex::new(r"^<(\d+)>").unwrap());
    COMMON_LOG_RE.get_or_init(|| {
        Regex::new(r#"^(\S+) \S+ \S+ \[([^\]]+)\] "([^"]+)" (\d+) (\S+)"#).unwrap()
    });
    LOGFMT_PAIR_RE.get_or_init(|| Regex::new(r#"(\w+)=(?:"([^"]*)"|([^\s]+))"#).unwrap());
}

#[derive(Debug, Clone, Default)]
pub struct ParserConfig {
    pub force_format: Option<LogFormat>,
    pub custom_regex: Option<Regex>,
}

impl ParserConfig {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_force_format(mut self, format: LogFormat) -> Self {
        self.force_format = Some(format);
        self
    }

    pub fn with_custom_regex(mut self, regex: Regex) -> Self {
        self.custom_regex = Some(regex);
        self.force_format = Some(LogFormat::Custom);
        self
    }

    pub fn build_for_file<S: Into<String>>(&self, file_name: S) -> LogParser {
        LogParser::from_config(file_name, self.clone())
    }
}

#[derive(Debug, Clone)]
pub struct LogParser {
    file_name: String,
    config: ParserConfig,
}

impl LogParser {
    pub fn new<S: Into<String>>(file_name: S) -> Self {
        Self::from_config(file_name, ParserConfig::default())
    }

    pub fn with_force_format<S: Into<String>>(file_name: S, format: LogFormat) -> Self {
        Self::from_config(
            file_name,
            ParserConfig {
                force_format: Some(format),
                custom_regex: None,
            },
        )
    }

    pub fn with_custom_regex<S: Into<String>>(file_name: S, regex: Regex) -> Self {
        Self::from_config(
            file_name,
            ParserConfig {
                force_format: Some(LogFormat::Custom),
                custom_regex: Some(regex),
            },
        )
    }

    pub fn from_config<S: Into<String>>(file_name: S, config: ParserConfig) -> Self {
        init_regexes();
        Self {
            file_name: file_name.into(),
            config,
        }
    }

    pub fn set_custom_regex(mut self, regex: Regex) -> Self {
        self.config.custom_regex = Some(regex);
        self.config.force_format = Some(LogFormat::Custom);
        self
    }

    pub fn parse_line(&self, line_number: usize, raw: &str) -> anyhow::Result<LogEntry> {
        let format = self
            .config
            .force_format
            .unwrap_or_else(|| Self::detect_format(raw));
        let parsed = match format {
            LogFormat::Json => self.try_parse_json(line_number, raw),
            LogFormat::Syslog => self.parse_syslog(line_number, raw),
            LogFormat::CommonLog => self.parse_common_log(line_number, raw),
            LogFormat::Logfmt => self.parse_logfmt(line_number, raw),
            LogFormat::PlainText | LogFormat::Unknown => Some(self.parse_plain(line_number, raw)),
            LogFormat::Custom => self
                .config
                .custom_regex
                .as_ref()
                .and_then(|regex| self.try_parse_custom(line_number, raw, regex)),
        };

        let mut entry = parsed.unwrap_or_else(|| self.parse_plain(line_number, raw));

        // If a custom regex was provided but not matched earlier, try again on the parsed line.
        if entry.format == LogFormat::PlainText {
            if let Some(regex) = &self.config.custom_regex {
                if let Some(custom_entry) = self.try_parse_custom(line_number, raw, regex) {
                    entry = custom_entry;
                }
            }
        }

        // Fallback: if syslog priority is present but detection missed, still parse as syslog.
        if entry.format == LogFormat::PlainText {
            if let Some(syslog_re) = SYSLOG_PRIORITY_RE.get() {
                if syslog_re.is_match(raw) {
                    if let Some(syslog_entry) = self.parse_syslog(line_number, raw) {
                        entry = syslog_entry;
                    }
                }
            }
        }

        Ok(entry)
    }

    pub fn detect_format(line: &str) -> LogFormat {
        init_regexes();
        let trimmed = line.trim();
        if trimmed.starts_with('{') && serde_json::from_str::<Value>(trimmed).is_ok() {
            return LogFormat::Json;
        }
        if SYSLOG_PRIORITY_RE.get().unwrap().is_match(trimmed) {
            return LogFormat::Syslog;
        }
        if COMMON_LOG_RE.get().unwrap().is_match(trimmed) {
            return LogFormat::CommonLog;
        }
        let logfmt_matches = LOGFMT_PAIR_RE
            .get()
            .unwrap()
            .find_iter(trimmed)
            .take(3)
            .count();
        if logfmt_matches >= 3 {
            return LogFormat::Logfmt;
        }
        LogFormat::PlainText
    }

    fn base_entry(&self, line_number: usize, raw: &str, format: LogFormat) -> LogEntry {
        LogEntry {
            id: Uuid::new_v4(),
            file: self.file_name.clone(),
            line_number,
            raw: raw.to_string(),
            timestamp: None,
            level: None,
            format,
            message: raw.to_string(),
            thread_id: None,
            correlation_id: None,
            trace_id: None,
            span_id: None,
            parent_span_id: None,
            service_name: None,
            fields: HashMap::new(),
        }
    }

    fn try_parse_json(&self, line_number: usize, raw: &str) -> Option<LogEntry> {
        let trimmed = raw.trim();
        if !trimmed.starts_with('{') {
            return None;
        }

        let value: Value = serde_json::from_str(trimmed).ok()?;
        let obj = value.as_object()?;
        let mut entry = self.base_entry(line_number, raw, LogFormat::Json);

        entry.timestamp = self.extract_json_timestamp(obj);
        entry.level = self.extract_json_level(obj);
        entry.message = self.extract_json_message(obj);
        entry.thread_id = self.extract_json_field(obj, &["thread", "thread_id", "tid"]);
        entry.correlation_id =
            self.extract_json_field(obj, &["correlation_id", "request_id", "req_id"]);
        entry.trace_id = self.extract_json_field(obj, &["trace_id", "traceId"]);
        entry.span_id = self.extract_json_field(obj, &["span_id", "spanId"]);
        entry.parent_span_id = self.extract_json_field(obj, &["parent_span_id", "parentSpanId"]);
        entry.service_name =
            self.extract_json_field(obj, &["service", "service_name", "serviceName"]);

        for (key, value) in obj.iter() {
            if !matches!(
                key.as_str(),
                "timestamp"
                    | "time"
                    | "@timestamp"
                    | "ts"
                    | "level"
                    | "severity"
                    | "log_level"
                    | "message"
                    | "msg"
                    | "text"
                    | "thread"
                    | "thread_id"
                    | "tid"
                    | "service"
                    | "service_name"
                    | "serviceName"
                    | "correlation_id"
                    | "request_id"
                    | "req_id"
                    | "trace_id"
                    | "traceId"
                    | "span_id"
                    | "spanId"
                    | "parent_span_id"
                    | "parentSpanId"
            ) {
                entry.fields.insert(key.clone(), value.clone());
            }
        }

        Some(entry)
    }

    fn parse_plain(&self, line_number: usize, raw: &str) -> LogEntry {
        let mut entry = self.base_entry(line_number, raw, LogFormat::PlainText);

        entry.timestamp = self.extract_timestamp(raw);
        entry.level = self.extract_level(raw);
        entry.thread_id = self.extract_thread_id(raw);
        entry.correlation_id = self.extract_correlation_id(raw);
        entry.trace_id = self.extract_trace_id(raw);
        entry.span_id = self.extract_span_id(raw);

        entry
    }

    fn parse_syslog(&self, line_number: usize, raw: &str) -> Option<LogEntry> {
        let mut entry = self.base_entry(line_number, raw, LogFormat::Syslog);
        let mut remaining = raw;

        if let Some(cap) = SYSLOG_PRIORITY_RE.get()?.captures(raw) {
            let priority: u32 = cap[1].parse().unwrap_or(0);
            let severity = priority & 0x07;
            entry.level = Some(match severity {
                0 => LogLevel::Fatal,
                1..=3 => LogLevel::Error,
                4 => LogLevel::Warn,
                5..=6 => LogLevel::Info,
                7 => LogLevel::Debug,
                _ => LogLevel::Unknown,
            });
            remaining = &raw[cap.get(0)?.end()..];
        }

        entry.timestamp = self.extract_timestamp(remaining);
        entry.message = remaining.trim().to_string();
        Some(entry)
    }

    fn parse_common_log(&self, line_number: usize, raw: &str) -> Option<LogEntry> {
        let mut entry = self.base_entry(line_number, raw, LogFormat::CommonLog);
        let caps = COMMON_LOG_RE.get()?.captures(raw)?;

        let timestamp_str = caps.get(2)?.as_str();
        if let Ok(dt) = DateTime::parse_from_str(timestamp_str, "%d/%b/%Y:%H:%M:%S %z") {
            entry.timestamp = Some(dt.with_timezone(&Utc));
        }

        let status: u16 = caps.get(4)?.as_str().parse().unwrap_or(0);
        entry.level = Some(if status >= 500 {
            LogLevel::Error
        } else if status >= 400 {
            LogLevel::Warn
        } else {
            LogLevel::Info
        });

        entry.message = format!("{} {} {}", &caps[1], &caps[3], &caps[4]);
        entry
            .fields
            .insert("remote_addr".into(), Value::String(caps[1].to_string()));
        entry
            .fields
            .insert("request".into(), Value::String(caps[3].to_string()));
        entry
            .fields
            .insert("status".into(), Value::Number(status.into()));
        entry
            .fields
            .insert("size".into(), Value::String(caps[5].to_string()));

        Some(entry)
    }

    fn parse_logfmt(&self, line_number: usize, raw: &str) -> Option<LogEntry> {
        let mut entry = self.base_entry(line_number, raw, LogFormat::Logfmt);
        let mut fields = HashMap::new();

        for cap in LOGFMT_PAIR_RE.get()?.captures_iter(raw) {
            let key = cap.get(1)?.as_str();
            let value = cap
                .get(2)
                .or_else(|| cap.get(3))
                .map(|m| m.as_str())
                .unwrap_or("");

            let json_value = if let Ok(num) = value.parse::<i64>() {
                Value::Number(num.into())
            } else if let Ok(f) = value.parse::<f64>() {
                Value::Number(serde_json::Number::from_f64(f).unwrap())
            } else if value.eq_ignore_ascii_case("true") || value.eq_ignore_ascii_case("false") {
                Value::Bool(value.eq_ignore_ascii_case("true"))
            } else {
                Value::String(value.to_string())
            };

            fields.insert(key.to_string(), json_value);
        }

        if let Some(Value::String(level)) = fields.get("level").or_else(|| fields.get("lvl")) {
            entry.level = LogLevel::parse(level);
        } else {
            entry.level = Some(LogLevel::Unknown);
        }
        if let Some(Value::String(msg)) = fields.get("msg").or_else(|| fields.get("message")) {
            entry.message = msg.clone();
        }
        if let Some(Value::String(ts)) = fields.get("ts").or_else(|| fields.get("timestamp")) {
            entry.timestamp = DateTime::parse_from_rfc3339(ts)
                .ok()
                .map(|dt| dt.with_timezone(&Utc));
        }
        if let Some(Value::String(thread)) =
            fields.get("thread").or_else(|| fields.get("thread_id"))
        {
            entry.thread_id = Some(thread.clone());
        }
        if let Some(Value::String(corr)) = fields
            .get("correlation_id")
            .or_else(|| fields.get("request_id"))
        {
            entry.correlation_id = Some(corr.clone());
        }
        if let Some(Value::String(trace)) = fields.get("trace_id") {
            entry.trace_id = Some(trace.clone());
        }
        if let Some(Value::String(span)) = fields.get("span_id") {
            entry.span_id = Some(span.clone());
        }
        if let Some(Value::String(service)) =
            fields.get("service").or_else(|| fields.get("service_name"))
        {
            entry.service_name = Some(service.clone());
        }

        entry.fields = fields;
        Some(entry)
    }

    fn try_parse_custom(&self, line_number: usize, raw: &str, regex: &Regex) -> Option<LogEntry> {
        let caps = regex.captures(raw)?;
        let mut entry = self.base_entry(line_number, raw, LogFormat::Custom);

        entry.timestamp = caps
            .name("timestamp")
            .and_then(|m| self.parse_timestamp_flex(m.as_str()));
        entry.level = caps.name("level").and_then(|m| LogLevel::parse(m.as_str()));
        entry.thread_id = caps
            .name("thread")
            .or_else(|| caps.name("thread_id"))
            .map(|m| m.as_str().to_string());
        entry.correlation_id = caps
            .name("correlation_id")
            .or_else(|| caps.name("request_id"))
            .map(|m| m.as_str().to_string());
        entry.trace_id = caps.name("trace_id").map(|m| m.as_str().to_string());
        entry.span_id = caps.name("span_id").map(|m| m.as_str().to_string());
        entry.parent_span_id = caps.name("parent_span_id").map(|m| m.as_str().to_string());
        entry.service_name = caps
            .name("service")
            .or_else(|| caps.name("service_name"))
            .map(|m| m.as_str().to_string());

        if let Some(msg) = caps.name("message").or_else(|| caps.name("msg")) {
            entry.message = msg.as_str().to_string();
        }

        Some(entry)
    }

    fn parse_timestamp_flex(&self, value: &str) -> Option<DateTime<Utc>> {
        if let Ok(dt) = DateTime::parse_from_rfc3339(value) {
            return Some(dt.with_timezone(&Utc));
        }
        if let Ok(dt) = chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%d %H:%M:%S") {
            return Some(DateTime::<Utc>::from_naive_utc_and_offset(dt, Utc));
        }
        if let Ok(dt) = chrono::NaiveDateTime::parse_from_str(value, "%d-%m-%Y %H:%M:%S") {
            return Some(DateTime::<Utc>::from_naive_utc_and_offset(dt, Utc));
        }
        None
    }

    fn extract_json_timestamp(
        &self,
        obj: &serde_json::Map<String, serde_json::Value>,
    ) -> Option<DateTime<Utc>> {
        for field in &["timestamp", "time", "@timestamp", "ts"] {
            if let Some(value) = obj.get(*field) {
                if let Some(s) = value.as_str() {
                    if let Ok(dt) = DateTime::parse_from_rfc3339(s) {
                        return Some(dt.with_timezone(&Utc));
                    }
                } else if let Some(ts_num) = value.as_i64() {
                    if let Some(dt) = DateTime::from_timestamp(ts_num, 0) {
                        return Some(dt);
                    }
                }
            }
        }
        None
    }

    fn extract_json_level(
        &self,
        obj: &serde_json::Map<String, serde_json::Value>,
    ) -> Option<LogLevel> {
        for field in &["level", "severity", "log_level"] {
            if let Some(value) = obj.get(*field) {
                if let Some(s) = value.as_str() {
                    return LogLevel::parse(s);
                }
            }
        }
        None
    }

    fn extract_json_message(&self, obj: &serde_json::Map<String, serde_json::Value>) -> String {
        for field in &["message", "msg", "text"] {
            if let Some(value) = obj.get(*field) {
                if let Some(s) = value.as_str() {
                    return s.to_string();
                }
            }
        }
        serde_json::to_string(obj).unwrap_or_default()
    }

    fn extract_json_field(
        &self,
        obj: &serde_json::Map<String, serde_json::Value>,
        keys: &[&str],
    ) -> Option<String> {
        for key in keys {
            if let Some(value) = obj.get(*key) {
                if let Some(s) = value.as_str() {
                    return Some(s.to_string());
                }
            }
        }
        None
    }

    fn extract_timestamp(&self, text: &str) -> Option<DateTime<Utc>> {
        let re = TIMESTAMP_RE.get()?;
        let cap = re.find(text)?;
        let ts_str = cap.as_str();

        if let Ok(dt) = DateTime::parse_from_rfc3339(ts_str) {
            return Some(dt.with_timezone(&Utc));
        }
        if let Ok(dt) = chrono::NaiveDateTime::parse_from_str(ts_str, "%Y-%m-%d %H:%M:%S") {
            return Some(DateTime::<Utc>::from_naive_utc_and_offset(dt, Utc));
        }
        if let Ok(dt) = chrono::NaiveDateTime::parse_from_str(ts_str, "%Y-%m-%dT%H:%M:%S") {
            return Some(DateTime::<Utc>::from_naive_utc_and_offset(dt, Utc));
        }

        None
    }

    fn extract_level(&self, text: &str) -> Option<LogLevel> {
        let re = LOG_LEVEL_RE.get()?;
        let cap = re.find(text)?;
        LogLevel::parse(cap.as_str())
    }

    fn extract_thread_id(&self, text: &str) -> Option<String> {
        let re = THREAD_ID_RE.get()?;
        let cap = re.captures(text)?;
        Some(cap.get(1)?.as_str().to_string())
    }

    fn extract_correlation_id(&self, text: &str) -> Option<String> {
        let re = CORRELATION_ID_RE.get()?;
        let cap = re.captures(text)?;
        Some(cap.get(1)?.as_str().to_string())
    }

    fn extract_trace_id(&self, text: &str) -> Option<String> {
        let re = TRACE_ID_RE.get()?;
        let cap = re.captures(text)?;
        Some(cap.get(1)?.as_str().to_string())
    }

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
        let parser = LogParser::new("test.log");
        let json_line = r#"{"timestamp":"2024-01-15T10:00:00Z","level":"ERROR","message":"Test error","thread_id":"worker-1"}"#;
        let entry = parser.parse_line(1, json_line).unwrap();

        assert_eq!(entry.line_number, 1);
        assert_eq!(entry.level, Some(LogLevel::Error));
        assert_eq!(entry.message, "Test error");
        assert_eq!(entry.thread_id, Some("worker-1".to_string()));
        assert_eq!(entry.format, LogFormat::Json);
    }

    #[test]
    fn test_parse_plain_text() {
        let parser = LogParser::new("test.log");
        let plain_line = "2024-01-15 10:00:00 ERROR [worker-1] Test error message";
        let entry = parser.parse_line(1, plain_line).unwrap();

        assert_eq!(entry.line_number, 1);
        assert_eq!(entry.level, Some(LogLevel::Error));
        assert!(entry.timestamp.is_some());
        assert_eq!(entry.thread_id, Some("worker-1".to_string()));
        assert_eq!(entry.format, LogFormat::PlainText);
    }

    #[test]
    fn test_parse_syslog() {
        let parser = LogParser::new("test.log");
        let line = "<14>2024-01-15T10:00:00Z host app: system rebooted";
        let entry = parser.parse_line(5, line).unwrap();

        assert_eq!(entry.format, LogFormat::Syslog);
        assert_eq!(entry.level, Some(LogLevel::Info));
        assert!(entry.timestamp.is_some());
        assert!(entry.message.contains("system rebooted"));
    }

    #[test]
    fn test_parse_common_log() {
        let parser = LogParser::new("test.log");
        let line =
            r#"127.0.0.1 - - [10/Oct/2000:13:55:36 -0700] "GET /apache.gif HTTP/1.0" 200 2326"#;
        let entry = parser.parse_line(1, line).unwrap();

        assert_eq!(entry.format, LogFormat::CommonLog);
        assert_eq!(entry.level, Some(LogLevel::Info));
        assert!(entry.timestamp.is_some());
        assert!(entry.fields.contains_key("request"));
    }

    #[test]
    fn test_parse_logfmt() {
        let parser = LogParser::new("test.log");
        let line = r#"level=info ts="2024-01-15T10:00:00Z" thread=worker-9 msg="hello world" correlation_id=req-1"#;
        let entry = parser.parse_line(2, line).unwrap();

        assert_eq!(entry.format, LogFormat::Logfmt);
        assert_eq!(entry.level, Some(LogLevel::Info));
        assert_eq!(entry.thread_id.as_deref(), Some("worker-9"));
        assert_eq!(entry.correlation_id.as_deref(), Some("req-1"));
        assert_eq!(entry.message, "hello world");
    }

    #[test]
    fn test_custom_regex() {
        let regex =
            Regex::new(r"^(?P<timestamp>[^ ]+) (?P<level>[A-Z]+) (?P<message>.+)$").unwrap();
        let parser = LogParser::with_custom_regex("test.log", regex);
        let line = "2024-01-15T10:00:00Z WARN subsystem offline";
        let entry = parser.parse_line(3, line).unwrap();

        assert_eq!(entry.format, LogFormat::Custom);
        assert_eq!(entry.level, Some(LogLevel::Warn));
        assert_eq!(entry.message, "subsystem offline");
    }

    #[test]
    fn test_invalid_json_falls_back_to_plain_with_unknown_level() {
        let parser = LogParser::new("test.log");
        let line = r#"{"timestamp": "2024-01-01"#; // malformed JSON
        let entry = parser.parse_line(10, line).unwrap();

        assert_eq!(entry.format, LogFormat::PlainText);
        assert_eq!(entry.line_number, 10);
        assert_eq!(entry.level, None);
        assert_eq!(entry.message, line);
    }

    #[test]
    fn test_logfmt_without_level_defaults_to_unknown() {
        let parser = LogParser::new("test.log");
        let line = r#"ts="2024-01-15T10:00:00Z" msg="no level set" thread=bg-worker"#;
        let entry = parser.parse_line(11, line).unwrap();

        assert_eq!(entry.format, LogFormat::Logfmt);
        assert_eq!(entry.level, Some(LogLevel::Unknown));
        assert_eq!(entry.message, "no level set");
    }

    #[test]
    fn test_syslog_priority_maps_to_error_and_keeps_body() {
        let parser = LogParser::new("test.log");
        let line = "<3>2024-01-15T10:00:00Z host app: critical failure imminent";
        let entry = parser.parse_line(12, line).unwrap();

        assert_eq!(entry.format, LogFormat::Syslog);
        assert_eq!(entry.level, Some(LogLevel::Error));
        assert!(entry.message.contains("critical failure imminent"));
    }

    #[test]
    fn test_common_log_detection_includes_status_field() {
        let parser = LogParser::new("test.log");
        let line = r#"10.0.0.1 - - [10/Oct/2000:13:55:36 -0700] "POST /submit HTTP/1.1" 503 123"#;
        let entry = parser.parse_line(13, line).unwrap();

        assert_eq!(entry.format, LogFormat::CommonLog);
        assert_eq!(entry.level, Some(LogLevel::Error));
        assert_eq!(
            entry.fields.get("status").and_then(|v| v.as_u64()),
            Some(503)
        );
    }
}
