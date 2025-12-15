use crate::parser::ParserConfig;
use crate::types::{LogEntry, LogLevel};
use dashmap::DashMap;
use rayon::prelude::*;
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

/// Line offset information for fast seeking
#[derive(Debug, Clone)]
pub struct LineOffset {
    pub line_number: usize,
    pub byte_offset: u64,
    pub length: usize,
}

/// In-memory log file index for fast searching
#[derive(Debug)]
pub struct LogIndex {
    /// File path
    pub file_path: String,
    /// Line offsets for seeking
    pub line_offsets: Vec<LineOffset>,
    /// Thread ID -> line numbers
    pub thread_index: HashMap<String, Vec<usize>>,
    /// Correlation ID -> line numbers
    pub correlation_index: HashMap<String, Vec<usize>>,
    /// Trace ID -> line numbers
    pub trace_index: HashMap<String, Vec<usize>>,
    /// Log level -> line numbers
    pub level_index: HashMap<LogLevel, Vec<usize>>,
    /// All parsed entries (optional, for small files)
    pub entries: Option<Vec<LogEntry>>,
}

impl LogIndex {
    /// Build index from a log file
    pub fn build<P: AsRef<Path>>(path: P) -> anyhow::Result<Self> {
        Self::build_with_config(path, &ParserConfig::default())
    }

    /// Build index with a custom parser configuration (e.g., custom regex).
    pub fn build_with_config<P: AsRef<Path>>(
        path: P,
        config: &ParserConfig,
    ) -> anyhow::Result<Self> {
        let path = path.as_ref();
        let file_path = path.to_string_lossy().to_string();
        let parser = config.build_for_file(file_path.clone());

        // Phase 1: Build line offsets
        let file = File::open(path)?;
        let reader = BufReader::new(file);
        let mut line_offsets = Vec::new();
        let mut byte_offset = 0u64;

        for (line_num, line_result) in reader.lines().enumerate() {
            let line = line_result?;
            let length = line.len() + 1; // +1 for newline
            line_offsets.push(LineOffset {
                line_number: line_num + 1,
                byte_offset,
                length,
            });
            byte_offset += length as u64;
        }

        // Phase 2: Parse and index (parallel)
        let file = File::open(path)?;
        let reader = BufReader::new(file);

        let entries: Vec<LogEntry> = reader
            .lines()
            .enumerate()
            .par_bridge()
            .filter_map(|(line_num, line_result)| {
                let line = line_result.ok()?;
                parser.parse_line(line_num + 1, &line).ok()
            })
            .collect();

        // Phase 3: Build indices
        let thread_index = DashMap::new();
        let correlation_index = DashMap::new();
        let trace_index = DashMap::new();
        let level_index = DashMap::new();

        entries.par_iter().for_each(|entry| {
            if let Some(ref thread_id) = entry.thread_id {
                thread_index
                    .entry(thread_id.clone())
                    .or_insert_with(Vec::new)
                    .push(entry.line_number);
            }
            if let Some(ref correlation_id) = entry.correlation_id {
                correlation_index
                    .entry(correlation_id.clone())
                    .or_insert_with(Vec::new)
                    .push(entry.line_number);
            }
            if let Some(ref trace_id) = entry.trace_id {
                trace_index
                    .entry(trace_id.clone())
                    .or_insert_with(Vec::new)
                    .push(entry.line_number);
            }
            if let Some(level) = entry.level {
                level_index
                    .entry(level)
                    .or_insert_with(Vec::new)
                    .push(entry.line_number);
            }
        });

        Ok(Self {
            file_path,
            line_offsets,
            thread_index: thread_index.into_iter().collect(),
            correlation_index: correlation_index.into_iter().collect(),
            trace_index: trace_index.into_iter().collect(),
            level_index: level_index.into_iter().collect(),
            entries: Some(entries),
        })
    }

    /// Get entry by line number
    pub fn get_entry(&self, line_number: usize) -> Option<&LogEntry> {
        self.entries
            .as_ref()?
            .iter()
            .find(|e| e.line_number == line_number)
    }

    /// Get entries by line numbers
    pub fn get_entries(&self, line_numbers: &[usize]) -> Vec<LogEntry> {
        if let Some(entries) = &self.entries {
            line_numbers
                .iter()
                .filter_map(|ln| entries.iter().find(|e| e.line_number == *ln).cloned())
                .collect()
        } else {
            Vec::new()
        }
    }

