use crate::parser::ParserConfig;
use crate::types::{LogEntry, LogLevel};
use rayon::prelude::*;
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

/// Lines parsed together. With `BATCH_BYTES` it bounds the memory held beside the entries.
const BATCH_LINES: usize = 16_384;
/// Bytes of line text after which a batch is sent, however few lines it holds.
const BATCH_BYTES: usize = 8 << 20;
const UTF8_BOM: &[u8] = b"\xEF\xBB\xBF";

type LineBatch = Vec<(usize, String)>;

/// Cut a file into numbered lines on bytes and send them in batches, in file order. A line
/// ends at `\n`; a `\r` right before it is dropped; a last line with no line end is a line;
/// nothing else is trimmed. A UTF-8 byte-order mark at the start is not part of line 1, and a
/// file of nothing but one is no line. Invalid bytes become U+FFFD.
fn read_batches(file: File, sender: &std::sync::mpsc::SyncSender<std::io::Result<LineBatch>>) {
    let mut reader = BufReader::with_capacity(1 << 20, file);
    let mut batch: LineBatch = Vec::with_capacity(BATCH_LINES);
    let mut batch_bytes = 0usize;
    let mut number = 0usize;
    loop {
        let mut line: Vec<u8> = Vec::new();
        match reader.read_until(b'\n', &mut line) {
            Err(e) => {
                let _ = sender.send(Err(e));
                return;
            }
            Ok(0) => break,
            Ok(_) => {}
        }
        if number == 0 && line.starts_with(UTF8_BOM) {
            line.drain(..UTF8_BOM.len());
        }
        if line.last() == Some(&b'\n') {
            line.pop();
            if line.last() == Some(&b'\r') {
                line.pop();
            }
        } else if line.is_empty() {
            break;
        }
        number += 1;
        let text = String::from_utf8(line)
            .unwrap_or_else(|e| String::from_utf8_lossy(e.as_bytes()).into_owned());
        batch_bytes += text.len();
        batch.push((number, text));
        if batch.len() == BATCH_LINES || batch_bytes >= BATCH_BYTES {
            batch_bytes = 0;
            let full = std::mem::replace(&mut batch, Vec::with_capacity(BATCH_LINES));
            if sender.send(Ok(full)).is_err() {
                return;
            }
        }
    }
    if !batch.is_empty() {
        let _ = sender.send(Ok(batch));
    }
}

/// Parse a batch of numbered lines in parallel and append the entries, in order, to `entries`.
fn parse_batch(
    parser: &crate::parser::LogParser,
    batch: &mut LineBatch,
    entries: &mut Vec<LogEntry>,
) {
    let parsed: Vec<LogEntry> = batch
        .par_iter()
        .filter_map(|(line_number, line)| parser.parse_line(*line_number, line).ok())
        .collect();
    batch.clear();
    entries.extend(parsed);
}

/// Line numbers by key, for the entries that have a key; each list ascends because `entries`
/// is in file order.
fn index_by<K, F>(entries: &[LogEntry], key: F) -> HashMap<K, Vec<usize>>
where
    K: std::hash::Hash + Eq + Clone,
    F: for<'e> Fn(&'e LogEntry) -> Option<&'e K>,
{
    let mut map: HashMap<K, Vec<usize>> = HashMap::new();
    for entry in entries {
        if let Some(k) = key(entry) {
            match map.get_mut(k) {
                Some(lines) => lines.push(entry.line_number),
                None => {
                    map.insert(k.clone(), vec![entry.line_number]);
                }
            }
        }
    }
    map
}

/// In-memory log file index for fast searching
#[derive(Debug)]
pub struct LogIndex {
    /// File path
    pub file_path: String,
    /// Number of lines in the file (every line, whether or not it parsed)
    pub total_lines: usize,
    /// Thread ID -> line numbers
    pub thread_index: HashMap<String, Vec<usize>>,
    /// Correlation ID -> line numbers
    pub correlation_index: HashMap<String, Vec<usize>>,
    /// Trace ID -> line numbers
    pub trace_index: HashMap<String, Vec<usize>>,
    /// Log level -> line numbers
    pub level_index: HashMap<LogLevel, Vec<usize>>,
    /// Service name -> line numbers
    pub service_index: HashMap<String, Vec<usize>>,
    /// All parsed entries, in file order (ascending line number)
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

        // One pass over the file, in file order. Lines are cut on bytes and decoded lossily;
        // they are parsed in parallel a batch at a time, and a batch is bounded in lines and
        // in bytes. `par_iter().collect()` keeps the batch's order.
        let file = File::open(path)?;
        let mut entries: Vec<LogEntry> = Vec::new();
        let mut total_lines = 0usize;
        // A reader thread cuts the file into batches of lines while this thread parses the
        // previous batch; the channel holds at most two, so memory stays bounded.
        let (sender, receiver) = std::sync::mpsc::sync_channel::<std::io::Result<LineBatch>>(2);
        std::thread::scope(|scope| {
            scope.spawn(move || read_batches(file, &sender));
            for batch in receiver {
                let mut batch = batch?;
                if let Some((last, _)) = batch.last() {
                    total_lines = *last;
                }
                parse_batch(&parser, &mut batch, &mut entries);
            }
            Ok::<(), std::io::Error>(())
        })?;

