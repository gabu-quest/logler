use crate::index::LogIndex;
use crate::parser::ParserConfig;
use crate::types::*;
use chrono::{DateTime, Utc};
use rayon::prelude::*;
use regex::{Regex, RegexBuilder};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::hash::{BuildHasher, RandomState};
use std::path::PathBuf;
use std::time::Instant;

/// A line number that has no entry in a file: the caller named a line the file does not
/// have (past the end, 0, negative, or a file with no lines). `line` is signed so a
/// negative request reports as asked. A caller that wants the kind downcasts the
/// `anyhow::Error` to this type.
#[derive(Debug, thiserror::Error)]
#[error("{file}: no entry at line {line}")]
pub struct NoEntryAtLine {
    pub file: String,
    pub line: i64,
}

/// A `query` or `exclude_pattern` that is not a valid regex: the caller's input is wrong.
/// `which` is `"query"` or `"exclude"`, `reason` the engine's one-line reason. A caller that
/// wants the kind downcasts the `anyhow::Error` to this type.
#[derive(Debug, thiserror::Error)]
#[error("Invalid {which} pattern \"{pattern}\": {reason}")]
pub struct InvalidPattern {
    pub which: &'static str,
    pub pattern: String,
    pub reason: String,
}

/// Compile a search pattern: one regex, letter case ignored unless the pattern says
/// otherwise with its own flag (`(?-i)`).
fn compile_pattern(which: &'static str, pattern: &str) -> Result<Regex, InvalidPattern> {
    RegexBuilder::new(pattern)
        .case_insensitive(true)
        .build()
        .map_err(|e| {
            let text = e.to_string();
            let last = text.lines().last().unwrap_or(&text);
            InvalidPattern {
                which,
                pattern: pattern.to_string(),
                reason: last.strip_prefix("error: ").unwrap_or(last).to_string(),
            }
        })
}

/// Whether a search pattern matches an entry: in the line as written in the file, or in the
/// message as read from it. The two differ where the line holds the message in another
/// spelling: a JSON line writes a quote as `\"` and may write `ä` as `\u00e4`.
fn pattern_matches(regex: &Regex, entry: &LogEntry) -> bool {
    regex.is_match(&entry.raw) || regex.is_match(&entry.message)
}

/// Safety cap: maximum results returned when no limit/tail is specified.
/// Prevents a single unbounded query from allocating gigabytes of memory.
/// At ~80 bytes per materialized result + JSON serialization overhead,
/// 10K results ≈ 80 MB total (Rust + Python).
///
/// Callers can override:
///   - `limit: Some(N)` for N > 0 → return at most N results
///   - `limit: Some(0)` → no cap (like MongoDB `cursor.limit(0)`)
///   - `limit: None` → apply this safety cap
const DEFAULT_MAX_RESULTS: usize = 10_000;

/// Lightweight match candidate produced in the filter phase.
/// ~40 bytes per candidate vs ~2-4 KB per full SearchResult with cloned entry.
struct MatchCandidate {
    file_key: usize,
    entry_idx: usize,
    entry_line_number: usize,
    timestamp: Option<DateTime<Utc>>,
}

/// How many messages `SearchAggregates::top_messages` holds at most.
pub const TOP_MESSAGES: usize = 20;
/// How many characters of a message `SearchAggregates::top_messages` keeps.
pub const MESSAGE_CHARS: usize = 200;
/// How many matches of a message `MessageSummary::examples` names.
pub const MESSAGE_EXAMPLES: usize = 2;

/// The levels a summary counts under, by `level_slot`; each is named by `as_str`.
const LEVEL_SLOTS: [LogLevel; 7] = [
    LogLevel::Trace,
    LogLevel::Debug,
    LogLevel::Info,
    LogLevel::Warn,
    LogLevel::Error,
    LogLevel::Fatal,
    LogLevel::Unknown,
];

/// The slot of `LEVEL_SLOTS` a level counts under; a line with no level is `UNKNOWN`.
fn level_slot(level: Option<LogLevel>) -> usize {
    match level {
        Some(LogLevel::Trace) => 0,
        Some(LogLevel::Debug) => 1,
        Some(LogLevel::Info) => 2,
        Some(LogLevel::Warn) => 3,
        Some(LogLevel::Error) => 4,
        Some(LogLevel::Fatal) => 5,
        Some(LogLevel::Unknown) | None => 6,
    }
}

/// Counts per level, which remember the order each level was first counted.
#[derive(Clone, Copy, Default)]
struct LevelTally {
    counts: [usize; 7],
    order: [u8; 7],
    seen: u8,
}

impl LevelTally {
    fn add(&mut self, slot: usize, n: usize) {
        if self.counts[slot] == 0 {
            self.order[self.seen as usize] = slot as u8;
            self.seen += 1;
        }
        self.counts[slot] += n;
    }

    fn to_counts(self) -> OrderedCounts {
        OrderedCounts(
            self.order[..self.seen as usize]
                .iter()
                .map(|&slot| {
                    let slot = slot as usize;
                    (LEVEL_SLOTS[slot].as_str().to_string(), self.counts[slot])
                })
                .collect(),
        )
    }
}

/// A message with white space cut from both ends, as Python's `str.strip()` cuts it
/// (which also cuts the separators U+001C to U+001F), so the summary's message keys are
/// the ones it always had.
fn strip_message(message: &str) -> &str {
    message.trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
}

/// Counts per file of the search, by file number, in the order each was first counted.
struct FileTally {
    counts: Vec<usize>,
    order: Vec<usize>,
}

impl FileTally {
    fn new(files: usize) -> Self {
        Self {
            counts: vec![0; files],
            order: Vec::new(),
        }
    }

    fn add(&mut self, file_key: usize, n: usize) {
        if self.counts[file_key] == 0 {
            self.order.push(file_key);
        }
        self.counts[file_key] += n;
    }
}

/// What one run of consecutive matches counts: levels, files and times.
struct RunCounts {
    levels: LevelTally,
    files: FileTally,
    earliest: Option<DateTime<Utc>>,
    latest: Option<DateTime<Utc>>,
}

