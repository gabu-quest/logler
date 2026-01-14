use crate::index::LogIndex;
use crate::parser::ParserConfig;
use crate::types::*;
use chrono::{DateTime, Utc};
use rayon::prelude::*;
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::time::Instant;

/// Main investigation API for LLM agents
pub struct Investigator {
    indices: HashMap<String, LogIndex>,
}

impl Investigator {
    /// Create a new investigator
    pub fn new() -> Self {
        Self {
            indices: HashMap::new(),
        }
    }

    /// Load log files and build indices
    pub fn load_files(&mut self, files: &[PathBuf]) -> anyhow::Result<()> {
        self.load_files_with_config(files, &ParserConfig::default())
    }

    /// Load log files with a custom parser configuration (custom regex/forced format).
    pub fn load_files_with_config(
        &mut self,
        files: &[PathBuf],
        config: &ParserConfig,
    ) -> anyhow::Result<()> {
        for file in files {
            let path_str = file.to_string_lossy().to_string();
            let index = LogIndex::build_with_config(file, config)?;
            self.indices.insert(path_str, index);
        }
        Ok(())
    }

    /// Search logs with filters
    pub fn search(&self, query: &SearchQuery) -> anyhow::Result<SearchResults> {
        let start = Instant::now();
        let mut all_results = Vec::new();

        for (file_path, index) in &self.indices {
            if !query.files.is_empty() {
                let file_matches = query
                    .files
                    .iter()
                    .any(|f| f.to_string_lossy().as_ref() == file_path);
                if !file_matches {
                    continue;
                }
            }

            let entries = self.search_in_index(index, query)?;
            all_results.extend(entries);
        }

        // Sort by relevance and timestamp
        all_results.sort_by(|a, b| {
            b.relevance_score
                .partial_cmp(&a.relevance_score)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| match (&a.entry.timestamp, &b.entry.timestamp) {
                    (Some(t1), Some(t2)) => t1.cmp(t2),
                    _ => std::cmp::Ordering::Equal,
                })
        });

        let total_matches = all_results.len();
        let results = if let Some(limit) = query.limit {
            all_results.into_iter().take(limit).collect()
        } else {
            all_results
        };

