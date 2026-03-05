use crate::index::LogIndex;
use crate::parser::ParserConfig;
use crate::types::*;
use chrono::{DateTime, Utc};
use rayon::prelude::*;
use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::time::Instant;

/// Safety cap: maximum results returned when no limit/tail is specified.
/// Prevents a single unbounded query from allocating gigabytes of memory.
const DEFAULT_MAX_RESULTS: usize = 100_000;

/// Lightweight match candidate produced in the filter phase.
/// ~40 bytes per candidate vs ~2-4 KB per full SearchResult with cloned entry.
struct MatchCandidate {
    file_key: usize,
    entry_idx: usize,
    entry_line_number: usize,
    timestamp: Option<DateTime<Utc>>,
    relevance_score: f64,
}

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

    /// Search logs with filters.
    ///
    /// Uses a two-phase approach to minimize memory:
    /// - Phase 1: Filter + score → lightweight `MatchCandidate` (~40 bytes each)
    /// - Phase 2: Materialize full `SearchResult` only for the final N results
    pub fn search(&self, query: &SearchQuery) -> anyhow::Result<SearchResults> {
        let start = Instant::now();

        // Pre-compile exclude_pattern regex once
        let exclude_regex = if let Some(ref pattern) = query.filters.exclude_pattern {
            Some(
                Regex::new(pattern)
                    .map_err(|e| anyhow::anyhow!("Invalid exclude_pattern regex: {}", e))?,
            )
        } else {
            None
        };

        // Build file list for stable indexing between phases
        let file_list: Vec<(&String, &LogIndex)> = self
            .indices
            .iter()
            .filter(|(file_path, _)| {
                if query.files.is_empty() {
                    true
                } else {
                    query
                        .files
                        .iter()
                        .any(|f| f.to_string_lossy().as_ref() == *file_path)
                }
            })
            .collect();

        // Phase 1: Collect lightweight candidates (no cloning, no context fetching)
        let mut all_candidates = Vec::new();
        for (file_key, (_, index)) in file_list.iter().enumerate() {
            let candidates =
                self.collect_candidates(file_key, index, query, exclude_regex.as_ref())?;
            all_candidates.extend(candidates);
        }

        let total_matches = all_candidates.len();

        // Sort and truncate candidates before materializing
        let selected: Vec<MatchCandidate> = if let Some(tail_n) = query.tail {
            // Sort by timestamp ASC and take last N
            all_candidates.sort_by(|a, b| match (&a.timestamp, &b.timestamp) {
                (Some(t1), Some(t2)) => t1.cmp(t2),
                (Some(_), None) => std::cmp::Ordering::Less,
                (None, Some(_)) => std::cmp::Ordering::Greater,
                (None, None) => a.entry_line_number.cmp(&b.entry_line_number),
            });
            let skip = all_candidates.len().saturating_sub(tail_n);
            all_candidates.into_iter().skip(skip).collect()
        } else {
            // Sort by relevance and timestamp
            all_candidates.sort_by(|a, b| {
                b.relevance_score
                    .total_cmp(&a.relevance_score)
                    .then_with(|| match (&a.timestamp, &b.timestamp) {
                        (Some(t1), Some(t2)) => t1.cmp(t2),
                        (Some(_), None) => std::cmp::Ordering::Less,
                        (None, Some(_)) => std::cmp::Ordering::Greater,
                        (None, None) => std::cmp::Ordering::Equal,
                    })
            });
            let cap = query.limit.unwrap_or(DEFAULT_MAX_RESULTS);
            all_candidates.into_iter().take(cap).collect()
        };

        // Phase 2: Materialize only the selected candidates (clone entry + fetch context)
        let results: Vec<SearchResult> = selected
            .into_iter()
            .map(|candidate| {
                let (_, index) = file_list[candidate.file_key];
                let entries = index.entries.as_ref().unwrap();
                let entry = &entries[candidate.entry_idx];

                let (context_before, context_after) = if let Some(n) = query.context_lines {
                    index.get_context(entry.line_number, n, n)
                } else {
                    (Vec::new(), Vec::new())
                };

                SearchResult {
                    entry: entry.clone(),
                    context_before,
                    context_after,
                    relevance_score: candidate.relevance_score,
                }
            })
            .collect();

        Ok(SearchResults {
            results,
            total_matches,
            search_time_ms: start.elapsed().as_millis() as u64,
        })
    }

    /// Phase 1: Collect lightweight match candidates from a single index.
    /// Returns entry indices and scores without cloning entries or fetching context.
    fn collect_candidates(
        &self,
        file_key: usize,
        index: &LogIndex,
        query: &SearchQuery,
        exclude_regex: Option<&Regex>,
    ) -> anyhow::Result<Vec<MatchCandidate>> {
        let entries = index
            .entries
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("Index has no entries loaded"))?;

        let candidates: Vec<MatchCandidate> = entries
            .par_iter()
            .enumerate()
            .filter(|(_, entry)| self.matches_filters(entry, &query.filters, exclude_regex))
            .filter_map(|(idx, entry)| {
                let score = self.calculate_relevance(entry, query);
                if score > 0.0 {
                    Some(MatchCandidate {
                        file_key,
                        entry_idx: idx,
                        entry_line_number: entry.line_number,
                        timestamp: entry.timestamp,
                        relevance_score: score,
                    })
                } else {
                    None
                }
            })
            .collect();

        Ok(candidates)
    }

    /// Check if entry matches filters
    fn matches_filters(
        &self,
        entry: &LogEntry,
        filters: &SearchFilters,
        exclude_regex: Option<&Regex>,
    ) -> bool {
        // Level include filter
        if !filters.levels.is_empty() {
            if let Some(level) = entry.level {
                if !filters.levels.contains(&level) {
                    return false;
                }
            } else {
                return false;
            }
        }

        // Level exclude filter
        if !filters.exclude_levels.is_empty() {
            if let Some(level) = entry.level {
                if filters.exclude_levels.contains(&level) {
                    return false;
                }
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

        // Thread ID filter (single OR multi-value)
        if let Some(ref thread_ids) = filters.thread_ids {
            if !thread_ids.is_empty() {
                match &entry.thread_id {
                    Some(tid) => {
                        if !thread_ids.contains(tid) {
                            return false;
                        }
                    }
                    None => return false,
                }
            }
        } else if let Some(ref thread_id) = filters.thread_id {
            if entry.thread_id.as_ref() != Some(thread_id) {
                return false;
            }
        }

        // Correlation ID filter (single OR multi-value)
        if let Some(ref correlation_ids) = filters.correlation_ids {
            if !correlation_ids.is_empty() {
                match &entry.correlation_id {
                    Some(cid) => {
                        if !correlation_ids.contains(cid) {
                            return false;
                        }
                    }
                    None => return false,
                }
            }
        } else if let Some(ref correlation_id) = filters.correlation_id {
            if entry.correlation_id.as_ref() != Some(correlation_id) {
                return false;
            }
        }

        // Trace ID filter (single OR multi-value)
        if let Some(ref trace_ids) = filters.trace_ids {
            if !trace_ids.is_empty() {
                match &entry.trace_id {
                    Some(tid) => {
                        if !trace_ids.contains(tid) {
                            return false;
                        }
                    }
                    None => return false,
                }
            }
        } else if let Some(ref trace_id) = filters.trace_id {
            if entry.trace_id.as_ref() != Some(trace_id) {
                return false;
            }
        }

        // Service name filter (single OR multi-value)
        if let Some(ref service_names) = filters.service_names {
            if !service_names.is_empty() {
                match &entry.service_name {
                    Some(sn) => {
                        if !service_names.contains(sn) {
                            return false;
                        }
                    }
                    None => return false,
                }
            }
        } else if let Some(ref service_name) = filters.service_name {
            if entry.service_name.as_ref() != Some(service_name) {
                return false;
            }
        }

        // Has correlation ID filter
        if let Some(has_correlation_id) = filters.has_correlation_id {
            if entry.correlation_id.is_some() != has_correlation_id {
                return false;
            }
        }

        // Exclude pattern filter (regex pre-compiled, passed in)
        if let Some(regex) = exclude_regex {
            if regex.is_match(&entry.message) || regex.is_match(&entry.raw) {
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

        // Deduplicate by (file, line_number) tuple
        // This prevents duplicates when an entry matches multiple IDs
        let mut seen: std::collections::HashSet<(String, usize)> = std::collections::HashSet::new();
        all_entries.retain(|entry| {
            let key = (entry.file.clone(), entry.line_number);
            seen.insert(key)
        });

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
                let first_seen = match entries.iter().filter_map(|e| e.timestamp).min() {
                    Some(ts) => ts,
                    None => continue,
                };
                let last_seen = match entries.iter().filter_map(|e| e.timestamp).max() {
                    Some(ts) => ts,
                    None => continue,
                };
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

    /// Extract all unique IDs (thread, correlation, trace, service) from loaded files
    pub fn extract_ids(&self, filters: Option<&SearchFilters>) -> anyhow::Result<IdsResult> {
        type IdMap = HashMap<String, (usize, Option<DateTime<Utc>>, Option<DateTime<Utc>>)>;

        let mut thread_map: IdMap = HashMap::new();
        let mut correlation_map: IdMap = HashMap::new();
        let mut trace_map: IdMap = HashMap::new();
        let mut service_map: IdMap = HashMap::new();

        let mut total_entries = 0usize;
        let mut min_ts: Option<DateTime<Utc>> = None;
        let mut max_ts: Option<DateTime<Utc>> = None;

        for index in self.indices.values() {
            if let Some(entries) = &index.entries {
                for entry in entries {
                    // Apply time filter if present
                    if let Some(f) = filters {
                        if let Some(ref time_range) = f.time_range {
                            if let Some(ts) = entry.timestamp {
                                if let Some(start) = time_range.start {
                                    if ts < start {
                                        continue;
                                    }
                                }
                                if let Some(end) = time_range.end {
                                    if ts > end {
                                        continue;
                                    }
                                }
                            }
                        }
                    }

                    total_entries += 1;
                    let ts = entry.timestamp;

                    // Update global time range
                    if let Some(t) = ts {
                        min_ts = Some(min_ts.map_or(t, |m: DateTime<Utc>| m.min(t)));
                        max_ts = Some(max_ts.map_or(t, |m: DateTime<Utc>| m.max(t)));
                    }

                    // Track thread IDs
                    if let Some(ref tid) = entry.thread_id {
                        let e = thread_map.entry(tid.clone()).or_insert((0, None, None));
                        e.0 += 1;
                        if let Some(t) = ts {
                            e.1 = Some(e.1.map_or(t, |m: DateTime<Utc>| m.min(t)));
                            e.2 = Some(e.2.map_or(t, |m: DateTime<Utc>| m.max(t)));
                        }
                    }

                    // Track correlation IDs
                    if let Some(ref cid) = entry.correlation_id {
                        let e = correlation_map
                            .entry(cid.clone())
                            .or_insert((0, None, None));
                        e.0 += 1;
                        if let Some(t) = ts {
                            e.1 = Some(e.1.map_or(t, |m: DateTime<Utc>| m.min(t)));
                            e.2 = Some(e.2.map_or(t, |m: DateTime<Utc>| m.max(t)));
                        }
                    }

                    // Track trace IDs
                    if let Some(ref tid) = entry.trace_id {
                        let e = trace_map.entry(tid.clone()).or_insert((0, None, None));
                        e.0 += 1;
                        if let Some(t) = ts {
                            e.1 = Some(e.1.map_or(t, |m: DateTime<Utc>| m.min(t)));
                            e.2 = Some(e.2.map_or(t, |m: DateTime<Utc>| m.max(t)));
                        }
                    }

                    // Track service names
                    if let Some(ref sn) = entry.service_name {
                        let e = service_map.entry(sn.clone()).or_insert((0, None, None));
                        e.0 += 1;
                        if let Some(t) = ts {
                            e.1 = Some(e.1.map_or(t, |m: DateTime<Utc>| m.min(t)));
                            e.2 = Some(e.2.map_or(t, |m: DateTime<Utc>| m.max(t)));
                        }
                    }
                }
            }
        }

        fn to_id_infos(map: IdMap) -> Vec<IdInfo> {
            let mut infos: Vec<IdInfo> = map
                .into_iter()
                .map(|(id, (count, first, last))| IdInfo {
                    id,
                    count,
                    first_seen: first,
                    last_seen: last,
                })
                .collect();
            infos.sort_by(|a, b| b.count.cmp(&a.count));
            infos
        }

        let time_range = if min_ts.is_some() || max_ts.is_some() {
            Some(TimeRange {
                start: min_ts,
                end: max_ts,
            })
        } else {
            None
        };

        Ok(IdsResult {
            thread_ids: to_id_infos(thread_map),
            correlation_ids: to_id_infos(correlation_map),
            trace_ids: to_id_infos(trace_map),
            services: to_id_infos(service_map),
            total_entries,
            time_range,
        })
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
                detection_method: "Unknown".to_string(),
                detection_methods: vec![],
            }))
    }
}

impl Default for Investigator {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    fn make_test_file(entries: &[&str]) -> NamedTempFile {
        let mut f = NamedTempFile::new().unwrap();
        for e in entries {
            writeln!(f, "{}", e).unwrap();
        }
        f.flush().unwrap();
        f
    }

    fn json_entry(ts: &str, level: &str, msg: &str, thread: &str, svc: &str) -> String {
        format!(
            r#"{{"timestamp":"{}","level":"{}","message":"{}","thread_id":"{}","service_name":"{}"}}"#,
            ts, level, msg, thread, svc
        )
    }

    fn json_entry_corr(ts: &str, level: &str, msg: &str, thread: &str, corr: &str) -> String {
        format!(
            r#"{{"timestamp":"{}","level":"{}","message":"{}","thread_id":"{}","correlation_id":"{}"}}"#,
            ts, level, msg, thread, corr
        )
    }

    fn build_investigator(file: &NamedTempFile) -> Investigator {
        let mut inv = Investigator::new();
        inv.load_files(&[file.path().to_path_buf()]).unwrap();
        inv
    }

    fn make_query(
        file: &NamedTempFile,
        filters: SearchFilters,
        query: Option<String>,
    ) -> SearchQuery {
        SearchQuery {
            files: vec![file.path().to_path_buf()],
            query,
            filters,
            limit: None,
            tail: None,
            context_lines: None,
        }
    }

    #[test]
    fn test_exclude_levels() {
        let entries: Vec<String> = vec![
            json_entry("2024-01-15T10:00:00Z", "DEBUG", "debug msg", "w-0", "svc-a"),
            json_entry("2024-01-15T10:00:01Z", "INFO", "info msg", "w-0", "svc-a"),
            json_entry("2024-01-15T10:00:02Z", "WARN", "warn msg", "w-0", "svc-a"),
            json_entry("2024-01-15T10:00:03Z", "ERROR", "error msg", "w-0", "svc-a"),
        ];
        let refs: Vec<&str> = entries.iter().map(|s| s.as_str()).collect();
        let file = make_test_file(&refs);
        let inv = build_investigator(&file);

        let q = make_query(
            &file,
            SearchFilters {
                exclude_levels: vec![LogLevel::Debug],
                ..Default::default()
            },
            None,
        );
        let results = inv.search(&q).unwrap();
        assert_eq!(results.total_matches, 3);
        for r in &results.results {
            assert_ne!(r.entry.level, Some(LogLevel::Debug));
        }
    }

    #[test]
    fn test_multi_thread_ids() {
        let entries: Vec<String> = vec![
            json_entry("2024-01-15T10:00:00Z", "INFO", "a", "w-0", "svc-a"),
            json_entry("2024-01-15T10:00:01Z", "INFO", "b", "w-1", "svc-a"),
            json_entry("2024-01-15T10:00:02Z", "INFO", "c", "w-2", "svc-a"),
            json_entry("2024-01-15T10:00:03Z", "INFO", "d", "w-0", "svc-a"),
        ];
        let refs: Vec<&str> = entries.iter().map(|s| s.as_str()).collect();
        let file = make_test_file(&refs);
        let inv = build_investigator(&file);

        let q = make_query(
            &file,
            SearchFilters {
                thread_ids: Some(vec!["w-0".to_string(), "w-1".to_string()]),
                ..Default::default()
            },
            None,
        );
        let results = inv.search(&q).unwrap();
        assert_eq!(results.total_matches, 3);
    }

    #[test]
    fn test_service_filter() {
        let entries: Vec<String> = vec![
            json_entry("2024-01-15T10:00:00Z", "INFO", "a", "w-0", "api"),
            json_entry("2024-01-15T10:00:01Z", "INFO", "b", "w-0", "worker"),
            json_entry("2024-01-15T10:00:02Z", "INFO", "c", "w-0", "api"),
        ];
        let refs: Vec<&str> = entries.iter().map(|s| s.as_str()).collect();
        let file = make_test_file(&refs);
        let inv = build_investigator(&file);

        let q = make_query(
            &file,
            SearchFilters {
                service_name: Some("api".to_string()),
                ..Default::default()
            },
            None,
        );
        let results = inv.search(&q).unwrap();
        assert_eq!(results.total_matches, 2);
    }

    #[test]
    fn test_tail() {
        let mut entries = Vec::new();
        for i in 0..100 {
            entries.push(json_entry(
                &format!("2024-01-15T10:{:02}:00Z", i % 60),
                "INFO",
                &format!("msg {}", i),
                "w-0",
                "svc",
            ));
        }
        let refs: Vec<&str> = entries.iter().map(|s| s.as_str()).collect();
        let file = make_test_file(&refs);
        let inv = build_investigator(&file);

        let q = SearchQuery {
            files: vec![file.path().to_path_buf()],
            query: None,
            filters: SearchFilters::default(),
            limit: None,
            tail: Some(10),
            context_lines: None,
        };
        let results = inv.search(&q).unwrap();
        assert_eq!(results.total_matches, 100);
        assert_eq!(results.results.len(), 10);
    }

    #[test]
    fn test_exclude_pattern() {
        let entries: Vec<String> = vec![
            json_entry(
                "2024-01-15T10:00:00Z",
                "INFO",
                "health check ok",
                "w-0",
                "svc",
            ),
            json_entry("2024-01-15T10:00:01Z", "ERROR", "db timeout", "w-0", "svc"),
            json_entry(
                "2024-01-15T10:00:02Z",
                "INFO",
                "health check ok",
                "w-0",
                "svc",
            ),
            json_entry("2024-01-15T10:00:03Z", "INFO", "user login", "w-0", "svc"),
        ];
        let refs: Vec<&str> = entries.iter().map(|s| s.as_str()).collect();
        let file = make_test_file(&refs);
        let inv = build_investigator(&file);

        let q = make_query(
            &file,
            SearchFilters {
                exclude_pattern: Some("health".to_string()),
                ..Default::default()
            },
            None,
        );
        let results = inv.search(&q).unwrap();
        assert_eq!(results.total_matches, 2);
    }

    #[test]
    fn test_backward_compat_single_thread_id() {
        let entries: Vec<String> = vec![
            json_entry("2024-01-15T10:00:00Z", "INFO", "a", "w-0", "svc"),
            json_entry("2024-01-15T10:00:01Z", "INFO", "b", "w-1", "svc"),
        ];
        let refs: Vec<&str> = entries.iter().map(|s| s.as_str()).collect();
        let file = make_test_file(&refs);
        let inv = build_investigator(&file);

        // Old-style single thread_id still works
        let q = make_query(
            &file,
            SearchFilters {
                thread_id: Some("w-0".to_string()),
                ..Default::default()
            },
            None,
        );
        let results = inv.search(&q).unwrap();
        assert_eq!(results.total_matches, 1);
        assert_eq!(results.results[0].entry.thread_id, Some("w-0".to_string()));
    }

    fn json_entry_corr_trace(
        ts: &str,
        level: &str,
        msg: &str,
        thread: &str,
        corr: &str,
        trace: &str,
    ) -> String {
        format!(
            r#"{{"timestamp":"{}","level":"{}","message":"{}","thread_id":"{}","correlation_id":"{}","trace_id":"{}"}}"#,
            ts, level, msg, thread, corr, trace
        )
    }

    #[test]
    fn test_follow_thread_deduplicates_corr_and_trace() {
        let entries: Vec<String> = vec![
            json_entry_corr_trace(
                "2024-01-15T10:00:00Z",
                "INFO",
                "start request",
                "w-0",
                "req-1",
                "trace-1",
            ),
            json_entry_corr_trace(
                "2024-01-15T10:00:01Z",
                "INFO",
                "processing",
                "w-0",
                "req-1",
                "trace-1",
            ),
            json_entry_corr_trace(
                "2024-01-15T10:00:02Z",
                "INFO",
                "done",
                "w-0",
                "req-1",
                "trace-1",
            ),
        ];
        let refs: Vec<&str> = entries.iter().map(|s| s.as_str()).collect();
        let file = make_test_file(&refs);
        let inv = build_investigator(&file);

        let timeline = inv
            .follow_thread(
                &[file.path().to_path_buf()],
                None,
                Some("req-1".to_string()),
                Some("trace-1".to_string()),
            )
            .unwrap();

        assert_eq!(
            timeline.entries.len(),
            3,
            "entries should be deduplicated when matching both correlation_id and trace_id"
        );
    }

    #[test]
    fn test_extract_ids() {
        let entries: Vec<String> = vec![
            json_entry_corr("2024-01-15T10:00:00Z", "INFO", "a", "w-0", "req-1"),
            json_entry_corr("2024-01-15T10:00:01Z", "INFO", "b", "w-1", "req-1"),
            json_entry_corr("2024-01-15T10:00:02Z", "INFO", "c", "w-0", "req-2"),
            json_entry_corr("2024-01-15T10:00:03Z", "ERROR", "d", "w-1", "req-2"),
        ];
        let refs: Vec<&str> = entries.iter().map(|s| s.as_str()).collect();
        let file = make_test_file(&refs);
        let inv = build_investigator(&file);

        let result = inv.extract_ids(None).unwrap();
        assert_eq!(result.total_entries, 4);
        assert_eq!(result.thread_ids.len(), 2);
        assert_eq!(result.correlation_ids.len(), 2);

        // Both threads have 2 entries each
        for tid in &result.thread_ids {
            assert_eq!(tid.count, 2);
        }
        // Both correlation IDs have 2 entries each
        for cid in &result.correlation_ids {
            assert_eq!(cid.count, 2);
        }
    }

    #[test]
    fn test_find_patterns_no_panic_when_timestamps_missing() {
        // BSD syslog entries may have no parsed timestamps
        // Repeated errors without timestamps should not crash
        let entries: Vec<String> = vec![
            r#"{"level":"ERROR","message":"connection refused to database","thread_id":"w-0"}"#
                .to_string(),
            r#"{"level":"ERROR","message":"connection refused to database","thread_id":"w-0"}"#
                .to_string(),
            r#"{"level":"ERROR","message":"connection refused to database","thread_id":"w-1"}"#
                .to_string(),
        ];
        let refs: Vec<&str> = entries.iter().map(|s| s.as_str()).collect();
        let file = make_test_file(&refs);
        let inv = build_investigator(&file);

        let result = inv.find_patterns(&[file.path().to_path_buf()], 2);
        assert!(
            result.is_ok(),
            "find_patterns should not panic with missing timestamps"
        );
        // Pattern is skipped because no timestamps available
        let patterns = result.unwrap();
        assert_eq!(
            patterns.patterns.len(),
            0,
            "patterns without timestamps should be skipped"
        );
    }

    #[test]
    fn test_search_limit_enforced() {
        // Create 200 entries, search with limit=5
        let mut entries = Vec::new();
        for i in 0..200 {
            entries.push(json_entry(
                &format!("2024-01-15T10:{:02}:{:02}Z", i / 60, i % 60),
                "INFO",
                &format!("event {}", i),
                "w-0",
                "svc",
            ));
        }
        let refs: Vec<&str> = entries.iter().map(|s| s.as_str()).collect();
        let file = make_test_file(&refs);
        let inv = build_investigator(&file);

        let q = SearchQuery {
            files: vec![file.path().to_path_buf()],
            query: None,
            filters: SearchFilters::default(),
            limit: Some(5),
            tail: None,
            context_lines: None,
        };
        let results = inv.search(&q).unwrap();
        assert_eq!(
            results.results.len(),
            5,
            "limit should cap returned results"
        );
        assert_eq!(
            results.total_matches, 200,
            "total_matches should reflect all matches before limit"
        );
    }

    #[test]
    fn test_search_no_limit_returns_all() {
        // Without limit, all matches should be returned (under safety cap)
        let mut entries = Vec::new();
        for i in 0..50 {
            entries.push(json_entry(
                &format!("2024-01-15T10:00:{:02}Z", i),
                "INFO",
                &format!("event {}", i),
                "w-0",
                "svc",
            ));
        }
        let refs: Vec<&str> = entries.iter().map(|s| s.as_str()).collect();
        let file = make_test_file(&refs);
        let inv = build_investigator(&file);

        let q = SearchQuery {
            files: vec![file.path().to_path_buf()],
            query: None,
            filters: SearchFilters::default(),
            limit: None,
            tail: None,
            context_lines: None,
        };
        let results = inv.search(&q).unwrap();
        assert_eq!(results.results.len(), 50);
        assert_eq!(results.total_matches, 50);
    }

    #[test]
    fn test_search_limit_with_query() {
        // Limit should work correctly with a text query
        let mut entries = Vec::new();
        for i in 0..100 {
            entries.push(json_entry(
                &format!("2024-01-15T10:00:{:02}Z", i % 60),
                "INFO",
                &format!("target event {}", i),
                "w-0",
                "svc",
            ));
        }
        // Add some non-matching entries
        for i in 0..50 {
            entries.push(json_entry(
                &format!("2024-01-15T11:00:{:02}Z", i % 60),
                "INFO",
                &format!("other stuff {}", i),
                "w-0",
                "svc",
            ));
        }
        let refs: Vec<&str> = entries.iter().map(|s| s.as_str()).collect();
        let file = make_test_file(&refs);
        let inv = build_investigator(&file);

        let q = SearchQuery {
            files: vec![file.path().to_path_buf()],
            query: Some("target".to_string()),
            filters: SearchFilters::default(),
            limit: Some(10),
            tail: None,
            context_lines: None,
        };
        let results = inv.search(&q).unwrap();
        assert_eq!(results.results.len(), 10);
        assert_eq!(results.total_matches, 100);
    }

    #[test]
    fn test_find_patterns_mixed_timestamps() {
        // Mix of entries with and without timestamps
        let entries: Vec<String> = vec![
            // Timestamped errors (should produce a pattern)
            json_entry(
                "2024-01-15T10:00:00Z",
                "ERROR",
                "disk full on /var/log",
                "w-0",
                "svc-a",
            ),
            json_entry(
                "2024-01-15T10:00:01Z",
                "ERROR",
                "disk full on /var/log",
                "w-1",
                "svc-a",
            ),
            json_entry(
                "2024-01-15T10:00:02Z",
                "ERROR",
                "disk full on /var/log",
                "w-0",
                "svc-a",
            ),
            // Non-timestamped errors (should be skipped gracefully)
            r#"{"level":"ERROR","message":"no timestamp here","thread_id":"w-2"}"#.to_string(),
            r#"{"level":"ERROR","message":"no timestamp here","thread_id":"w-2"}"#.to_string(),
            r#"{"level":"ERROR","message":"no timestamp here","thread_id":"w-2"}"#.to_string(),
        ];
        let refs: Vec<&str> = entries.iter().map(|s| s.as_str()).collect();
        let file = make_test_file(&refs);
        let inv = build_investigator(&file);

        let result = inv.find_patterns(&[file.path().to_path_buf()], 2);
        assert!(
            result.is_ok(),
            "find_patterns should handle mixed timestamps"
        );
        let patterns = result.unwrap();
        // Only the timestamped pattern should appear
        assert_eq!(patterns.patterns.len(), 1);
        assert_eq!(patterns.patterns[0].occurrences, 3);
        assert!(patterns.patterns[0].pattern.contains("disk full"));
    }
}