/// How often a message comes, and the positions of its first matches.
#[derive(Clone, Copy)]
struct MessageCount {
    count: usize,
    /// Positions in the search's order; the first is where the message first comes.
    examples: [usize; MESSAGE_EXAMPLES],
}

impl MessageCount {
    /// Most frequent first; of equal counts, the one whose first match comes first.
    /// Unique, because two messages never share a first match.
    fn rank(&self) -> (std::cmp::Reverse<usize>, usize) {
        (std::cmp::Reverse(self.count), self.examples[0])
    }
}

/// What a reported message holds beside its count, from one run of matches.
#[derive(Clone, Copy, Default)]
struct MessageDetail {
    levels: LevelTally,
    first_seen: Option<DateTime<Utc>>,
    last_seen: Option<DateTime<Utc>>,
}

/// Keep the `TOP_MESSAGES` items of least rank (in no order).
fn keep_top<T>(items: &mut Vec<T>, rank: impl Fn(&T) -> (std::cmp::Reverse<usize>, usize)) {
    if items.len() > TOP_MESSAGES {
        items.select_nth_unstable_by_key(TOP_MESSAGES - 1, rank);
        items.truncate(TOP_MESSAGES);
    }
}

fn min_time(a: Option<DateTime<Utc>>, b: Option<DateTime<Utc>>) -> Option<DateTime<Utc>> {
    match (a, b) {
        (Some(x), Some(y)) => Some(x.min(y)),
        (x, None) | (None, x) => x,
    }
}

fn max_time(a: Option<DateTime<Utc>>, b: Option<DateTime<Utc>>) -> Option<DateTime<Utc>> {
    match (a, b) {
        (Some(x), Some(y)) => Some(x.max(y)),
        (x, None) | (None, x) => x,
    }
}

/// The aggregates of the summary and count formats over every match, which the caller
/// has put in the search's order. Every order in the output is an order of first match
/// in that sequence, so no hash order reaches it; no entry is copied (only the messages
/// and examples reported are), and the files are not read again.
///
/// The work is spread over the threads. Each takes a run of consecutive matches and
/// counts levels, files and times, which add up in run order; with `messages`, it also
/// hashes each match's message. The hash picks one of as many shards, and each shard
/// counts its own messages, so a message is counted in one place. The few messages
/// reported then get their levels and times from a sweep over the hashes, which reads
/// an entry again only where the hash is one of theirs.
fn aggregate_matches(
    file_list: &[(&String, &LogIndex)],
    candidates: &[MatchCandidate],
    messages: bool,
) -> SearchAggregates {
    let entries_of: Vec<&[LogEntry]> = file_list
        .iter()
        .map(|(_, index)| index.entries.as_deref().unwrap_or(&[]))
        .collect();
    let entry_at = |pos: usize| {
        let c = &candidates[pos];
        &entries_of[c.file_key][c.entry_idx]
    };
    let threads = rayon::current_num_threads().max(1);
    let run = candidates.len().div_ceil(threads).max(1);
    let hasher = RandomState::new();
    let hash_of = |entry: &LogEntry| hasher.hash_one(strip_message(&entry.message));

    // Levels, files and times, by runs of consecutive matches; and each message's hash.
    let mut hashes = vec![0u64; if messages { candidates.len() } else { 0 }];
    let mut hash_runs: Vec<&mut [u64]> = hashes.chunks_mut(run).collect();
    hash_runs.resize_with(candidates.len().div_ceil(run), Default::default);
    let runs: Vec<RunCounts> = hash_runs
        .into_par_iter()
        .enumerate()
        .map(|(i, hashes)| {
            let start = i * run;
            let end = (start + run).min(candidates.len());
            let mut counts = RunCounts {
                levels: LevelTally::default(),
                files: FileTally::new(file_list.len()),
                earliest: None,
                latest: None,
            };
            for (offset, candidate) in candidates[start..end].iter().enumerate() {
                let entry = &entries_of[candidate.file_key][candidate.entry_idx];
                counts.levels.add(level_slot(entry.level), 1);
                counts.files.add(candidate.file_key, 1);
                counts.earliest = min_time(counts.earliest, entry.timestamp);
                counts.latest = max_time(counts.latest, entry.timestamp);
                if let Some(hash) = hashes.get_mut(offset) {
                    *hash = hash_of(entry);
                }
            }
            counts
        })
        .collect();

    let mut levels = LevelTally::default();
    let mut files = FileTally::new(file_list.len());
    let (mut earliest, mut latest) = (None, None);
    for counts in runs {
        for &slot in &counts.levels.order[..counts.levels.seen as usize] {
            levels.add(slot as usize, counts.levels.counts[slot as usize]);
        }
        for &file_key in &counts.files.order {
            files.add(file_key, counts.files.counts[file_key]);
        }
        earliest = min_time(earliest, counts.earliest);
        latest = max_time(latest, counts.latest);
    }

    // A file is named by its entries' `file`; two loaded files never share one, but the
    // counts would add up under it if they did.
    let mut by_file: Vec<(String, usize)> = Vec::new();
    let mut slot_of_name: HashMap<&str, usize> = HashMap::new();
    for file_key in files.order {
        let name = entries_of[file_key].first().map_or("", |e| e.file.as_str());
        let slot = *slot_of_name.entry(name).or_insert_with(|| {
            by_file.push((name.to_string(), 0));
            by_file.len() - 1
        });
        by_file[slot].1 += files.counts[file_key];
    }

    let (unique_messages, top_messages) = if messages {
        let (unique, top) = count_messages(candidates.len(), &hashes, threads, entry_at);
        let reported = describe_messages(&top, &hashes, run, &hash_of, entry_at);
        (Some(unique), Some(reported))
    } else {
        (None, None)
    };

    SearchAggregates {
        by_level: levels.to_counts(),
        by_file: OrderedCounts(by_file),
        unique_messages,
        top_messages,
        time_range: earliest.map(|start| TimeRange {
            start: Some(start),
            end: latest,
        }),
    }
}