        // The five indexes are built side by side, each walking the entries in file order.
        let ((thread_index, correlation_index), (trace_index, (level_index, service_index))) =
            rayon::join(
                || {
                    rayon::join(
                        || index_by(&entries, |e| e.thread_id.as_ref()),
                        || index_by(&entries, |e| e.correlation_id.as_ref()),
                    )
                },
                || {
                    rayon::join(
                        || index_by(&entries, |e| e.trace_id.as_ref()),
                        || {
                            rayon::join(
                                || index_by(&entries, |e| e.level.as_ref()),
                                || index_by(&entries, |e| e.service_name.as_ref()),
                            )
                        },
                    )
                },
            );

        Ok(Self {
            file_path,
            total_lines,
            thread_index,
            correlation_index,
            trace_index,
            level_index,
            service_index,
            entries: Some(entries),
        })
    }

    /// Get entry by line number
    pub fn get_entry(&self, line_number: usize) -> Option<&LogEntry> {
        let entries = self.entries.as_ref()?;
        entries
            .binary_search_by_key(&line_number, |e| e.line_number)
            .ok()
            .map(|i| &entries[i])
    }

    /// Get entries by line numbers
    pub fn get_entries(&self, line_numbers: &[usize]) -> Vec<LogEntry> {
        if let Some(entries) = &self.entries {
            line_numbers
                .iter()
                .filter_map(|ln| {
                    entries
                        .binary_search_by_key(ln, |e| e.line_number)
                        .ok()
                        .map(|i| entries[i].clone())
                })
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
        let end_line = line_number.saturating_add(after);

        // Entries are in file order, so each range is a slice. `upto(n)` is the position after
        // the last entry on line `n` or before it.
        let from = |line: usize| entries.partition_point(|e| e.line_number < line);
        let upto = |line: usize| entries.partition_point(|e| e.line_number <= line);
        let before_entries = entries[from(start_line)..from(line_number)].to_vec();
        let after_entries = entries[upto(line_number)..upto(end_line)].to_vec();

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
            total_lines: self.total_lines,
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

        assert_eq!(index.total_lines, 2);
        assert_eq!(index.thread_index.get("worker-1").unwrap().len(), 2);

        let stats = index.get_stats();
        assert_eq!(stats.total_lines, 2);
        assert_eq!(stats.unique_threads, 1);
    }

    fn index_of(bytes: &[u8]) -> LogIndex {
        let mut file = NamedTempFile::new().unwrap();
        file.write_all(bytes).unwrap();
        file.flush().unwrap();
        LogIndex::build(file.path()).unwrap()
    }

    #[test]
    fn context_with_more_lines_asked_than_any_file_has_is_the_rest_of_the_file() {
        let index = index_of(b"one\ntwo\nthree\nfour\n");
        let lines = |entries: Vec<LogEntry>| -> Vec<usize> {
            entries.iter().map(|e| e.line_number).collect()
        };

        let (before, after) = index.get_context(2, usize::MAX, usize::MAX);
        assert_eq!(lines(before), vec![1]);
        assert_eq!(lines(after), vec![3, 4]);

        let (before, after) = index.get_context(usize::MAX, 1, 1);
        assert_eq!(lines(before), Vec::<usize>::new());
        assert_eq!(lines(after), Vec::<usize>::new());
    }

    fn raws(index: &LogIndex) -> Vec<(usize, String)> {
        index
            .entries
            .as_ref()
            .unwrap()
            .iter()
            .map(|e| (e.line_number, e.raw.clone()))
            .collect()
    }

    #[test]
    fn bytes_that_are_not_utf8_become_replacement_characters() {
        let cases: [(&[u8], &str); 6] = [
            (b"caf\xe9 x", "caf\u{fffd} x"),
            (b"a\x80b", "a\u{fffd}b"),
            (b"a\xe2\x82 b", "a\u{fffd} b"),
            (b"a\xc0\xafb", "a\u{fffd}\u{fffd}b"),
            (b"a\xf5b", "a\u{fffd}b"),
            (b"a\x00b", "a\x00b"),
        ];
        for (bytes, expected) in cases {
            let mut data = b"one\n".to_vec();
            data.extend_from_slice(bytes);
            data.extend_from_slice(b"\nthree\n");
            let index = index_of(&data);
            assert_eq!(
                raws(&index),
                vec![(1, "one".into()), (2, expected.into()), (3, "three".into())]
            );
            assert_eq!(index.total_lines, 3);
        }
    }

    #[test]
    fn a_character_cut_off_at_the_end_of_the_file_is_one_replacement() {
        let index = index_of(b"one\nend\xe2\x82");
        assert_eq!(
            raws(&index),
            vec![(1, "one".into()), (2, "end\u{fffd}".into())]
        );
    }

    #[test]
    fn lines_are_cut_on_bytes_and_nothing_else_is_trimmed() {
        let index = index_of(b"a  \r\n\n   \nb\rc\nlast");
        assert_eq!(
            raws(&index),
            vec![
                (1, "a  ".into()),
                (2, "".into()),
                (3, "   ".into()),
                (4, "b\rc".into()),
                (5, "last".into()),
            ]
        );
        assert_eq!(index.total_lines, 5);
    }

    #[test]
    fn an_empty_file_has_no_lines_and_a_file_ending_in_a_newline_has_no_extra_one() {
        assert_eq!(index_of(b"").total_lines, 0);
        assert!(index_of(b"").entries.unwrap().is_empty());
        assert_eq!(index_of(b"x\n").total_lines, 1);
        assert_eq!(index_of(b"x").total_lines, 1);
    }

    #[test]
    fn a_byte_order_mark_is_not_part_of_line_one() {
        let index = index_of(b"\xef\xbb\xbf{\"level\":\"ERROR\",\"message\":\"m\"}\nx\n");
        let entries = index.entries.as_ref().unwrap();
        assert_eq!(entries[0].raw, "{\"level\":\"ERROR\",\"message\":\"m\"}");
        assert_eq!(entries[0].message, "m");
        assert_eq!(entries[0].level, Some(LogLevel::Error));
        assert_eq!(index_of(b"\xef\xbb\xbf").total_lines, 0);
        assert_eq!(index_of(b"\xef\xbb\xbf\n").total_lines, 1);
    }

    #[test]
    fn long_lines_are_sent_in_batches_bounded_by_bytes() {
        // 24 lines of an eighth of BATCH_BYTES each: far fewer than BATCH_LINES.
        let line = vec![b'x'; BATCH_BYTES / 8];
        let mut file = NamedTempFile::new().unwrap();
        for _ in 0..24 {
            file.write_all(&line).unwrap();
            file.write_all(b"\n").unwrap();
        }
        file.flush().unwrap();

        let (sender, receiver) = std::sync::mpsc::sync_channel(32);
        read_batches(File::open(file.path()).unwrap(), &sender);
        drop(sender);
        let lines_per_batch: Vec<usize> = receiver.iter().map(|b| b.unwrap().len()).collect();
        assert_eq!(lines_per_batch, vec![8, 8, 8]);
    }

    #[test]
    fn entries_context_and_lookups_are_in_file_order() {
        let mut data = Vec::new();
        // More than one batch, so the order is checked across batch borders.
        let n = BATCH_LINES * 3 + 11;
        for i in 1..=n {
            data.extend_from_slice(
                format!("2024-01-15 10:00:00 INFO [t-{}] line {}\n", i % 5, i).as_bytes(),
            );
        }
        let index = index_of(&data);
        let numbers: Vec<usize> = index
            .entries
            .as_ref()
            .unwrap()
            .iter()
            .map(|e| e.line_number)
            .collect();
        assert_eq!(numbers, (1..=n).collect::<Vec<_>>());
        let just_past_a_batch = BATCH_LINES + 1;
        assert_eq!(
            index.get_entry(just_past_a_batch).unwrap().raw,
            format!(
                "2024-01-15 10:00:00 INFO [t-{}] line {}",
                just_past_a_batch % 5,
                just_past_a_batch
            )
        );
        assert!(index.get_entry(n + 1).is_none());
        assert!(index.get_entry(0).is_none());

        let (before, after) = index.get_context(BATCH_LINES, 3, 3);
        let b: Vec<usize> = before.iter().map(|e| e.line_number).collect();
        let a: Vec<usize> = after.iter().map(|e| e.line_number).collect();
        assert_eq!(b, vec![BATCH_LINES - 3, BATCH_LINES - 2, BATCH_LINES - 1]);
        assert_eq!(a, vec![BATCH_LINES + 1, BATCH_LINES + 2, BATCH_LINES + 3]);
        let (before, after) = index.get_context(2, 5, 1);
        assert_eq!(before.len(), 1);
        assert_eq!(after.len(), 1);

        let thread = index.thread_index.get("t-3").unwrap();
        assert_eq!(*thread, (3..=n).step_by(5).collect::<Vec<_>>());
        let got: Vec<usize> = index
            .get_thread_entries("t-3")
            .iter()
            .map(|e| e.line_number)
            .collect();
        assert_eq!(got, *thread);
    }
}
