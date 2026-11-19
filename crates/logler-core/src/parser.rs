use crate::types::{LogEntry, LogFormat, LogLevel};
use chrono::{DateTime, FixedOffset, NaiveDate, NaiveDateTime, TimeZone, Utc};
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
static BSD_SYSLOG_RE: OnceLock<Regex> = OnceLock::new();

/// A timestamp inside a line: date, `T` or space, time, an optional `.` or `,` fraction and an
/// optional zone. `read_timestamp` reads what this finds.
const TIMESTAMP_PATTERN: &str =
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?";

// One list of keys per field, read by the JSON and the logfmt branch; the first key present wins.
const TIMESTAMP_KEYS: &[&str] = &["timestamp", "time", "@timestamp", "ts", "datetime"];
const LEVEL_KEYS: &[&str] = &["level", "severity", "log_level", "loglevel", "lvl"];
const MESSAGE_KEYS: &[&str] = &["message", "msg", "text", "content"];
const THREAD_KEYS: &[&str] = &[
    "thread",
    "thread_id",
    "tid",
    "threadId",
    "thread_name",
    "threadName",
];
const CORRELATION_KEYS: &[&str] = &[
    "correlation_id",
    "correlationId",
    "request_id",
    "requestId",
    "req_id",
];
const TRACE_KEYS: &[&str] = &["trace_id", "traceId"];
const SPAN_KEYS: &[&str] = &["span_id", "spanId"];
const PARENT_SPAN_KEYS: &[&str] = &["parent_span_id", "parentSpanId"];
const SERVICE_KEYS: &[&str] = &["service", "service_name", "serviceName"];

/// The first key of `keys` for which `read` gives a value.
fn first_by<T>(keys: &[&str], read: impl Fn(&str) -> Option<T>) -> Option<T> {
    keys.iter().find_map(|key| read(key))
}

/// Like `first_by`, and the key that gave the value is noted in `taken`.
fn take_first<'k, T>(
    keys: &[&'k str],
    taken: &mut Vec<&'k str>,
    read: impl Fn(&str) -> Option<T>,
) -> Option<T> {
    keys.iter().find_map(|key| {
        let value = read(key)?;
        taken.push(key);
        Some(value)
    })
}

/// A Unix time given as a JSON number. Its size tells the unit: seconds stay below 1e11
/// (the year 5138), then milliseconds, microseconds and nanoseconds, each a thousand times
/// larger. A number with a fraction is kept to the microsecond.
fn epoch_timestamp(number: &serde_json::Number) -> Option<DateTime<Utc>> {
    let per_second = |size: f64| match size {
        s if s < 1e11 => 1_i64,
        s if s < 1e14 => 1_000,
        s if s < 1e17 => 1_000_000,
        _ => 1_000_000_000,
    };
    if let Some(whole) = number.as_i64() {
        let units = per_second(whole.unsigned_abs() as f64);
        let nanos = whole.rem_euclid(units) * (1_000_000_000 / units);
        return DateTime::from_timestamp(whole.div_euclid(units), nanos as u32);
    }
    let value = number.as_f64()?;
    let micros = (value / per_second(value.abs()) as f64 * 1e6).round();
    // `as` saturates, and chrono refuses what lies past its last year.
    DateTime::from_timestamp_micros(micros as i64)
}

/// A run of ASCII digits as a number; `None` when any byte is something else.
fn number(digits: &[u8]) -> Option<u32> {
    digits.iter().try_fold(0u32, |sum, byte| {
        byte.is_ascii_digit()
            .then(|| sum * 10 + u32::from(byte - b'0'))
    })
}

/// The one reader of a timestamp string: `YYYY-MM-DD`, `T` or a space, `HH:MM:SS`, an optional
/// fraction after `.` or `,`, and an optional zone (`Z`, `+09:00`, `+0900`). No zone is read
/// as UTC. The shape is fixed, so it is read by position, in one pass and without a format
/// string; anything left over after the zone makes it no timestamp.
fn read_timestamp(text: &str) -> Option<DateTime<Utc>> {
    let (head, mut rest) = text.trim().as_bytes().split_at_checked(19)?;
    let marks = (head[4], head[7], head[10], head[13], head[16]);
    if !matches!(marks, (b'-', b'-', b'T' | b't' | b' ', b':', b':')) {
        return None;
    }
    let part = |from: usize, to: usize| number(&head[from..to]);
    let date = NaiveDate::from_ymd_opt(part(0, 4)? as i32, part(5, 7)?, part(8, 10)?)?;
    let (hour, minute, second) = (part(11, 13)?, part(14, 16)?, part(17, 19)?);

    let mut nanos = 0;
    if let [b'.' | b',', fraction @ ..] = rest {
        let count = fraction.iter().take_while(|b| b.is_ascii_digit()).count();
        // Nine digits make a nanosecond; digits past the ninth are dropped.
        let kept = &fraction[..count.min(9)];
        if kept.is_empty() {
            return None;
        }
        nanos = number(kept)? * 10u32.pow(9 - kept.len() as u32);
        rest = &fraction[count..];
    }
    // chrono keeps a leap second (`:60`) as second 59 with one more second of nanoseconds.
    let (second, nanos) = match second {
        60 => (59, nanos + 1_000_000_000),
        _ => (second, nanos),
    };
    let local = date.and_hms_nano_opt(hour, minute, second, nanos)?;

    let east = match rest.trim_ascii_start() {
        [] | [b'Z' | b'z'] => 0,
        [sign @ (b'+' | b'-'), h1, h2, b':', m1, m2] | [sign @ (b'+' | b'-'), h1, h2, m1, m2] => {
            let (hours, minutes) = (number(&[*h1, *h2])?, number(&[*m1, *m2])?);
            if minutes > 59 {
                return None;
            }
            let seconds = (hours * 3600 + minutes * 60) as i32;
            if *sign == b'-' {
                -seconds
            } else {
                seconds
            }
        }
        _ => return None,
    };
    let zone = FixedOffset::east_opt(east)?;
    Some(
        zone.from_local_datetime(&local)
            .single()?
            .with_timezone(&Utc),
    )
}

