use crate::types::{LogEntry, LogLevel};
use chrono::{DateTime, Utc};
use regex::Regex;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogFilter {
    pub levels: Option<Vec<LogLevel>>,
    pub pattern: Option<String>,
    pub regex: Option<String>,
    pub thread_id: Option<String>,
    pub correlation_id: Option<String>,
    pub trace_id: Option<String>,
    pub service_name: Option<String>,
    pub time_start: Option<DateTime<Utc>>,
    pub time_end: Option<DateTime<Utc>>,
}

impl LogFilter {
    pub fn new() -> Self {
        Self {
            levels: None,
            pattern: None,
            regex: None,
            thread_id: None,
            correlation_id: None,
            trace_id: None,
            service_name: None,
            time_start: None,
            time_end: None,
        }
    }

    pub fn matches(&self, entry: &LogEntry) -> bool {
        // Filter by log level
        if let Some(ref levels) = self.levels {
            match entry.level {
                Some(level) if levels.contains(&level) => {}
                _ => return false,
            }
        }

        // Filter by pattern (case-insensitive substring)
        if let Some(ref pattern) = self.pattern {
            let pattern_lower = pattern.to_lowercase();
            let msg = entry.message.to_lowercase();
            let raw = entry.raw.to_lowercase();
            if !msg.contains(&pattern_lower) && !raw.contains(&pattern_lower) {
                return false;
            }
        }

        // Filter by regex
        if let Some(ref regex_str) = self.regex {
            if let Ok(regex) = Regex::new(regex_str) {
                if !regex.is_match(&entry.message) && !regex.is_match(&entry.raw) {
                    return false;
                }
            }
        }

        // Filter by thread ID
        if let Some(ref thread_id) = self.thread_id {
            if entry.thread_id.as_ref() != Some(thread_id) {
                return false;
            }
        }

        // Filter by correlation ID
        if let Some(ref correlation_id) = self.correlation_id {
            if entry.correlation_id.as_ref() != Some(correlation_id) {
                return false;
            }
        }

        // Filter by trace ID
        if let Some(ref trace_id) = self.trace_id {
            if entry.trace_id.as_ref() != Some(trace_id) {
                return false;
            }
        }

        // Filter by service name
        if let Some(ref service_name) = self.service_name {
            if entry.service_name.as_ref() != Some(service_name) {
                return false;
            }
        }

        // Filter by time range
        if let Some(timestamp) = entry.timestamp {
            if let Some(start) = self.time_start {
                if timestamp < start {
                    return false;
                }
            }
            if let Some(end) = self.time_end {
                if timestamp > end {
                    return false;
                }
            }
        }

        true
    }
}

impl Default for LogFilter {
    fn default() -> Self {
        Self::new()
    }
}