/// How many different messages the matches hold, and the `TOP_MESSAGES` most frequent,
/// in rank order. Each shard counts the messages whose hash falls in it.
fn count_messages<'a>(
    n: usize,
    hashes: &[u64],
    shards: usize,
    entry_at: impl Fn(usize) -> &'a LogEntry + Sync,
) -> (usize, Vec<(&'a str, MessageCount)>) {
    let shards = shards as u64;
    let per_shard: Vec<(usize, Vec<(&str, MessageCount)>)> = (0..shards)
        .into_par_iter()
        .map(|shard| {
            let mine: Vec<usize> = (0..n)
                .filter(|&pos| hashes[pos] % shards == shard)
                .collect();
            // Room for every match of the shard, so the map never grows while it counts.
            let mut counts: HashMap<&str, MessageCount> = HashMap::with_capacity(mine.len());
            for pos in mine {
                let count = counts
                    .entry(strip_message(&entry_at(pos).message))
                    .or_insert(MessageCount {
                        count: 0,
                        examples: [pos; MESSAGE_EXAMPLES],
                    });
                if count.count < MESSAGE_EXAMPLES {
                    count.examples[count.count] = pos;
                }
                count.count += 1;
            }
            let mut top: Vec<(&str, MessageCount)> = counts.iter().map(|(m, c)| (*m, *c)).collect();
            keep_top(&mut top, |(_, c)| c.rank());
            (counts.len(), top)
        })
        .collect();
    let unique = per_shard.iter().map(|(unique, _)| unique).sum();
    let mut top: Vec<(&str, MessageCount)> =
        per_shard.into_iter().flat_map(|(_, top)| top).collect();
    keep_top(&mut top, |(_, c)| c.rank());
    top.sort_unstable_by_key(|(_, c)| c.rank());
    (unique, top)
}

/// The reported messages with their levels, times and examples. Runs of consecutive
/// matches are swept in parallel and add up in run order, so each message's levels come
/// in order of first match.
fn describe_messages<'a>(
    top: &[(&'a str, MessageCount)],
    hashes: &[u64],
    run: usize,
    hash_of: &(impl Fn(&LogEntry) -> u64 + Sync),
    entry_at: impl Fn(usize) -> &'a LogEntry + Sync,
) -> Vec<MessageSummary> {
    let wanted: Vec<(u64, &str)> = top
        .iter()
        .map(|(message, count)| (hash_of(entry_at(count.examples[0])), *message))
        .collect();
    let runs: Vec<Vec<MessageDetail>> = hashes
        .par_chunks(run)
        .enumerate()
        .map(|(i, hashes)| {
            let mut details = vec![MessageDetail::default(); wanted.len()];
            for (offset, hash) in hashes.iter().enumerate() {
                for (k, (want, message)) in wanted.iter().enumerate() {
                    if hash != want {
                        continue;
                    }
                    let entry = entry_at(i * run + offset);
                    if strip_message(&entry.message) != *message {
                        continue;
                    }
                    let detail = &mut details[k];
                    detail.levels.add(level_slot(entry.level), 1);
                    detail.first_seen = min_time(detail.first_seen, entry.timestamp);
                    detail.last_seen = max_time(detail.last_seen, entry.timestamp);
                }
            }
            details
        })
        .collect();

    top.iter()
        .enumerate()
        .map(|(k, (message, count))| {
            let mut detail = MessageDetail::default();
            for run in &runs {
                let part = &run[k];
                for &slot in &part.levels.order[..part.levels.seen as usize] {
                    detail
                        .levels
                        .add(slot as usize, part.levels.counts[slot as usize]);
                }
                detail.first_seen = min_time(detail.first_seen, part.first_seen);
                detail.last_seen = max_time(detail.last_seen, part.last_seen);
            }
            MessageSummary {
                message: message.chars().take(MESSAGE_CHARS).collect(),
                count: count.count,
                first_seen: detail.first_seen,
                last_seen: detail.last_seen,
                levels: detail.levels.to_counts(),
                examples: count.examples[..count.count.min(MESSAGE_EXAMPLES)]
                    .iter()
                    .map(|&pos| {
                        let entry = entry_at(pos);
                        MessageExample {
                            file: entry.file.clone(),
                            line: entry.line_number,
                            timestamp: entry.timestamp,
                            level: LEVEL_SLOTS[level_slot(entry.level)].as_str().to_string(),
                        }
                    })
                    .collect(),
            }
        })
        .collect()
}

/// Main investigation API for LLM agents
pub struct Investigator {
    /// Loaded files by path. Ordered, so every walk over the files goes in order of path.
    indices: BTreeMap<String, LogIndex>,
}

impl Investigator {
    /// Create a new investigator
    pub fn new() -> Self {
        Self {
            indices: BTreeMap::new(),
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
    ///
    /// When `count_only` is set, Phase 2 is skipped entirely — returns
    /// `total_matches` with an empty `results` vec (zero serialization cost).
    ///
    /// `offset` is applied after sorting and before `take(limit)`, enabling
    /// server-side pagination without re-materializing skipped entries.
    pub fn search(&self, query: &SearchQuery) -> anyhow::Result<SearchResults> {
        let start = Instant::now();

        // Compile both patterns once, before any line is read. An empty query is no filter.
        let query_regex = match query.query.as_deref() {
            Some(pattern) if !pattern.is_empty() => Some(compile_pattern("query", pattern)?),
            _ => None,
        };
        let exclude_regex = query
            .filters
            .exclude_pattern
            .as_deref()
            .map(|pattern| compile_pattern("exclude", pattern))
            .transpose()?;

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
            let candidates = self.collect_candidates(
                file_key,
                index,
                query,
                query_regex.as_ref(),
                exclude_regex.as_ref(),
            )?;
            all_candidates.extend(candidates);
        }

        let total_matches = all_candidates.len();
        let count_only = query.count_only.unwrap_or(false);

        // count_only: skip Phase 2 entirely — no sorting, no materialization
        if count_only && query.aggregate.is_none() {
            return Ok(SearchResults {
                results: Vec::new(),
                total_matches,
                search_time_ms: start.elapsed().as_millis() as u64,
                aggregates: None,
            });
        }

        // Sort, count every match when asked, and truncate before materializing
        let skip_n = query.offset.unwrap_or(0);
        if query.tail.is_some() {
            // Sort by timestamp ASC; the page is the last N (offset not applied to tail)
            all_candidates.sort_by(|a, b| match (&a.timestamp, &b.timestamp) {
                (Some(t1), Some(t2)) => t1.cmp(t2),
                (Some(_), None) => std::cmp::Ordering::Less,
                (None, Some(_)) => std::cmp::Ordering::Greater,
                (None, None) => a.entry_line_number.cmp(&b.entry_line_number),
            });
        } else {
            // Sort by timestamp; entries with none keep file order after the timed ones
            all_candidates.sort_by(|a, b| match (&a.timestamp, &b.timestamp) {
                (Some(t1), Some(t2)) => t1.cmp(t2),
                (Some(_), None) => std::cmp::Ordering::Less,
                (None, Some(_)) => std::cmp::Ordering::Greater,
                (None, None) => std::cmp::Ordering::Equal,
            });
        }
        let aggregates = query.aggregate.map(|what| {
            aggregate_matches(&file_list, &all_candidates, what == Aggregate::Messages)
        });
        if count_only {
            return Ok(SearchResults {
                results: Vec::new(),
                total_matches,
                search_time_ms: start.elapsed().as_millis() as u64,
                aggregates,
            });
        }

        let selected: Vec<MatchCandidate> = if let Some(tail_n) = query.tail {
            let skip = all_candidates.len().saturating_sub(tail_n);
            all_candidates.into_iter().skip(skip).collect()
        } else {
            let cap = match query.limit {
                Some(0) => usize::MAX, // 0 = no limit (like MongoDB cursor.limit(0))
                Some(n) => n,
                None => DEFAULT_MAX_RESULTS,
            };
            all_candidates.into_iter().skip(skip_n).take(cap).collect()
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
                    relevance_score: 1.0,
                }
            })
            .collect();

        Ok(SearchResults {
            results,
            total_matches,
            search_time_ms: start.elapsed().as_millis() as u64,
            aggregates,
        })
    }

    /// Phase 1: Collect lightweight match candidates from a single index.
    /// Returns entry indices and scores without cloning entries or fetching context.
    fn collect_candidates(
        &self,
        file_key: usize,
        index: &LogIndex,
        query: &SearchQuery,
        query_regex: Option<&Regex>,
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
            .filter(|(_, entry)| query_regex.is_none_or(|regex| pattern_matches(regex, entry)))
            .map(|(idx, entry)| MatchCandidate {
                file_key,
                entry_idx: idx,
                entry_line_number: entry.line_number,
                timestamp: entry.timestamp,
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
            if pattern_matches(regex, entry) {
                return false;
            }
        }

        true
    }

    /// Return a page of raw entries by slicing the in-memory index directly.
    ///
    /// O(page_size) per call — no filtering, scoring, or sorting.
    /// File keys are sorted for deterministic pagination across calls.
    pub fn get_entries_page(&self, offset: usize, limit: usize) -> EntriesPage {
        let mut file_keys: Vec<&String> = self.indices.keys().collect();
        file_keys.sort();

        let mut total_entries = 0;
        for key in &file_keys {
            if let Some(entries) = &self.indices[*key].entries {
                total_entries += entries.len();
            }
        }

        let mut result = Vec::with_capacity(limit.min(total_entries.saturating_sub(offset)));
        let mut global_idx = 0;

        for key in &file_keys {
            if let Some(entries) = &self.indices[*key].entries {
                let file_len = entries.len();
                if global_idx + file_len <= offset {
                    global_idx += file_len;
                    continue;
                }
                let start = offset.saturating_sub(global_idx);
                for entry in &entries[start..] {
                    if result.len() >= limit {
                        return EntriesPage {
                            entries: result,
                            total_entries,
                            has_more: true,
                        };
                    }
                    result.push(entry.clone());
                }
                global_idx += file_len;
            }
        }

        EntriesPage {
            entries: result,
            total_entries,
            has_more: false,
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

        let unique_spans: BTreeSet<String> = all_entries
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
            .ok_or_else(|| NoEntryAtLine {
                file: file.to_string(),
                line: i64::try_from(line_number).unwrap_or(i64::MAX),
            })?
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
                let affected_threads: BTreeSet<String> =
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

        // Most occurrences first; patterns with the same count in order of pattern
        patterns.sort_by(|a, b| {
            b.occurrences
                .cmp(&a.occurrences)
                .then_with(|| a.pattern.cmp(&b.pattern))
        });

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
            let available_fields: BTreeSet<String> = entries
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

    /// For every thread id in the loaded files (or in `files`, when any are named), its number
    /// of entries at each level, by level name, and `total`, its number of entries. Several
    /// files add up; an entry with no thread id is in no thread's counts.
    pub fn thread_level_counts(
        &self,
        files: &[PathBuf],
    ) -> BTreeMap<String, BTreeMap<String, usize>> {
        let mut threads: BTreeMap<String, BTreeMap<String, usize>> = BTreeMap::new();
        for (file_path, index) in &self.indices {
            if !files.is_empty()
                && !files
                    .iter()
                    .any(|f| f.to_string_lossy() == file_path.as_str())
            {
                continue;
            }
            for (thread_id, levels) in index.thread_level_counts() {
                let counts = threads.entry(thread_id).or_default();
                for (level, count) in levels {
                    *counts.entry(level.as_str().to_string()).or_insert(0) += count;
                    *counts.entry("total".to_string()).or_insert(0) += count;
                }
            }
        }
        threads
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
            // Highest count first; ids with the same count in order of id
            infos.sort_by(|a, b| b.count.cmp(&a.count).then_with(|| a.id.cmp(&b.id)));
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
            count_only: None,
            offset: None,
            aggregate: None,
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
            count_only: None,
            offset: None,
            aggregate: None,
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
            count_only: None,
            offset: None,
            aggregate: None,
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
            count_only: None,
            offset: None,
            aggregate: None,
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
            count_only: None,
            offset: None,
            aggregate: None,
        };
        let results = inv.search(&q).unwrap();
        assert_eq!(results.results.len(), 10);
        assert_eq!(results.total_matches, 100);
    }

    #[test]
    fn a_query_is_one_case_blind_regex_over_the_whole_line() {
        let lines = [
            r#"{"time":"2024-01-15T10:00:00Z","level":"error","msg":"payment failed","err":"connection refused","order":"A-17"}"#,
            r#"{"time":"2024-01-15T10:00:01Z","level":"info","msg":"payment ok","order":"A-18"}"#,
            r#"{"time":"2024-01-15T10:00:02Z","level":"info","msg":"connection refused by peer"}"#,
        ];
        let file = make_test_file(&lines);
        let inv = build_investigator(&file);
        let found = |pattern: &str| -> Vec<usize> {
            let q = make_query(&file, SearchFilters::default(), Some(pattern.to_string()));
            let out = inv.search(&q).unwrap();
            out.results.iter().map(|r| r.entry.line_number).collect()
        };
        assert_eq!(found("A-17"), vec![1]);
        assert_eq!(found("CONNECTION REFUSED"), vec![1, 3]);
        assert_eq!(found("connection timeout"), Vec::<usize>::new());
        assert_eq!(found("timeout|ok"), vec![2]);
        assert_eq!(found("(?-i)PAYMENT"), Vec::<usize>::new());
        assert_eq!(found(""), vec![1, 2, 3]);
    }

    #[test]
    fn a_pattern_also_reads_the_message_a_json_line_holds_with_escapes() {
        let lines = [
            r#"{"time":"2024-01-15T10:00:00Z","level":"info","msg":"user said \"no\"","n":1}"#,
            r#"{"time":"2024-01-15T10:00:01Z","level":"info","msg":"viel \u00e4rger","n":2}"#,
        ];
        let file = make_test_file(&lines);
        let inv = build_investigator(&file);
        let found = |query: Option<&str>, exclude: Option<&str>| -> Vec<usize> {
            let filters = SearchFilters {
                exclude_pattern: exclude.map(str::to_string),
                ..Default::default()
            };
            let q = make_query(&file, filters, query.map(str::to_string));
            let out = inv.search(&q).unwrap();
            out.results.iter().map(|r| r.entry.line_number).collect()
        };
        assert_eq!(found(Some(r#"said "no""#), None), vec![1]);
        assert_eq!(found(Some("ÄRGER"), None), vec![2]);
        assert_eq!(found(Some(r"\\u00e4"), None), vec![2]);
        assert_eq!(found(Some("^viel"), None), vec![2]);
        assert_eq!(found(None, Some(r#"said "no""#)), vec![2]);
        assert_eq!(found(None, Some("ärger")), vec![1]);
    }

    #[test]
    fn a_pattern_that_is_not_a_regex_is_the_callers_error() {
        let file = make_test_file(&[r#"{"time":"2024-01-15T10:00:00Z","level":"info","msg":"a"}"#]);
        let inv = build_investigator(&file);

        let q = make_query(&file, SearchFilters::default(), Some("(".to_string()));
        let err = inv.search(&q).unwrap_err();
        assert_eq!(
            err.to_string(),
            "Invalid query pattern \"(\": unclosed group"
        );
        assert!(err.downcast_ref::<InvalidPattern>().is_some());

        let filters = SearchFilters {
            exclude_pattern: Some("[".to_string()),
            ..Default::default()
        };
        let q = make_query(&file, filters, None);
        let err = inv.search(&q).unwrap_err();
        assert_eq!(
            err.to_string(),
            "Invalid exclude pattern \"[\": unclosed character class"
        );
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

    #[test]
    fn test_search_count_only() {
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
            count_only: Some(true),
            offset: None,
            aggregate: None,
        };
        let results = inv.search(&q).unwrap();
        assert_eq!(
            results.total_matches, 50,
            "count_only should report all matches"
        );
        assert_eq!(
            results.results.len(),
            0,
            "count_only should return empty results vec"
        );
    }

    #[test]
    fn test_search_offset() {
        let mut entries = Vec::new();
        for i in 0..20 {
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
            limit: Some(5),
            tail: None,
            context_lines: None,
            count_only: None,
            offset: Some(10),
            aggregate: None,
        };
        let results = inv.search(&q).unwrap();
        assert_eq!(
            results.total_matches, 20,
            "total_matches unaffected by offset"
        );
        assert_eq!(results.results.len(), 5, "limit respected after offset");
        // Verify correct entries returned (no query → all score 1.0, sorted by timestamp)
        assert_eq!(results.results[0].entry.message, "event 10");
        assert_eq!(results.results[4].entry.message, "event 14");
    }

    #[test]
    fn test_search_offset_beyond_total() {
        let mut entries = Vec::new();
        for i in 0..20 {
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
            limit: Some(10),
            tail: None,
            context_lines: None,
            count_only: None,
            offset: Some(25),
            aggregate: None,
        };
        let results = inv.search(&q).unwrap();
        assert_eq!(results.total_matches, 20, "total_matches still reported");
        assert_eq!(results.results.len(), 0, "offset past end returns empty");
    }

    #[test]
    fn test_search_count_only_with_filter() {
        let mut entries = Vec::new();
        for i in 0..50 {
            let level = if i % 2 == 0 { "ERROR" } else { "INFO" };
            entries.push(json_entry(
                &format!("2024-01-15T10:00:{:02}Z", i % 60),
                level,
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
            filters: SearchFilters {
                levels: vec![LogLevel::Error],
                ..Default::default()
            },
            limit: None,
            tail: None,
            context_lines: None,
            count_only: Some(true),
            offset: None,
            aggregate: None,
        };
        let results = inv.search(&q).unwrap();
        assert_eq!(
            results.total_matches, 25,
            "count_only with filter counts correctly"
        );
        assert_eq!(results.results.len(), 0, "count_only returns no entries");
    }

    #[test]
    fn test_search_limit_zero_returns_all() {
        // limit=0 means "no cap" — return all matches (like MongoDB cursor.limit(0))
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
            limit: Some(0),
            tail: None,
            context_lines: None,
            count_only: None,
            offset: None,
            aggregate: None,
        };
        let results = inv.search(&q).unwrap();
        assert_eq!(
            results.results.len(),
            200,
            "limit=0 should return all results"
        );
        assert_eq!(results.total_matches, 200);
    }

    // Each Investigator below is built again in a loop: every hash map has its own order,
    // so one lucky run cannot pass.

    #[test]
    fn loaded_files_are_walked_in_order_of_path() {
        for _ in 0..20 {
            let files: Vec<NamedTempFile> = (0..8)
                .map(|i| {
                    make_test_file(&[&json_entry(
                        "2024-01-15T10:00:00Z",
                        "INFO",
                        &format!("file {i}"),
                        "t",
                        "svc",
                    )])
                })
                .collect();
            let mut inv = Investigator::new();
            let paths: Vec<PathBuf> = files.iter().map(|f| f.path().to_path_buf()).collect();
            inv.load_files(&paths).unwrap();

            let mut expected: Vec<String> = paths
                .iter()
                .map(|p| p.to_string_lossy().to_string())
                .collect();
            expected.sort();
            let walked: Vec<String> = inv
                .get_metadata(&[])
                .unwrap()
                .into_iter()
                .map(|m| m.path)
                .collect();
            assert_eq!(walked, expected);
        }
    }

    #[test]
    fn thread_level_counts_are_per_thread_and_per_level() {
        let one = make_test_file(&[
            &json_entry("2024-01-15T10:00:00Z", "INFO", "a", "t1", "svc"),
            &json_entry("2024-01-15T10:00:01Z", "ERROR", "b", "t1", "svc"),
            &json_entry("2024-01-15T10:00:02Z", "ERROR", "c", "t1", "svc"),
            &json_entry("2024-01-15T10:00:03Z", "WARN", "d", "t2", "svc"),
            r#"{"timestamp":"2024-01-15T10:00:04Z","message":"no level","thread_id":"t3"}"#,
            r#"{"timestamp":"2024-01-15T10:00:05Z","level":"ERROR","message":"no thread"}"#,
        ]);
        let two = make_test_file(&[
            &json_entry("2024-01-15T10:00:06Z", "INFO", "e", "t1", "svc"),
            &json_entry("2024-01-15T10:00:07Z", "WARN", "f", "t2", "svc"),
        ]);
        let mut inv = Investigator::new();
        inv.load_files(&[one.path().to_path_buf(), two.path().to_path_buf()])
            .unwrap();
        let counts = |t: &[(&str, usize)]| -> BTreeMap<String, usize> {
            t.iter().map(|(k, v)| (k.to_string(), *v)).collect()
        };
        let all = inv.thread_level_counts(&[]);
        assert_eq!(all.len(), 3);
        assert_eq!(
            all["t1"],
            counts(&[("INFO", 2), ("ERROR", 2), ("total", 4)])
        );
        assert_eq!(all["t2"], counts(&[("WARN", 2), ("total", 2)]));
        assert_eq!(all["t3"], counts(&[("UNKNOWN", 1), ("total", 1)]));
        let only_one = inv.thread_level_counts(&[one.path().to_path_buf()]);
        assert_eq!(
            only_one["t1"],
            counts(&[("INFO", 1), ("ERROR", 2), ("total", 3)])
        );
        assert_eq!(only_one["t2"], counts(&[("WARN", 1), ("total", 1)]));
    }

    #[test]
    fn ids_with_the_same_count_come_in_order_of_id() {
        let names = ["m", "c", "x", "a", "q", "b", "z", "d", "k", "f"];
        for _ in 0..20 {
            let lines: Vec<String> = names
                .iter()
                .map(|n| json_entry("2024-01-15T10:00:00Z", "INFO", "hi", &format!("w-{n}"), n))
                .collect();
            let refs: Vec<&str> = lines.iter().map(String::as_str).collect();
            let file = make_test_file(&refs);
            let ids = build_investigator(&file).extract_ids(None).unwrap();

            let mut sorted: Vec<&str> = names.to_vec();
            sorted.sort();
            let threads: Vec<String> = ids.thread_ids.iter().map(|i| i.id.clone()).collect();
            let expected: Vec<String> = sorted.iter().map(|n| format!("w-{n}")).collect();
            assert_eq!(threads, expected);
            let services: Vec<&str> = ids.services.iter().map(|i| i.id.as_str()).collect();
            assert_eq!(services, sorted);
        }
    }

    #[test]
    fn error_patterns_with_the_same_count_come_in_order_of_pattern() {
        let words = ["pear", "fig", "plum", "apple", "kiwi", "lime"];
        for _ in 0..20 {
            let lines: Vec<String> = words
                .iter()
                .flat_map(|w| {
                    (0..2).map(move |i| {
                        json_entry(
                            "2024-01-15T10:00:00Z",
                            "ERROR",
                            &format!("{w} failed"),
                            &format!("t-{w}-{i}"),
                            "svc",
                        )
                    })
                })
                .collect();
            let refs: Vec<&str> = lines.iter().map(String::as_str).collect();
            let file = make_test_file(&refs);
            let found = build_investigator(&file).find_patterns(&[], 2).unwrap();

            let mut expected: Vec<String> = words.iter().map(|w| format!("{w} failed")).collect();
            expected.sort();
            let order: Vec<String> = found.patterns.iter().map(|p| p.pattern.clone()).collect();
            assert_eq!(order, expected);
            for p in &found.patterns {
                let mut threads = p.affected_threads.clone();
                threads.sort();
                assert_eq!(p.affected_threads, threads, "threads of {}", p.pattern);
            }
        }
    }

    #[test]
    fn a_result_writes_its_maps_with_the_keys_in_order() {
        let keys = ["m", "c", "x", "a", "q", "b", "z", "d", "k", "f"];
        for _ in 0..20 {
            let lines = [r#"{"timestamp":"2024-01-15T10:00:00Z","level":"INFO","message":"hi","m":1,"c":1,"x":1,"a":1,"q":1,"b":1,"z":1,"d":1,"k":1,"f":1}"#.to_string()];
            let refs: Vec<&str> = lines.iter().map(String::as_str).collect();
            let file = make_test_file(&refs);
            let inv = build_investigator(&file);
            let entry = inv.get_entries_page(0, 1).entries.remove(0);
            let written = serde_json::to_string(&entry).unwrap();
            let at: Vec<usize> = ["a", "b", "c", "d", "f", "k", "m", "q", "x", "z"]
                .iter()
                .map(|k| written.find(&format!("\"{k}\":1")).unwrap())
                .collect();
            let mut in_order = at.clone();
            in_order.sort();
            assert_eq!(at, in_order, "fields of an entry in key order: {written}");
            assert_eq!(keys.len(), at.len());

            let mut stats = crate::stats::LogStats::new();
            for k in keys {
                stats.level_counts.insert(k.to_string(), 1);
                stats.service_counts.insert(k.to_string(), 1);
                stats.thread_counts.insert(k.to_string(), 1);
            }
            let written = serde_json::to_string(&stats).unwrap();
            let sorted = r#"{"a":1,"b":1,"c":1,"d":1,"f":1,"k":1,"m":1,"q":1,"x":1,"z":1}"#;
            for field in ["level_counts", "service_counts", "thread_counts"] {
                assert!(
                    written.contains(&format!("\"{field}\":{sorted}")),
                    "{field} in key order: {written}"
                );
            }
        }
    }

    mod aggregates {
        use super::*;

        fn line(ts: Option<&str>, level: Option<&str>, msg: &str) -> String {
            let mut rec = serde_json::Map::new();
            if let Some(ts) = ts {
                rec.insert("timestamp".into(), ts.into());
            }
            if let Some(level) = level {
                rec.insert("level".into(), level.into());
            }
            rec.insert("message".into(), msg.into());
            serde_json::Value::Object(rec).to_string()
        }

        fn second(i: usize) -> String {
            format!("2024-01-15T10:{:02}:{:02}Z", i / 60, i % 60)
        }

        fn search(lines: &[String], tweak: impl FnOnce(&mut SearchQuery)) -> SearchResults {
            let refs: Vec<&str> = lines.iter().map(String::as_str).collect();
            let file = make_test_file(&refs);
            let inv = build_investigator(&file);
            let mut q = make_query(&file, SearchFilters::default(), None);
            q.aggregate = Some(Aggregate::Messages);
            tweak(&mut q);
            inv.search(&q).unwrap()
        }

        fn counts(pairs: &[(&str, usize)]) -> OrderedCounts {
            OrderedCounts(pairs.iter().map(|(k, v)| (k.to_string(), *v)).collect())
        }

        #[test]
        fn every_match_is_counted_whatever_the_limit() {
            let lines: Vec<String> = (0..30)
                .map(|i| {
                    let level = if i < 25 { "INFO" } else { "ERROR" };
                    line(Some(&second(i)), Some(level), &format!("m{}", i % 4))
                })
                .collect();
            let out = search(&lines, |q| q.limit = Some(3));
            assert_eq!(out.results.len(), 3, "the page keeps the limit");
            let agg = out.aggregates.unwrap();
            assert_eq!(agg.by_level, counts(&[("INFO", 25), ("ERROR", 5)]));
            assert_eq!(agg.by_file.0.len(), 1);
            assert_eq!(agg.by_file.0[0].1, 30);
            assert_eq!(agg.unique_messages, Some(4));
            let time = agg.time_range.unwrap();
            assert_eq!(
                time.start.unwrap().to_rfc3339(),
                "2024-01-15T10:00:00+00:00"
            );
            assert_eq!(time.end.unwrap().to_rfc3339(), "2024-01-15T10:00:29+00:00");
        }

        #[test]
        fn messages_of_equal_count_come_in_order_of_first_match() {
            let words = [
                ("INFO", "beta"),
                ("ERROR", "alpha"),
                ("WARN", "gamma"),
                ("INFO", "alpha"),
                ("INFO", "beta"),
                ("DEBUG", "gamma"),
                ("INFO", "delta"),
            ];
            let lines: Vec<String> = words
                .iter()
                .enumerate()
                .map(|(i, (lv, m))| line(Some(&second(i)), Some(lv), m))
                .collect();
            let agg = search(&lines, |_| {}).aggregates.unwrap();
            let top = agg.top_messages.unwrap();
            let names: Vec<(&str, usize)> =
                top.iter().map(|m| (m.message.as_str(), m.count)).collect();
            assert_eq!(
                names,
                [("beta", 2), ("alpha", 2), ("gamma", 2), ("delta", 1)]
            );
            assert_eq!(top[1].levels, counts(&[("ERROR", 1), ("INFO", 1)]));
            let lines_of: Vec<usize> = top[1].examples.iter().map(|e| e.line).collect();
            assert_eq!(lines_of, [2, 4], "alpha's first two lines");
            assert_eq!(top[1].examples[0].level, "ERROR");
            assert_eq!(top[3].examples.len(), 1, "delta has one line");
            assert_eq!(
                agg.by_level,
                counts(&[("INFO", 4), ("ERROR", 1), ("WARN", 1), ("DEBUG", 1)])
            );
        }

        #[test]
        fn more_than_twenty_messages_keep_the_twenty_most_frequent() {
            // m0..m24 once each in order, then m24 twice more and m23 once more.
            let mut words: Vec<String> = (0..25).map(|k| format!("m{k}")).collect();
            words.extend(["m24", "m24", "m23"].map(String::from));
            let lines: Vec<String> = words
                .iter()
                .enumerate()
                .map(|(i, m)| line(Some(&second(i)), Some("INFO"), m))
                .collect();
            let agg = search(&lines, |_| {}).aggregates.unwrap();
            assert_eq!(agg.unique_messages, Some(25));
            let top: Vec<String> = agg
                .top_messages
                .unwrap()
                .iter()
                .map(|m| format!("{}x{}", m.message, m.count))
                .collect();
            let mut expected = vec!["m24x3".to_string(), "m23x2".to_string()];
            expected.extend((0..18).map(|k| format!("m{k}x1")));
            assert_eq!(top, expected);
        }

        #[test]
        fn white_space_is_cut_as_python_cuts_it() {
            let lines = vec![
                line(Some(&second(0)), Some("INFO"), "  tick "),
                line(Some(&second(1)), Some("INFO"), "tick\u{1c}"),
                line(Some(&second(2)), Some("INFO"), "\ttick"),
            ];
            let top = search(&lines, |_| {})
                .aggregates
                .unwrap()
                .top_messages
                .unwrap();
            assert_eq!(top.len(), 1, "one message: {top:?}");
            assert_eq!((top[0].message.as_str(), top[0].count), ("tick", 3));
        }

        #[test]
        fn a_long_message_is_cut_to_two_hundred_characters() {
            let long = "é".repeat(250);
            let lines = vec![line(Some(&second(0)), Some("INFO"), &long)];
            let top = search(&lines, |_| {})
                .aggregates
                .unwrap()
                .top_messages
                .unwrap();
            assert_eq!(top[0].message, "é".repeat(200));
        }

        #[test]
        fn times_are_compared_as_times_and_a_line_with_none_is_left_out() {
            let lines = vec![
                line(Some("2024-01-15T10:00:05.500Z"), Some("INFO"), "tick"),
                line(Some("2024-01-15T10:00:05Z"), Some("INFO"), "tick"),
                line(None, Some("ERROR"), "tick"),
            ];
            let agg = search(&lines, |_| {}).aggregates.unwrap();
            let tick = &agg.top_messages.unwrap()[0];
            let text = |t: Option<DateTime<Utc>>| serde_json::to_string(&t).unwrap();
            assert_eq!(text(tick.first_seen), r#""2024-01-15T10:00:05Z""#);
            assert_eq!(text(tick.last_seen), r#""2024-01-15T10:00:05.500Z""#);
            let time = agg.time_range.unwrap();
            assert_eq!(text(time.start), r#""2024-01-15T10:00:05Z""#);
            assert_eq!(text(time.end), r#""2024-01-15T10:00:05.500Z""#);

            let none = vec![line(None, None, "a"), line(None, Some("WARN"), "b")];
            let agg = search(&none, |_| {}).aggregates.unwrap();
            assert!(agg.time_range.is_none(), "no timestamp: {agg:?}");
            assert_eq!(agg.by_level, counts(&[("UNKNOWN", 1), ("WARN", 1)]));
            assert_eq!(agg.top_messages.unwrap()[0].first_seen, None);
        }

        #[test]
        fn counts_alone_hold_no_messages_and_count_only_returns_no_page() {
            let lines: Vec<String> = (0..5)
                .map(|i| line(Some(&second(i)), Some("WARN"), "w"))
                .collect();
            let out = search(&lines, |q| {
                q.aggregate = Some(Aggregate::Counts);
                q.count_only = Some(true);
            });
            assert_eq!(out.results.len(), 0);
            assert_eq!(out.total_matches, 5);
            let agg = out.aggregates.unwrap();
            assert_eq!(agg.by_level, counts(&[("WARN", 5)]));
            assert_eq!(agg.unique_messages, None);
            let written = serde_json::to_string(&agg).unwrap();
            assert!(!written.contains("messages"), "{written}");

            let plain = search(&lines, |q| q.aggregate = None);
            let written = serde_json::to_string(&plain).unwrap();
            assert!(!written.contains("aggregates"), "{written}");
        }

        #[test]
        fn no_match_counts_nothing() {
            let lines = vec![line(Some(&second(0)), Some("INFO"), "a")];
            let out = search(&lines, |q| q.query = Some("zzz".to_string()));
            let agg = out.aggregates.unwrap();
            assert_eq!(out.total_matches, 0);
            assert_eq!(agg.by_level, counts(&[]));
            assert_eq!(agg.unique_messages, Some(0));
            assert_eq!(agg.top_messages.unwrap().len(), 0);
            assert!(agg.time_range.is_none());
        }

        /// Many matches over every thread: the counts equal a plain count, in one loop,
        /// over the matches as the search sorts them.
        #[test]
        fn the_threaded_counts_equal_a_plain_count_in_search_order() {
            let levels = ["INFO", "DEBUG", "WARN", "ERROR", "FATAL"];
            let lines: Vec<String> = (0..20_000)
                .map(|i| {
                    let ts = (i % 7 != 0).then(|| {
                        format!(
                            "2024-01-15T{:02}:{:02}:{:02}Z",
                            i % 24,
                            (i * 7) % 60,
                            i % 60
                        )
                    });
                    let level = (i % 11 != 0).then_some(levels[(i * 3) % 5]);
                    line(ts.as_deref(), level, &format!("msg {}", (i * 13) % 997))
                })
                .collect();
            let out = search(&lines, |q| q.limit = Some(0));
            let agg = out.aggregates.unwrap();

            let mut by_level: Vec<(String, usize)> = Vec::new();
            let mut msgs: Vec<(String, usize, Vec<usize>)> = Vec::new();
            for r in &out.results {
                let e = &r.entry;
                let lv = e.level.unwrap_or(LogLevel::Unknown).as_str().to_string();
                match by_level.iter_mut().find(|(k, _)| *k == lv) {
                    Some((_, n)) => *n += 1,
                    None => by_level.push((lv, 1)),
                }
                let m = e.message.trim().to_string();
                match msgs.iter_mut().find(|(k, _, _)| *k == m) {
                    Some((_, n, ex)) => {
                        *n += 1;
                        if ex.len() < 2 {
                            ex.push(e.line_number);
                        }
                    }
                    None => msgs.push((m, 1, vec![e.line_number])),
                }
            }
            assert_eq!(agg.by_level, OrderedCounts(by_level));
            assert_eq!(agg.unique_messages, Some(msgs.len()));
            msgs.sort_by_key(|(_, n, _)| std::cmp::Reverse(*n));
            let top = agg.top_messages.unwrap();
            let got: Vec<(String, usize, Vec<usize>)> = top
                .iter()
                .map(|m| {
                    let lines = m.examples.iter().map(|e| e.line).collect();
                    (m.message.clone(), m.count, lines)
                })
                .collect();
            assert_eq!(got, msgs[..20].to_vec());
        }

        #[test]
        fn ordered_counts_keep_their_order_in_json() {
            let c = counts(&[("b", 1), ("a", 2)]);
            let written = serde_json::to_string(&c).unwrap();
            assert_eq!(written, r#"{"b":1,"a":2}"#);
            let read: OrderedCounts = serde_json::from_str(&written).unwrap();
            assert_eq!(read, c);
        }
    }
}