/// The letters a line starts with, when a word ends there (no digit or `_` runs on).
fn leading_word(text: &str) -> Option<&str> {
    let end = text
        .find(|c: char| !c.is_ascii_alphabetic())
        .unwrap_or(text.len());
    let runs_on = text[end..]
        .chars()
        .next()
        .is_some_and(|c| c.is_alphanumeric() || c == '_');
    (end > 0 && !runs_on).then(|| &text[..end])
}

/// A level word at the head of a line, in any letter case: the first word after a timestamp
/// that starts the line, bare or in square brackets (`2024-01-15 10:00:00 warn ...`,
/// `[2024-01-15 10:00:00] warn ...`; spaces, `-`, `|` or `:` may stand between), or the
/// first word of the line when a colon follows it (`error: disk full`).
/// `timestamp` is the first timestamp of `text`, as `find_timestamp` gives it.
fn head_level(text: &str, timestamp: Option<&regex::Match>) -> Option<LogLevel> {
    let lead = text.len() - text.trim_start().len();
    let leads = |found: &&regex::Match| {
        let rest = &text[lead..found.start()];
        rest.is_empty() || (rest == "[" && text[found.end()..].starts_with(']'))
    };
    if let Some(timestamp) = timestamp.filter(leads) {
        let rest = &text[timestamp.end()..];
        let word = rest.trim_start_matches(|c: char| c.is_whitespace() || "]-|:".contains(c));
        if word.len() == rest.len() {
            return None;
        }
        return LogLevel::from_word(leading_word(word)?);
    }
    let text = &text[lead..];
    let word = leading_word(text)?;
    text[word.len()..]
        .starts_with(':')
        .then(|| LogLevel::from_word(word))?
}

/// The first level word that stands alone in square brackets, in any letter case: `[info]`.
/// Only the few bytes after each `[` are read, so a line of many brackets costs one pass.
fn bracket_level(text: &str) -> Option<LogLevel> {
    text.match_indices('[').find_map(|(open, _)| {
        let inner = &text.as_bytes()[open + 1..];
        let close = inner
            .iter()
            .take(LogLevel::LONGEST_WORD + 1)
            .position(|b| !b.is_ascii_alphabetic())?;
        (inner[close] == b']').then(|| LogLevel::from_word(&text[open + 1..open + 1 + close]))?
    })
}

/// The first timestamp in a text. One search serves both the timestamp and the level.
fn find_timestamp(text: &str) -> Option<regex::Match<'_>> {
    TIMESTAMP_RE.get()?.find(text)
}