    /// Get all entries for a thread
    pub fn get_thread_entries(&self, thread_id: &str) -> Vec<LogEntry> {
        if let Some(line_numbers) = self.thread_index.get(thread_id) {
            self.get_entries(line_numbers)
        } else {
            Vec::new()
        }
    }

    /// Get all entries for a correlation ID
    pub fn get_correlation_entries(&self, correlation_id: &str) -> Vec<LogEntry> {
        if let Some(line_numbers) = self.correlation_index.get(correlation_id) {
            self.get_entries(line_numbers)
        } else {
            Vec::new()
        }
    }

    /// Get all entries for a trace ID
    pub fn get_trace_entries(&self, trace_id: &str) -> Vec<LogEntry> {
        if let Some(line_numbers) = self.trace_index.get(trace_id) {
            self.get_entries(line_numbers)
        } else {
            Vec::new()
        }
    }

    /// Get all entries for a log level
    pub fn get_level_entries(&self, level: LogLevel) -> Vec<LogEntry> {
        if let Some(line_numbers) = self.level_index.get(&level) {
            self.get_entries(line_numbers)
        } else {
            Vec::new()
        }
    }

    /// Get context around a line number
    pub fn get_context(
        &self,
        line_number: usize,
        before: usize,
        after: usize,
    ) -> (Vec<LogEntry>, Vec<LogEntry>) {
        let entries = match &self.entries {
            Some(e) => e,
            None => return (Vec::new(), Vec::new()),
        };

        let start_line = line_number.saturating_sub(before);
        let end_line = line_number + after;

        let before_entries: Vec<LogEntry> = entries
            .iter()
            .filter(|e| e.line_number >= start_line && e.line_number < line_number)
            .cloned()
            .collect();

        let after_entries: Vec<LogEntry> = entries
            .iter()
            .filter(|e| e.line_number > line_number && e.line_number <= end_line)
            .cloned()
            .collect();

        (before_entries, after_entries)
    }

    /// Search entries matching a query string
    pub fn search(&self, query: &str, case_sensitive: bool) -> Vec<LogEntry> {
        let entries = match &self.entries {
            Some(e) => e,
            None => return Vec::new(),
        };

        if case_sensitive {
            entries
                .par_iter()
                .filter(|e| e.raw.contains(query) || e.message.contains(query))
                .cloned()
                .collect()
        } else {
            let query_lower = query.to_lowercase();
            entries
                .par_iter()
                .filter(|e| {
                    e.raw.to_lowercase().contains(&query_lower)
                        || e.message.to_lowercase().contains(&query_lower)
                })
                .cloned()
                .collect()
        }
    }

    /// Get statistics about the indexed file
    pub fn get_stats(&self) -> IndexStats {
        let empty_vec = Vec::new();
        let entries = self.entries.as_ref().unwrap_or(&empty_vec);

        IndexStats {
            total_lines: self.line_offsets.len(),
            total_entries: entries.len(),
            unique_threads: self.thread_index.len(),
            unique_correlations: self.correlation_index.len(),
            unique_traces: self.trace_index.len(),
            level_counts: self
                .level_index
                .iter()
                .map(|(k, v)| (*k, v.len()))
                .collect(),
        }
    }
}

/// Statistics about an indexed log file
#[derive(Debug, Clone)]
pub struct IndexStats {
    pub total_lines: usize,
    pub total_entries: usize,
    pub unique_threads: usize,
    pub unique_correlations: usize,
    pub unique_traces: usize,
    pub level_counts: HashMap<LogLevel, usize>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn test_build_index() {
        let mut temp_file = NamedTempFile::new().unwrap();
        writeln!(temp_file, r#"{{"timestamp":"2024-01-15T10:00:00Z","level":"ERROR","message":"Test","thread_id":"worker-1"}}"#).unwrap();
        writeln!(temp_file, r#"{{"timestamp":"2024-01-15T10:00:01Z","level":"INFO","message":"Test2","thread_id":"worker-1"}}"#).unwrap();
        temp_file.flush().unwrap();

        let index = LogIndex::build(temp_file.path()).unwrap();

        assert_eq!(index.line_offsets.len(), 2);
        assert_eq!(index.thread_index.get("worker-1").unwrap().len(), 2);

        let stats = index.get_stats();
        assert_eq!(stats.total_lines, 2);
        assert_eq!(stats.unique_threads, 1);
    }
}
