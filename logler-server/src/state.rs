use dashmap::DashMap;
use logler_core::{LogEntry, ThreadTracker};
use std::path::PathBuf;
use std::sync::Arc;
use uuid::Uuid;

#[derive(Clone)]
pub struct AppState {
    /// Currently opened log files
    pub open_files: Arc<DashMap<Uuid, PathBuf>>,
    /// Cached log entries
    pub log_entries: Arc<DashMap<Uuid, Vec<LogEntry>>>,
    /// Thread tracker for correlation
    pub thread_tracker: Arc<ThreadTracker>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            open_files: Arc::new(DashMap::new()),
            log_entries: Arc::new(DashMap::new()),
            thread_tracker: Arc::new(ThreadTracker::new()),
        }
    }
}