fn init_regexes() {
    TIMESTAMP_RE.get_or_init(|| Regex::new(TIMESTAMP_PATTERN).unwrap());
    // A level word in capitals, anywhere in the line; the words come from the one table in
    // `types.rs`. The places where a word counts in any letter case are in `extract_level`.
    // This function runs for every line, so the pattern is built inside the closure.
    LOG_LEVEL_RE
        .get_or_init(|| Regex::new(&format!(r"\b(?:{})\b", LogLevel::words_pattern())).unwrap());
    THREAD_ID_RE.get_or_init(|| {
        Regex::new(concat!(
            r"(?:",
            // thread_id=xxx, thread=xxx, tid=xxx formats
            r"(?:thread[_-]?(?:id)?|tid)[=:\s]+([a-zA-Z0-9_.-]+)",
            r"|",
            // [thread-name] bracketed format (with optional -thread-N suffix)
            r"\[([a-zA-Z0-9_.-]+(?:-thread-\d+)?)\]",
            r"|",
            // Java thread pool patterns: pool-1-thread-1
            r"\b(pool-\d+-thread-\d+)\b",
            r"|",
            // Python ThreadPoolExecutor patterns: ThreadPoolExecutor-0_0
            r"\b(ThreadPoolExecutor-\d+_\d+)\b",
            r"|",
            // Common thread name patterns: MainThread, WorkerThread-1
            r"\b((?:Main|Worker)Thread(?:-\d+)?)\b",
            r")"
        ))
        .unwrap()
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
    BSD_SYSLOG_RE.get_or_init(|| {
        Regex::new(r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+\S+(?:\[\d+\])?:")
            .unwrap()
    });
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
        if BSD_SYSLOG_RE.get().unwrap().is_match(trimmed) {
            return LogFormat::Syslog;
        }
        if COMMON_LOG_RE.get().unwrap().is_match(trimmed) {
            return LogFormat::CommonLog;
        }
        let logfmt_matches = LOGFMT_PAIR_RE
            .get()
            .unwrap()
            .find_iter(trimmed)
            .take(2)
            .count();
        if logfmt_matches >= 2 {
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

        // The keys read into an entry field. Every other key stays in `fields`, a listed key
        // whose value could not be read (`"level": 30`, a second message key) among them.
        let mut taken: Vec<&str> = Vec::new();
        entry.timestamp = take_first(TIMESTAMP_KEYS, &mut taken, |key| match obj.get(key)? {
            Value::String(text) => read_timestamp(text),
            Value::Number(number) => epoch_timestamp(number),
            _ => None,
        });
        entry.level = take_first(LEVEL_KEYS, &mut taken, |key| {
            obj.get(key)?.as_str().and_then(LogLevel::parse)
        });
        entry.message = take_first(MESSAGE_KEYS, &mut taken, |key| {
            obj.get(key)?.as_str().map(String::from)
        })
        .unwrap_or_else(|| serde_json::to_string(obj).unwrap_or_default());
        let mut id = |keys: &[&'static str]| {
            take_first(keys, &mut taken, |key| match obj.get(key)? {
                Value::String(text) => Some(text.clone()),
                Value::Number(number) => Some(number.to_string()),
                _ => None,
            })
        };
        entry.thread_id = id(THREAD_KEYS);
        entry.correlation_id = id(CORRELATION_KEYS);
        entry.trace_id = id(TRACE_KEYS);
        entry.span_id = id(SPAN_KEYS);
        entry.parent_span_id = id(PARENT_SPAN_KEYS);
        entry.service_name = id(SERVICE_KEYS);

        for (key, value) in obj.iter() {
            if !taken.contains(&key.as_str()) {
                entry.fields.insert(key.clone(), value.clone());
            }
        }

        Some(entry)
    }

    fn parse_plain(&self, line_number: usize, raw: &str) -> LogEntry {
        let mut entry = self.base_entry(line_number, raw, LogFormat::PlainText);

        let timestamp = find_timestamp(raw);
        entry.timestamp = timestamp.and_then(|found| read_timestamp(found.as_str()));
        entry.level = self.extract_level(raw, timestamp.as_ref());
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

        let timestamp = find_timestamp(remaining);
        // Keyword fallback for syslog without priority prefix
        if entry.level.is_none() {
            entry.level = self.extract_level(remaining, timestamp.as_ref());
        }
        // Pattern-based inference for common syslog messages
        if entry.level.is_none() {
            entry.level = Self::infer_syslog_level(remaining);
        }

        entry.timestamp = timestamp.and_then(|found| read_timestamp(found.as_str()));
        entry.message = remaining.trim().to_string();
        Some(entry)
    }

    fn infer_syslog_level(text: &str) -> Option<LogLevel> {
        let lower = text.to_lowercase();

        // Fatal patterns
        if lower.contains("out of memory")
            || lower.contains("kill process")
            || lower.contains("segfault")
            || lower.contains("kernel panic")
            || lower.contains("oom-killer")
        {
            return Some(LogLevel::Fatal);
        }

        // Error patterns
        if lower.contains("failed password")
            || lower.contains("authentication failure")
            || lower.contains("invalid user")
            || lower.contains("connection refused")
            || lower.contains("permission denied")
            || lower.contains("not allowed")
            || lower.contains("fatal:")
            || lower.contains("error:")
            || lower.contains("failed to")
            || lower.contains("unable to")
            || lower.contains("timed out")
            || lower.contains("timeout")
        {
            return Some(LogLevel::Error);
        }

        // Warn patterns
        if lower.contains("warning:")
            || lower.contains("rate limit")
            || lower.contains("stopping")
            || lower.contains("deprecated")
            || lower.contains("retry")
        {
            return Some(LogLevel::Warn);
        }

        // Info patterns (common success/operational messages)
        if lower.contains("accepted")
            || lower.contains("session opened")
            || lower.contains("session closed")
            || lower.contains("started")
            || lower.contains("mounted")
            || lower.contains("received signal")
            || lower.contains("listening on")
            || lower.contains(") cmd")
        {
            return Some(LogLevel::Info);
        }

        None
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
        // Each value as written in the line: an id is that text, not the number it parses to.
        let mut texts: Vec<(&str, &str)> = Vec::new();

        for cap in LOGFMT_PAIR_RE.get()?.captures_iter(raw) {
            let key = cap.get(1)?.as_str();
            let value = cap
                .get(2)
                .or_else(|| cap.get(3))
                .map(|m| m.as_str())
                .unwrap_or("");

            let json_value = if let Ok(num) = value.parse::<i64>() {
                Value::Number(num.into())
            } else if let Some(num) = value
                .parse::<f64>()
                .ok()
                .and_then(serde_json::Number::from_f64)
            {
                // from_f64 is None for NaN and the infinities ("nan", "inf", "1e999"): JSON
                // has no such number, so those values fall through and stay text.
                Value::Number(num)
            } else if value.eq_ignore_ascii_case("true") || value.eq_ignore_ascii_case("false") {
                Value::Bool(value.eq_ignore_ascii_case("true"))
            } else {
                Value::String(value.to_string())
            };

            texts.push((key, value));
            fields.insert(key.to_string(), json_value);
        }

        // Many logfmt lines lead with a bare timestamp and level before the pairs
        // ("2024-01-15T15:00:00Z INFO service=api ..."). Those leading words are read when
        // no key names the value; a word inside a pair's value never is.
        let prefix = LOGFMT_PAIR_RE
            .get()?
            .find(raw)
            .map_or("", |first_pair| &raw[..first_pair.start()]);

        // A key written twice keeps its last value, as `fields` does.
        let written = |key: &str| {
            texts
                .iter()
                .rev()
                .find(|(name, _)| *name == key)
                .map(|(_, value)| *value)
        };
        let text = |keys: &[&str]| first_by(keys, |key| written(key).map(String::from));
        let lead = find_timestamp(prefix);
        entry.level = first_by(LEVEL_KEYS, |key| written(key).and_then(LogLevel::from_word))
            .or_else(|| self.extract_level(prefix, lead.as_ref()))
            .or(Some(LogLevel::Unknown));
        if let Some(message) = text(MESSAGE_KEYS) {
            entry.message = message;
        }
        entry.timestamp = first_by(TIMESTAMP_KEYS, |key| written(key).and_then(read_timestamp))
            .or_else(|| lead.and_then(|found| read_timestamp(found.as_str())));
        entry.thread_id = text(THREAD_KEYS).or_else(|| self.extract_thread_id(prefix));
        entry.correlation_id = text(CORRELATION_KEYS);
        entry.trace_id = text(TRACE_KEYS);
        entry.span_id = text(SPAN_KEYS);
        entry.parent_span_id = text(PARENT_SPAN_KEYS);
        entry.service_name = text(SERVICE_KEYS);

        entry.fields = fields;
        Some(entry)
    }

    /// A line read by the user's regex. Every named group is read the way the JSON branch reads
    /// a string value: a group named by one of the key lists fills that field (first key
    /// present wins); every other group that took part in the match, and a listed group whose
    /// value was not read, goes into `fields` as captured.
    fn try_parse_custom(&self, line_number: usize, raw: &str, regex: &Regex) -> Option<LogEntry> {
        let caps = regex.captures(raw)?;
        let mut entry = self.base_entry(line_number, raw, LogFormat::Custom);

        let mut taken: Vec<&str> = Vec::new();
        let group = |key: &str| caps.name(key).map(|m| m.as_str());
        entry.timestamp = take_first(TIMESTAMP_KEYS, &mut taken, |key| {
            self.parse_custom_timestamp(group(key)?)
        });
        entry.level = take_first(LEVEL_KEYS, &mut taken, |key| LogLevel::parse(group(key)?));
        if let Some(message) =
            take_first(MESSAGE_KEYS, &mut taken, |key| group(key).map(String::from))
        {
            entry.message = message;
        }
        let mut id = |keys: &[&'static str]| {
            take_first(keys, &mut taken, |key| group(key).map(String::from))
        };
        entry.thread_id = id(THREAD_KEYS);
        entry.correlation_id = id(CORRELATION_KEYS);
        entry.trace_id = id(TRACE_KEYS);
        entry.span_id = id(SPAN_KEYS);
        entry.parent_span_id = id(PARENT_SPAN_KEYS);
        entry.service_name = id(SERVICE_KEYS);

        for name in regex.capture_names().flatten() {
            if taken.contains(&name) {
                continue;
            }
            if let Some(value) = group(name) {
                entry
                    .fields
                    .insert(name.to_string(), Value::String(value.to_string()));
            }
        }

        Some(entry)
    }

    /// The shared reader, then the looser forms only a custom format's capture may hold:
    /// fields written without a leading zero (`2024-1-5 1:02:03`), or the day first.
    fn parse_custom_timestamp(&self, value: &str) -> Option<DateTime<Utc>> {
        read_timestamp(value).or_else(|| {
            ["%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"]
                .iter()
                .find_map(|format| NaiveDateTime::parse_from_str(value, format).ok())
                .map(|dt| DateTime::<Utc>::from_naive_utc_and_offset(dt, Utc))
        })
    }

    /// The leftmost level word in a place where one counts. In capitals a word counts
    /// anywhere. In any letter case it counts at the head of the line (`head_level`) and alone
    /// in square brackets (`bracket_level`); a lower-case word inside a sentence does not.
    /// `timestamp` is the first timestamp of `text`, as `find_timestamp` gives it.
    fn extract_level(&self, text: &str, timestamp: Option<&regex::Match>) -> Option<LogLevel> {
        if let Some(level) = head_level(text, timestamp) {
            return Some(level);
        }
        let capital = LOG_LEVEL_RE.get()?.find(text);
        let end = capital.map_or(text.len(), |word| word.start());
        bracket_level(&text[..end])
            .or_else(|| capital.and_then(|word| LogLevel::from_word(word.as_str())))
    }

    fn extract_thread_id(&self, text: &str) -> Option<String> {
        let re = THREAD_ID_RE.get()?;
        for cap in re.captures_iter(text) {
            // Check all capture groups (1-5) since we have multiple alternations
            for i in 1..=5 {
                if let Some(m) = cap.get(i) {
                    // Group 2 is `[name]`: a level word in brackets is the level, not a thread.
                    if i == 2 && LogLevel::from_word(m.as_str()).is_some() {
                        break;
                    }
                    return Some(m.as_str().to_string());
                }
            }
        }
        None
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
    fn test_logfmt_after_a_leading_timestamp_and_level_keeps_both() {
        // A common shape: the timestamp and level come first as bare words, the rest is pairs.
        let parser = LogParser::new("test.log");
        let line =
            r#"2024-01-15T15:00:00.500Z WARN service=api thread_id=api-001 message="slow start""#;
        let entry = parser.parse_line(13, line).unwrap();

        assert_eq!(entry.format, LogFormat::Logfmt);
        assert_eq!(entry.level, Some(LogLevel::Warn));
        assert_eq!(
            entry.timestamp,
            Some(
                DateTime::parse_from_rfc3339("2024-01-15T15:00:00.500Z")
                    .unwrap()
                    .with_timezone(&Utc)
            )
        );
        assert_eq!(entry.message, "slow start");
        assert_eq!(entry.service_name.as_deref(), Some("api"));
        assert_eq!(entry.thread_id.as_deref(), Some("api-001"));
    }

    #[test]
    fn test_logfmt_level_word_inside_a_value_is_not_the_level() {
        // Only the words before the first pair can name the level; a value that happens to
        // contain "error" does not, and a level key wins over a leading word.
        let parser = LogParser::new("test.log");

        let entry = parser
            .parse_line(14, r#"service=api msg="error budget is fine" user=bob"#)
            .unwrap();
        assert_eq!(entry.format, LogFormat::Logfmt);
        assert_eq!(entry.level, Some(LogLevel::Unknown));

        let entry = parser
            .parse_line(15, r#"INFO level=error msg="disk full" host=db1"#)
            .unwrap();
        assert_eq!(entry.level, Some(LogLevel::Error));
    }

    #[test]
    fn test_logfmt_words_that_parse_as_non_finite_floats_stay_strings() {
        // "nan", "inf" and "1e999" parse as f64, but JSON has no such number. In a log line
        // they are words (user=nan), so they stay the text they were.
        let parser = LogParser::new("test.log");
        let line = "level=info msg=ok user=nan limit=inf low=-Infinity big=1e999 ratio=1.5 n=7";
        let entry = parser.parse_line(12, line).unwrap();

        assert_eq!(entry.format, LogFormat::Logfmt);
        assert_eq!(entry.level, Some(LogLevel::Info));
        for (key, word) in [
            ("user", "nan"),
            ("limit", "inf"),
            ("low", "-Infinity"),
            ("big", "1e999"),
        ] {
            assert_eq!(
                entry.fields.get(key),
                Some(&Value::String(word.to_string())),
                "field {key} should keep its text"
            );
        }
        assert_eq!(entry.fields.get("ratio"), Some(&serde_json::json!(1.5)));
        assert_eq!(entry.fields.get("n"), Some(&serde_json::json!(7)));
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
    fn test_bsd_syslog_detected_as_syslog() {
        let line =
            "Mar 15 03:00:00 host sshd[1234]: Failed password for root from 10.0.0.1 port 22";
        let format = LogParser::detect_format(line);
        assert_eq!(format, LogFormat::Syslog);
    }

    #[test]
    fn test_bsd_syslog_infers_error_level() {
        let parser = LogParser::new("test.log");
        let line =
            "Mar 15 03:00:00 host sshd[1234]: Failed password for root from 10.0.0.1 port 22";
        let entry = parser.parse_line(1, line).unwrap();

        assert_eq!(entry.format, LogFormat::Syslog);
        assert_eq!(entry.level, Some(LogLevel::Error));
        assert!(entry.message.contains("Failed password"));
    }

    #[test]
    fn test_bsd_syslog_infers_fatal_for_oom() {
        let parser = LogParser::new("test.log");
        let line = "Mar 15 03:00:00 host kernel: Out of memory: Kill process 1234 (java)";
        let entry = parser.parse_line(1, line).unwrap();

        assert_eq!(entry.format, LogFormat::Syslog);
        assert_eq!(entry.level, Some(LogLevel::Fatal));
    }

    #[test]
    fn test_bsd_syslog_infers_info_for_session() {
        let parser = LogParser::new("test.log");
        let line = "Mar 15 03:00:00 host sshd[1234]: Accepted publickey for user from 10.0.0.1";
        let entry = parser.parse_line(1, line).unwrap();

        assert_eq!(entry.format, LogFormat::Syslog);
        assert_eq!(entry.level, Some(LogLevel::Info));
    }

    #[test]
    fn test_bsd_syslog_infers_warn_for_stopping() {
        let parser = LogParser::new("test.log");
        let line = "Mar 15 03:00:00 host systemd[1]: Stopping nginx.service";
        let entry = parser.parse_line(1, line).unwrap();

        assert_eq!(entry.format, LogFormat::Syslog);
        assert_eq!(entry.level, Some(LogLevel::Warn));
    }

    #[test]
    fn test_bsd_syslog_cron_gets_info() {
        let parser = LogParser::new("test.log");
        let line = "Mar 15 03:00:00 host CRON[5678]: (root) CMD (/usr/bin/cleanup)";
        let entry = parser.parse_line(1, line).unwrap();

        assert_eq!(entry.format, LogFormat::Syslog);
        assert_eq!(entry.level, Some(LogLevel::Info));
    }

    #[test]
    fn test_infer_syslog_level_patterns() {
        // Fatal
        assert_eq!(
            LogParser::infer_syslog_level("kernel: Out of memory: Kill process 123"),
            Some(LogLevel::Fatal)
        );
        assert_eq!(
            LogParser::infer_syslog_level("kernel: segfault at 0000000"),
            Some(LogLevel::Fatal)
        );
        // Error
        assert_eq!(
            LogParser::infer_syslog_level("sshd[1]: Failed password for root"),
            Some(LogLevel::Error)
        );
        assert_eq!(
            LogParser::infer_syslog_level("sshd[1]: authentication failure; user=nobody"),
            Some(LogLevel::Error)
        );
        assert_eq!(
            LogParser::infer_syslog_level("sshd[1]: Invalid user admin from 10.0.0.1"),
            Some(LogLevel::Error)
        );
        // Warn
        assert_eq!(
            LogParser::infer_syslog_level("systemd[1]: Stopping nginx.service"),
            Some(LogLevel::Warn)
        );
        // Info
        assert_eq!(
            LogParser::infer_syslog_level("sshd[1]: Accepted publickey for user"),
            Some(LogLevel::Info)
        );
        assert_eq!(
            LogParser::infer_syslog_level("CRON[5678]: (root) CMD (/usr/bin/cleanup)"),
            Some(LogLevel::Info)
        );
        // No match
        assert_eq!(
            LogParser::infer_syslog_level("some random message with no pattern"),
            None
        );
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

    fn parse(line: &str) -> LogEntry {
        LogParser::new("test.log").parse_line(1, line).unwrap()
    }

    fn utc(s: &str) -> Option<DateTime<Utc>> {
        Some(DateTime::parse_from_rfc3339(s).unwrap().with_timezone(&Utc))
    }

    #[test]
    fn test_plain_text_level_words_and_places() {
        let rows: &[(&str, Option<LogLevel>)] = &[
            ("2024-01-01T00:00:00Z trace Message", Some(LogLevel::Trace)),
            ("2024-01-01T00:00:00Z Trace Message", Some(LogLevel::Trace)),
            ("2024-01-01T00:00:00Z warn Message", Some(LogLevel::Warn)),
            ("2024-01-01T00:00:00Z ERR Message", Some(LogLevel::Error)),
            ("2024-01-01T00:00:00Z CRIT Message", Some(LogLevel::Fatal)),
            (
                "2024-01-01T00:00:00Z INFORMATION Message",
                Some(LogLevel::Info),
            ),
            (
                "2024-01-15 10:00:00,123 error cannot open file",
                Some(LogLevel::Error),
            ),
            ("2024-01-15 10:00:00 - info - started", Some(LogLevel::Info)),
            (
                "10:30:00.123 [info] Application myapp started",
                Some(LogLevel::Info),
            ),
            (
                "2024/01/15 10:00:00 [error] 1234#0: *1 connect() failed",
                Some(LogLevel::Error),
            ),
            ("warning: unused variable", Some(LogLevel::Warn)),
            ("Something happened ERROR occurred", Some(LogLevel::Error)),
            (
                "INFORMATION about DEBUGGING the ERROR in WARNING systems",
                Some(LogLevel::Info),
            ),
            ("2024-01-01T00:00:00Z Just a message", None),
            ("Loading user info for bob", None),
            ("no error found in 3 files", None),
            ("Server returned error NXDOMAIN", None),
            ("stack trace follows", None),
            ("2024-01-01T00:00:00Z [worker-1] fetching debug info", None),
            (
                "[2024-01-15 10:00:00] error something broke",
                Some(LogLevel::Error),
            ),
            (
                "[2024-01-15T10:00:00.123Z] info: started",
                Some(LogLevel::Info),
            ),
            ("[2024-01-15 10:00:00 worker] error in a sentence", None),
            ("x 2024-01-15 10:00:00 error in a sentence", None),
        ];
        for (line, expected) in rows {
            assert_eq!(parse(line).level, *expected, "level of {line:?}");
        }
    }

    #[test]
    fn test_bracketed_level_word_is_never_the_thread_id() {
        let entry = parse("2024-01-01 10:00:00 [INFO] started");
        assert_eq!(entry.level, Some(LogLevel::Info), "level of [INFO] line");
        assert_eq!(entry.thread_id, None, "thread id of [INFO] line");

        let entry = parse("2024-01-01 10:00:00 [INFO] [worker-1] started");
        assert_eq!(entry.level, Some(LogLevel::Info), "level of two brackets");
        assert_eq!(
            entry.thread_id.as_deref(),
            Some("worker-1"),
            "thread id of two brackets"
        );
    }

    #[test]
    fn test_json_and_logfmt_read_one_list_of_keys_per_field() {
        let json_levels = [
            (r#"{"loglevel": "error", "message": "test"}"#, "loglevel"),
            (r#"{"lvl": "error", "message": "test"}"#, "lvl"),
        ];
        for (line, what) in json_levels {
            assert_eq!(parse(line).level, Some(LogLevel::Error), "level of {what}");
        }

        let entry = parse(r#"{"level": "err", "content": "disk full"}"#);
        assert_eq!(entry.level, Some(LogLevel::Error), "level of err");
        assert_eq!(entry.message, "disk full", "message from content");

        let entry = parse(r#"{"datetime": "2024-01-15T10:00:00Z", "msg": "x"}"#);
        assert_eq!(entry.timestamp, utc("2024-01-15T10:00:00Z"), "datetime key");

        let entry = parse(r#"{"requestId": "r-9", "msg": "x"}"#);
        assert_eq!(entry.correlation_id.as_deref(), Some("r-9"), "requestId");
        assert!(
            !entry.fields.contains_key("requestId"),
            "requestId must not stay in fields: {:?}",
            entry.fields
        );

        let line = r#"ts=2024-01-15T10:00:00Z severity=warning tid=api-7 requestId=r-9 msg="slow""#;
        let entry = parse(line);
        assert_eq!(entry.format, LogFormat::Logfmt, "format of logfmt row");
        assert_eq!(entry.level, Some(LogLevel::Warn), "logfmt level");
        assert_eq!(entry.thread_id.as_deref(), Some("api-7"), "logfmt thread");
        assert_eq!(
            entry.correlation_id.as_deref(),
            Some("r-9"),
            "logfmt correlation"
        );
        assert_eq!(entry.message, "slow", "logfmt message");

        let entry = parse("2024-01-15T10:00:00Z INFO time=12ms user=bob");
        assert_eq!(entry.level, Some(LogLevel::Info), "prefix level");
        assert_eq!(
            entry.timestamp,
            utc("2024-01-15T10:00:00Z"),
            "12ms is no timestamp, the prefix is read"
        );
    }

    #[test]
    fn test_an_id_that_is_a_number_is_still_an_id() {
        let entry = parse(r#"{"tid": 1234, "msg": "x"}"#);
        assert_eq!(entry.thread_id.as_deref(), Some("1234"), "json number tid");

        let entry = parse(r#"level=info thread=7 msg="x""#);
        assert_eq!(
            entry.thread_id.as_deref(),
            Some("7"),
            "logfmt number thread"
        );

        let entry = parse(r#"level=info trace_id=0012345678901234 span_id=00000042 msg="x""#);
        assert_eq!(
            entry.trace_id.as_deref(),
            Some("0012345678901234"),
            "trace id keeps its zeros"
        );
        assert_eq!(
            entry.span_id.as_deref(),
            Some("00000042"),
            "span id keeps its zeros"
        );
    }

    /// Every spelling `read_timestamp` takes names the instant chrono reads from the RFC 3339
    /// spelling of the same fields, and what chrono refuses there (month 13, 30 February,
    /// hour 24, a zone past a day) is refused in every spelling.
    #[test]
    fn test_read_timestamp_agrees_with_chrono_in_every_spelling() {
        let dates = [
            "2024-01-15",
            "2024-02-29",
            "2023-02-29",
            "2024-13-01",
            "2024-00-10",
            "2024-04-31",
            "0001-01-01",
            "9999-12-31",
        ];
        let times = [
            "00:00:00", "10:00:00", "23:59:59", "23:59:60", "10:30:60", "24:00:00", "10:60:00",
            "10:00:61",
        ];
        let fractions = ["", ".5", ".123", ".123456789", ".1234567891234"];
        let zones = [
            "Z", "+00:00", "+09:00", "-05:30", "+23:59", "+24:00", "-00:00", "+09:60",
        ];
        let (mut read, mut refused) = (0, 0);
        for date in dates {
            for time in times {
                for fraction in fractions {
                    for zone in zones {
                        let rfc3339 = format!("{date}T{time}{fraction}{zone}");
                        let expected = DateTime::parse_from_rfc3339(&rfc3339)
                            .ok()
                            .map(|dt| dt.with_timezone(&Utc));
                        match expected {
                            Some(_) => read += 1,
                            None => refused += 1,
                        }
                        let mut spellings = vec![
                            rfc3339.clone(),
                            rfc3339.replace('T', " "),
                            rfc3339.replace('T', "t"),
                            rfc3339.replace('.', ","),
                            format!("{date}T{time}{fraction}{}", zone.replace(':', "")),
                            format!("{date} {time}{fraction} {zone}"),
                            format!("  {rfc3339}  "),
                        ];
                        if zone == "Z" {
                            spellings.extend([
                                format!("{date}T{time}{fraction}"),
                                format!("{date} {time}{fraction}z"),
                            ]);
                        }
                        for spelling in spellings {
                            assert_eq!(read_timestamp(&spelling), expected, "{spelling:?}");
                        }
                    }
                }
            }
        }
        assert_eq!(
            (read, refused),
            (600, 1960),
            "how many of the table chrono reads"
        );
    }

    #[test]
    fn test_read_timestamp_refuses_any_other_shape() {
        for text in [
            "",
            "2024-01-15",
            "2024-01-15T10:00",
            "2024-01-1510:00:00",
            "2024-01-15_10:00:00",
            "2024-1-15 10:00:00",
            "2024-01-15 1:00:00",
            "24-01-15 10:00:00",
            "2024/01/15 10:00:00",
            "2024-01-15 10:00:00.",
            "2024-01-15 10:00:00.x",
            "2024-01-15 10:00:00+09",
            "2024-01-15 10:00:00+9:00",
            "2024-01-15 10:00:00+09:00x",
            "2024-01-15 10:00:00 UTC",
            "2024-01-15 10:00:00 tomorrow",
            "+024-01-15 10:00:00",
            "２０２４-01-15 10:00:00",
            "2024-01-15 10:00:00\u{3000}Z",
        ] {
            assert_eq!(read_timestamp(text), None, "{text:?}");
        }
    }

    #[test]
    fn test_one_reader_for_timestamp_strings() {
        let rows: &[(&str, &str)] = &[
            (
                r#"{"timestamp": "2024-01-15 10:00:00", "msg": "x"}"#,
                "2024-01-15T10:00:00Z",
            ),
            (
                r#"{"timestamp": "2024-01-15T10:00:00", "msg": "x"}"#,
                "2024-01-15T10:00:00Z",
            ),
            (
                r#"{"time": "2024-01-15 10:00:00,123", "msg": "x"}"#,
                "2024-01-15T10:00:00.123Z",
            ),
            (
                r#"{"ts": "2024-01-15T19:00:00+0900", "msg": "x"}"#,
                "2024-01-15T10:00:00Z",
            ),
            (
                "2024-01-15 10:00:00.123 INFO started",
                "2024-01-15T10:00:00.123Z",
            ),
            (
                "2024-01-15 10:00:00,123 INFO started",
                "2024-01-15T10:00:00.123Z",
            ),
            (
                r#"ts="2024-01-15 10:00:00" level=info msg="x""#,
                "2024-01-15T10:00:00Z",
            ),
            (
                r#"{"ts": "2024-01-15 19:00:00+09:00", "msg": "x"}"#,
                "2024-01-15T10:00:00Z",
            ),
            (
                r#"{"ts": "2024-01-15 19:00:00.250+0900", "msg": "x"}"#,
                "2024-01-15T10:00:00.250Z",
            ),
            (
                r#"{"ts": "2024-01-15 10:00:00Z", "msg": "x"}"#,
                "2024-01-15T10:00:00Z",
            ),
            (
                r#"{"ts": "2024-01-15T05:00:00.5-05:00", "msg": "x"}"#,
                "2024-01-15T10:00:00.5Z",
            ),
            (
                "2024-01-15 05:00:00-0500 INFO started",
                "2024-01-15T10:00:00Z",
            ),
        ];
        for (line, expected) in rows {
            assert_eq!(parse(line).timestamp, utc(expected), "timestamp of {line}");
        }
        for line in [
            r#"{"timestamp": "not a time", "msg": "x"}"#,
            r#"{"timestamp": "時刻ではない文字列です、ほんとうに", "msg": "x"}"#,
            r#"{"timestamp": "2024-01-15 10:00:00 tomorrow", "msg": "x"}"#,
        ] {
            assert_eq!(parse(line).timestamp, None, "no timestamp in {line}");
        }

        let regex = Regex::new(r"^(?P<timestamp>\S+ \S+) (?P<message>.*)$").unwrap();
        let custom = LogParser::with_custom_regex("test.log", regex);
        let entry = custom.parse_line(1, "15-01-2024 10:00:00 hello").unwrap();
        assert_eq!(
            entry.timestamp,
            utc("2024-01-15T10:00:00Z"),
            "custom regex keeps its day-first form"
        );
        let entry = custom.parse_line(1, "2024-01-15 10:00:00,5 hello").unwrap();
        assert_eq!(
            entry.timestamp,
            utc("2024-01-15T10:00:00.5Z"),
            "custom regex reads the shared forms"
        );
        let entry = custom.parse_line(1, "2024-1-5 1:02:03 hello").unwrap();
        assert_eq!(
            entry.timestamp,
            utc("2024-01-05T01:02:03Z"),
            "custom regex keeps fields written without a leading zero"
        );
    }

    #[test]
    fn test_logfmt_thread_in_brackets_before_the_pairs_is_read() {
        let line = "2024-01-01T00:00:00Z INFO [worker-1] correlation_id=req-123 trace_id=abcd1234abcd1234 span_id=efef5678 Database query";
        let entry = parse(line);
        assert_eq!(entry.format, LogFormat::Logfmt, "format");
        assert_eq!(entry.thread_id.as_deref(), Some("worker-1"), "thread id");
        assert_eq!(entry.level, Some(LogLevel::Info), "level");
    }

    #[test]
    fn test_json_epoch_number_is_read_in_the_unit_its_size_tells() {
        let rows: &[(&str, &str)] = &[
            (r#"{"ts": 1705312800, "msg": "x"}"#, "2024-01-15T10:00:00Z"),
            (
                r#"{"time": 1705312800123, "msg": "x"}"#,
                "2024-01-15T10:00:00.123Z",
            ),
            (
                r#"{"time": 1705312800123456, "msg": "x"}"#,
                "2024-01-15T10:00:00.123456Z",
            ),
            (
                r#"{"time": 1705312800123456789, "msg": "x"}"#,
                "2024-01-15T10:00:00.123456789Z",
            ),
            (
                r#"{"ts": 1705312800.25, "msg": "x"}"#,
                "2024-01-15T10:00:00.25Z",
            ),
            (
                r#"{"ts": 1705312800123.5, "msg": "x"}"#,
                "2024-01-15T10:00:00.1235Z",
            ),
            (r#"{"ts": 0, "msg": "x"}"#, "1970-01-01T00:00:00Z"),
            (r#"{"ts": -1, "msg": "x"}"#, "1969-12-31T23:59:59Z"),
            (r#"{"ts": -1500, "msg": "x"}"#, "1969-12-31T23:35:00Z"),
        ];
        for (line, expected) in rows {
            assert_eq!(parse(line).timestamp, utc(expected), "timestamp of {line}");
        }
        for line in [
            r#"{"ts": 1e300, "msg": "x"}"#,
            r#"{"ts": true, "msg": "x"}"#,
        ] {
            assert_eq!(parse(line).timestamp, None, "no timestamp in {line}");
        }
    }

    #[test]
    fn test_json_key_that_was_not_read_stays_in_fields() {
        let entry = parse(
            r#"{"msg": "a", "text": "b", "level": 30, "lvl": "warn", "time": "soon", "ts": 1705312800, "thread": ["x"], "tid": 7, "user": "u1"}"#,
        );
        assert_eq!(entry.message, "a", "message");
        assert_eq!(entry.level, Some(LogLevel::Warn), "level");
        assert_eq!(entry.timestamp, utc("2024-01-15T10:00:00Z"), "timestamp");
        assert_eq!(entry.thread_id.as_deref(), Some("7"), "thread id");
        let expected: HashMap<String, Value> = serde_json::from_str(
            r#"{"text": "b", "level": 30, "time": "soon", "thread": ["x"], "user": "u1"}"#,
        )
        .unwrap();
        assert_eq!(entry.fields, expected, "fields");
    }

    #[test]
    fn test_custom_regex_reads_every_named_group() {
        let plc = Regex::new(
            r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\|(?P<level>\w+)\|(?P<station>[\w-]+)\|(?P<message>.*)$",
        )
        .unwrap();
        let robot = Regex::new(r"^(?P<lvl>\w+);(?P<axis>\d+);(?P<msg>.*)$").unwrap();
        let ids = Regex::new(
            r"^(?P<request_id>\S+) (?P<threadName>\S+) (?P<level>\S+) (?P<user>\S+)?(?P<note>x)?$",
        )
        .unwrap();
        let stamped = Regex::new(r"^(?P<timestamp>\S+) (?P<message>.*)$").unwrap();
        let fields = |pairs: &[(&str, &str)]| -> HashMap<String, Value> {
            pairs
                .iter()
                .map(|(k, v)| (k.to_string(), Value::String(v.to_string())))
                .collect()
        };

        // (regex, line, format, level, timestamp, message, thread, correlation, fields)
        #[allow(clippy::type_complexity)]
        let rows: Vec<(
            &Regex,
            &str,
            LogFormat,
            Option<LogLevel>,
            Option<&str>,
            &str,
            Option<&str>,
            Option<&str>,
            HashMap<String, Value>,
        )> = vec![
            (
                &plc,
                "2024-01-15 10:00:00|warn|ST-07|pressure low",
                LogFormat::Custom,
                Some(LogLevel::Warn),
                Some("2024-01-15T10:00:00Z"),
                "pressure low",
                None,
                None,
                fields(&[("station", "ST-07")]),
            ),
            (
                &plc,
                "2024-01-15 10:00:01|error|ST-07|valve stuck",
                LogFormat::Custom,
                Some(LogLevel::Error),
                Some("2024-01-15T10:00:01Z"),
                "valve stuck",
                None,
                None,
                fields(&[("station", "ST-07")]),
            ),
            (
                &plc,
                "2024-01-15 10:00:02 INFO a plain line in a plc file",
                LogFormat::PlainText,
                Some(LogLevel::Info),
                Some("2024-01-15T10:00:02Z"),
                "2024-01-15 10:00:02 INFO a plain line in a plc file",
                None,
                None,
                HashMap::new(),
            ),
            (
                &robot,
                "error;3;overtravel",
                LogFormat::Custom,
                Some(LogLevel::Error),
                None,
                "overtravel",
                None,
                None,
                fields(&[("axis", "3")]),
            ),
            (
                &robot,
                "info;1;homed",
                LogFormat::Custom,
                Some(LogLevel::Info),
                None,
                "homed",
                None,
                None,
                fields(&[("axis", "1")]),
            ),
            (
                &ids,
                "req-9 pool-3 bogus bob",
                LogFormat::Custom,
                // A word that names no level reads as Unknown, as in the JSON branch.
                Some(LogLevel::Unknown),
                None,
                "req-9 pool-3 bogus bob",
                Some("pool-3"),
                Some("req-9"),
                // `note` did not take part in the match: it is absent.
                fields(&[("user", "bob")]),
            ),
            (
                &stamped,
                "notatime hi",
                LogFormat::Custom,
                None,
                None,
                "hi",
                None,
                None,
                // A listed group whose value could not be read is kept as captured.
                fields(&[("timestamp", "notatime")]),
            ),
        ];
        for (regex, line, format, level, timestamp, message, thread, correlation, expected) in rows
        {
            let entry = LogParser::with_custom_regex("test.log", regex.clone())
                .parse_line(1, line)
                .unwrap();
            assert_eq!(entry.format, format, "format of {line}");
            assert_eq!(entry.level, level, "level of {line}");
            assert_eq!(
                entry.timestamp,
                timestamp.and_then(utc),
                "timestamp of {line}"
            );
            assert_eq!(entry.message, message, "message of {line}");
            assert_eq!(entry.thread_id.as_deref(), thread, "thread of {line}");
            assert_eq!(
                entry.correlation_id.as_deref(),
                correlation,
                "correlation id of {line}"
            );
            assert_eq!(entry.fields, expected, "fields of {line}");
        }
    }
}