        Ok(SearchResults {
            results,
            total_matches,
            search_time_ms: start.elapsed().as_millis() as u64,
        })
    }

    /// Search within a single index
    fn search_in_index(
        &self,
        index: &LogIndex,
        query: &SearchQuery,
    ) -> anyhow::Result<Vec<SearchResult>> {
        let entries = index
            .entries
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("Index has no entries loaded"))?;

        let results: Vec<SearchResult> = entries
            .par_iter()
            .filter(|entry| self.matches_filters(entry, &query.filters))
            .filter_map(|entry| {
                let score = self.calculate_relevance(entry, query);
                if score > 0.0 {
                    let (context_before, context_after) = if let Some(n) = query.context_lines {
                        index.get_context(entry.line_number, n, n)
                    } else {
                        (Vec::new(), Vec::new())
                    };

                    Some(SearchResult {
                        entry: entry.clone(),
                        context_before,
                        context_after,
                        relevance_score: score,
                    })
                } else {
                    None
                }
            })
            .collect();

        Ok(results)
    }

    /// Check if entry matches filters
    fn matches_filters(&self, entry: &LogEntry, filters: &SearchFilters) -> bool {
        // Level filter
        if !filters.levels.is_empty() {
            if let Some(level) = entry.level {
                if !filters.levels.contains(&level) {
                    return false;
                }
            } else {
                return false;
            }
        }

        // Time range filter
        if let Some(ref time_range) = filters.time_range {
            if let Some(timestamp) = entry.timestamp {
                if let Some(start) = time_range.start {
                    if timestamp < start {
                        return false;
                    }
                }
                if let Some(end) = time_range.end {
                    if timestamp > end {
                        return false;
                    }
                }
            }
        }

        // Thread ID filter
        if let Some(ref thread_id) = filters.thread_id {
            if entry.thread_id.as_ref() != Some(thread_id) {
                return false;
            }
        }

        // Correlation ID filter
        if let Some(ref correlation_id) = filters.correlation_id {
            if entry.correlation_id.as_ref() != Some(correlation_id) {
                return false;
            }
        }

        // Trace ID filter
        if let Some(ref trace_id) = filters.trace_id {
            if entry.trace_id.as_ref() != Some(trace_id) {
                return false;
            }
        }

        // Has correlation ID filter
        if let Some(has_correlation_id) = filters.has_correlation_id {
            if entry.correlation_id.is_some() != has_correlation_id {
                return false;
            }
        }

        true
    }

    /// Calculate relevance score for a log entry
    fn calculate_relevance(&self, entry: &LogEntry, query: &SearchQuery) -> f64 {
        if let Some(ref query_str) = query.query {
            let query_lower = query_str.to_lowercase();
            let message_lower = entry.message.to_lowercase();

            if message_lower.contains(&query_lower) {
                // Exact match
                if message_lower == query_lower {
                    return 1.0;
                }
                // Contains query
                return 0.7;
            }

            // Fuzzy match (simple word overlap)
            let query_words: HashSet<_> = query_lower.split_whitespace().collect();
            let message_words: HashSet<_> = message_lower.split_whitespace().collect();
            let overlap = query_words.intersection(&message_words).count();

            if overlap > 0 {
                return (overlap as f64) / (query_words.len() as f64) * 0.5;
            }

            0.0
        } else {
            // No query string, matches filters
            1.0
        }
    }

    /// Follow a thread/correlation/trace
    pub fn follow_thread(
        &self,
        files: &[PathBuf],
        thread_id: Option<String>,
        correlation_id: Option<String>,
        trace_id: Option<String>,
    ) -> anyhow::Result<ThreadTimeline> {
        let mut all_entries = Vec::new();

        for (file_path, index) in &self.indices {
            if !files.is_empty() {
                let file_matches = files
                    .iter()
                    .any(|f| f.to_string_lossy().as_ref() == file_path);
                if !file_matches {
                    continue;
                }
            }

            if let Some(ref tid) = thread_id {
                all_entries.extend(index.get_thread_entries(tid));
            }
            if let Some(ref cid) = correlation_id {
                all_entries.extend(index.get_correlation_entries(cid));
            }
            if let Some(ref tid) = trace_id {
                all_entries.extend(index.get_trace_entries(tid));
            }
        }

        // Sort by timestamp
        all_entries.sort_by(|a, b| match (&a.timestamp, &b.timestamp) {
            (Some(t1), Some(t2)) => t1.cmp(t2),
            (Some(_), None) => std::cmp::Ordering::Less,
            (None, Some(_)) => std::cmp::Ordering::Greater,
            (None, None) => a.line_number.cmp(&b.line_number),
        });

        let duration_ms = if !all_entries.is_empty() {
            if let (Some(first), Some(last)) = (
                all_entries.first().and_then(|e| e.timestamp),
                all_entries.last().and_then(|e| e.timestamp),
            ) {
                Some((last - first).num_milliseconds())
            } else {
                None
            }
        } else {
            None
        };

        let unique_spans: HashSet<String> = all_entries
            .iter()
            .filter_map(|e| e.span_id.clone())
            .collect();

        Ok(ThreadTimeline {
            total_entries: all_entries.len(),
            entries: all_entries,
            duration_ms,
            unique_spans: unique_spans.into_iter().collect(),
        })
    }

    /// Get context around a specific log entry
    pub fn get_context(
        &self,
        file: &str,
        line_number: usize,
        lines_before: usize,
        lines_after: usize,
        include_related_threads: bool,
    ) -> anyhow::Result<LogContext> {
        let index = self
            .indices
            .get(file)
            .ok_or_else(|| anyhow::anyhow!("File not indexed: {}", file))?;

        let target = index
            .get_entry(line_number)
            .ok_or_else(|| anyhow::anyhow!("Line not found: {}", line_number))?
            .clone();

        let (context_before, context_after) =
            index.get_context(line_number, lines_before, lines_after);

        let related_threads = if include_related_threads {
            let mut related = Vec::new();
            if let Some(ref thread_id) = target.thread_id {
                let entries = index.get_thread_entries(thread_id);
                if !entries.is_empty() {
                    related.push(ThreadEntries {
                        thread_id: thread_id.clone(),
                        entries,
                    });
                }
            }
            related
        } else {
            Vec::new()
        };

        Ok(LogContext {
            target,
            context_before,
            context_after,
            related_threads,
        })
    }

    /// Find patterns in logs
    pub fn find_patterns(
        &self,
        files: &[PathBuf],
        min_occurrences: usize,
    ) -> anyhow::Result<PatternResults> {
        let mut error_messages: HashMap<String, Vec<LogEntry>> = HashMap::new();

        for (file_path, index) in &self.indices {
            if !files.is_empty() {
                let file_matches = files
                    .iter()
                    .any(|f| f.to_string_lossy().as_ref() == file_path);
                if !file_matches {
                    continue;
                }
            }

            if let Some(entries) = &index.entries {
                for entry in entries {
                    if matches!(entry.level, Some(LogLevel::Error) | Some(LogLevel::Fatal)) {
                        // Group by message prefix (first 50 chars)
                        let prefix = entry.message.chars().take(50).collect::<String>();
                        error_messages
                            .entry(prefix)
                            .or_default()
                            .push(entry.clone());
                    }
                }
            }
        }

        let mut patterns = Vec::new();

        for (pattern, entries) in error_messages {
            if entries.len() >= min_occurrences {
                let first_seen = entries.iter().filter_map(|e| e.timestamp).min().unwrap();
                let last_seen = entries.iter().filter_map(|e| e.timestamp).max().unwrap();
                let affected_threads: HashSet<String> =
                    entries.iter().filter_map(|e| e.thread_id.clone()).collect();

                patterns.push(Pattern {
                    pattern_type: PatternType::RepeatedError,
                    pattern: pattern.clone(),
                    occurrences: entries.len(),
                    first_seen,
                    last_seen,
                    affected_threads: affected_threads.into_iter().collect(),
                    examples: entries.into_iter().take(5).collect(),
                });
            }
        }

        // Sort by occurrence count
        patterns.sort_by(|a, b| b.occurrences.cmp(&a.occurrences));

        Ok(PatternResults { patterns })
    }

    /// Get file metadata
    pub fn get_metadata(&self, files: &[PathBuf]) -> anyhow::Result<Vec<FileMetadata>> {
        let mut metadata = Vec::new();

        for (file_path, index) in &self.indices {
            if !files.is_empty() {
                let file_matches = files
                    .iter()
                    .any(|f| f.to_string_lossy().as_ref() == file_path);
                if !file_matches {
                    continue;
                }
            }

            let stats = index.get_stats();
            let empty_vec = Vec::new();
            let entries = index.entries.as_ref().unwrap_or(&empty_vec);

            let time_range = if !entries.is_empty() {
                let timestamps: Vec<DateTime<Utc>> =
                    entries.iter().filter_map(|e| e.timestamp).collect();
                if !timestamps.is_empty() {
                    Some(TimeRange {
                        start: timestamps.iter().min().copied(),
                        end: timestamps.iter().max().copied(),
                    })
                } else {
                    None
                }
            } else {
                None
            };

            // Detect format using the first entry
            let format = entries
                .first()
                .map(|e| crate::parser::LogParser::detect_format(&e.raw))
                .unwrap_or(LogFormat::Unknown);

            let size_bytes = std::fs::metadata(file_path).map(|m| m.len()).unwrap_or(0);

            // Get available fields
            let available_fields: HashSet<String> = entries
                .iter()
                .flat_map(|e| e.fields.keys().cloned())
                .collect();

            metadata.push(FileMetadata {
                path: file_path.clone(),
                size_bytes,
                lines: stats.total_lines,
                format,
                time_range,
                available_fields: available_fields.into_iter().collect(),
                unique_threads: stats.unique_threads,
                unique_correlation_ids: stats.unique_correlations,
                log_levels: stats
                    .level_counts
                    .iter()
                    .map(|(k, v)| (k.as_str().to_string(), *v))
                    .collect(),
            });
        }

        Ok(metadata)
    }

    /// Execute SQL query on loaded logs (requires 'sql' feature)
    #[cfg(feature = "sql")]
    pub fn sql_query(&self, query: &str) -> anyhow::Result<String> {
        use crate::sql::SqlEngine;

        let mut engine = SqlEngine::new()?;
        engine.load_files(&self.indices)?;
        engine.query(query)
    }

    /// Get available SQL tables (requires 'sql' feature)
    #[cfg(feature = "sql")]
    pub fn sql_tables(&self) -> anyhow::Result<Vec<String>> {
        use crate::sql::SqlEngine;

        let mut engine = SqlEngine::new()?;
        engine.load_files(&self.indices)?;
        engine.get_tables()
    }

    /// Get SQL table schema (requires 'sql' feature)
    #[cfg(feature = "sql")]
    pub fn sql_schema(&self, table: &str) -> anyhow::Result<String> {
        use crate::sql::SqlEngine;

        let mut engine = SqlEngine::new()?;
        engine.load_files(&self.indices)?;
        engine.get_schema(table)
    }

    /// Build hierarchical view of threads/spans for a given identifier
    pub fn build_hierarchy(
        &self,
        files: &[PathBuf],
        root_identifier: &str,
        config: Option<crate::hierarchy::HierarchyConfig>,
    ) -> anyhow::Result<crate::hierarchy::ThreadHierarchy> {
        use crate::hierarchy::HierarchyBuilder;

        let config = config.unwrap_or_default();
        let mut builder = HierarchyBuilder::new(config);

        // Collect all relevant entries from the indices
        for (file_path, index) in &self.indices {
            if !files.is_empty() {
                let file_matches = files
                    .iter()
                    .any(|f| f.to_string_lossy().as_ref() == file_path);
                if !file_matches {
                    continue;
                }
            }

            let entries = index
                .entries
                .as_ref()
                .ok_or_else(|| anyhow::anyhow!("Index has no entries loaded"))?;

            for entry in entries.iter() {
                builder.add_entry(entry.clone());
            }
        }

        // Build the hierarchy
        // Return empty hierarchy if no match found (instead of error)
        Ok(builder
            .build(root_identifier)
            .unwrap_or_else(|| crate::hierarchy::ThreadHierarchy {
                roots: vec![],
                total_nodes: 0,
                max_depth: 0,
                total_duration_ms: None,
                concurrent_count: 0,
                bottleneck: None,
                error_nodes: vec![],
                detection_method: crate::hierarchy::DetectionMethod::Explicit,
            }))
    }
}

impl Default for Investigator {
    fn default() -> Self {
        Self::new()
    }
}
