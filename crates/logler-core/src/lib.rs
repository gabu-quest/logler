//! Logler Core - High-performance log parsing and investigation library
//!
//! This library provides fast log parsing, indexing, and investigation capabilities
//! designed for LLM agents. It supports multiple log formats (JSON, plain text, syslog),
//! thread/trace following, pattern detection, and statistical analysis.
//!
//! # Examples
//!
//! ```no_run
//! use logler_core::*;
//! use std::path::PathBuf;
//!
//! // Create investigator and load files
//! let mut investigator = Investigator::new();
//! investigator.load_files(&[PathBuf::from("app.log")]).unwrap();
//!
//! // Search for errors
//! let query = SearchQuery {
//!     files: vec![PathBuf::from("app.log")],
//!     query: Some("database timeout".to_string()),
//!     filters: SearchFilters {
//!         levels: vec![LogLevel::Error],
//!         ..Default::default()
//!     },
//!     limit: Some(10),
//!     context_lines: Some(3),
//! };
//!
//! let results = investigator.search(&query).unwrap();
//! println!("Found {} errors", results.total_matches);
//! ```

pub mod filter;
pub mod hierarchy;
pub mod index;
pub mod investigate;
pub mod parser;
#[cfg(feature = "async")]
pub mod reader;
pub mod stats;
pub mod thread_tracker;
pub mod trace;
pub mod types;

#[cfg(feature = "sql")]
pub mod sql;

pub use filter::LogFilter;
pub use index::{IndexStats, LogIndex};
pub use investigate::Investigator;
pub use parser::{LogParser, ParserConfig};
#[cfg(feature = "async")]
pub use reader::LogReader;
pub use stats::LogStats;
pub use thread_tracker::ThreadTracker;
pub use trace::TraceExporter;
pub use types::*;

#[cfg(feature = "sql")]
pub use sql::SqlEngine;

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn test_end_to_end() {
        // Create a test log file
        let mut temp_file = NamedTempFile::new().unwrap();
        writeln!(temp_file, r#"{{"timestamp":"2024-01-15T10:00:00Z","level":"ERROR","message":"Database connection failed","thread_id":"worker-1","correlation_id":"req-001"}}"#).unwrap();
        writeln!(temp_file, r#"{{"timestamp":"2024-01-15T10:00:01Z","level":"INFO","message":"Retrying connection","thread_id":"worker-1","correlation_id":"req-001"}}"#).unwrap();
        writeln!(temp_file, r#"{{"timestamp":"2024-01-15T10:00:02Z","level":"INFO","message":"Connection successful","thread_id":"worker-1","correlation_id":"req-001"}}"#).unwrap();
        temp_file.flush().unwrap();

        // Create investigator and load file
        let mut investigator = Investigator::new();
        investigator
            .load_files(&[temp_file.path().to_path_buf()])
            .unwrap();

        // Search for errors
        let query = SearchQuery {
            files: vec![temp_file.path().to_path_buf()],
            query: Some("database".to_string()),
            filters: SearchFilters {
                levels: vec![LogLevel::Error],
                ..Default::default()
            },
            limit: Some(10),
            context_lines: Some(1),
        };

        let results = investigator.search(&query).unwrap();
        assert_eq!(results.total_matches, 1);
        assert_eq!(
            results.results[0].entry.message,
            "Database connection failed"
        );
        assert_eq!(results.results[0].context_after.len(), 1);

        // Follow thread
        let timeline = investigator
            .follow_thread(
                &[temp_file.path().to_path_buf()],
                Some("worker-1".to_string()),
                None,
                None,
            )
            .unwrap();

        assert_eq!(timeline.total_entries, 3);
        assert!(timeline.duration_ms.is_some());
        assert!(timeline.duration_ms.unwrap() >= 2000); // At least 2 seconds
    }
}
