use crate::types::{LogEntry, LogLevel};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogStats {
    pub total_count: usize,
    pub level_counts: HashMap<String, usize>,
    pub service_counts: HashMap<String, usize>,
    pub thread_counts: HashMap<String, usize>,
    pub error_rate: f64,
    pub first_timestamp: Option<DateTime<Utc>>,
    pub last_timestamp: Option<DateTime<Utc>>,
}

impl LogStats {
    pub fn new() -> Self {
        Self {
            total_count: 0,
            level_counts: HashMap::new(),
            service_counts: HashMap::new(),
            thread_counts: HashMap::new(),
            error_rate: 0.0,
            first_timestamp: None,
            last_timestamp: None,
        }
    }

    pub fn compute(entries: &[LogEntry]) -> Self {
        let mut stats = Self::new();
        stats.total_count = entries.len();

        if entries.is_empty() {
            return stats;
        }

        let mut error_count = 0;

        for entry in entries {
            // Count by level
            let level_key = entry
                .level
                .map(|l| l.as_str().to_string())
                .unwrap_or_else(|| LogLevel::Unknown.as_str().to_string());
            *stats.level_counts.entry(level_key.clone()).or_insert(0) += 1;

            if matches!(entry.level, Some(LogLevel::Error | LogLevel::Fatal)) {
                error_count += 1;
            }

            // Count by service
            if let Some(ref service) = entry.service_name {
                *stats.service_counts.entry(service.clone()).or_insert(0) += 1;
            }

            // Count by thread
            if let Some(ref thread) = entry.thread_id {
                *stats.thread_counts.entry(thread.clone()).or_insert(0) += 1;
            }

            // Track timestamps
            if let Some(timestamp) = entry.timestamp {
                if stats.first_timestamp.is_none() || stats.first_timestamp.unwrap() > timestamp {
                    stats.first_timestamp = Some(timestamp);
                }
                if stats.last_timestamp.is_none() || stats.last_timestamp.unwrap() < timestamp {
                    stats.last_timestamp = Some(timestamp);
                }
            }
        }

        stats.error_rate = if stats.total_count > 0 {
            (error_count as f64 / stats.total_count as f64) * 100.0
        } else {
            0.0
        };

        stats
    }
}

impl Default for LogStats {
    fn default() -> Self {
        Self::new()
    }
}
