use logler_core::{LogParser, LogFilter, LogStats, ThreadTracker};

#[tokio::test]
async fn test_parse_json_log() {
    let parser = LogParser::new();
    let raw = r#"{"timestamp": "2024-01-15T10:00:00Z", "level": "INFO", "message": "Test", "thread_id": "worker-1"}"#;

    let entry = parser.parse(1, raw.to_string());

    assert_eq!(entry.line_number, 1);
    assert_eq!(entry.message, "Test");
    assert_eq!(entry.thread_id, Some("worker-1".to_string()));
}

#[tokio::test]
async fn test_parse_plain_log() {
    let parser = LogParser::new();
    let raw = "2024-01-15 10:00:00 ERROR [worker-1] Database connection failed";

    let entry = parser.parse(1, raw.to_string());

    assert_eq!(entry.line_number, 1);
    assert!(entry.message.contains("Database connection failed"));
}

#[tokio::test]
async fn test_thread_tracker() {
    let tracker = ThreadTracker::new();
    let parser = LogParser::new();

    // Create log entries with same thread ID
    let entry1 = parser.parse(1, r#"{"thread_id": "worker-1", "level": "INFO", "message": "Start"}"#.to_string());
    let entry2 = parser.parse(2, r#"{"thread_id": "worker-1", "level": "ERROR", "message": "Error"}"#.to_string());

    tracker.track(&entry1);
    tracker.track(&entry2);

    let thread_ctx = tracker.get_thread("worker-1").unwrap();
    assert_eq!(thread_ctx.log_count, 2);
    assert_eq!(thread_ctx.error_count, 1);
}

#[tokio::test]
async fn test_log_filter() {
    let parser = LogParser::new();
    let entry = parser.parse(1, r#"{"level": "ERROR", "message": "Test error"}"#.to_string());

    let mut filter = LogFilter::new();
    filter.levels = Some(vec![logler_core::types::LogLevel::Error]);

    assert!(filter.matches(&entry));

    filter.levels = Some(vec![logler_core::types::LogLevel::Info]);
    assert!(!filter.matches(&entry));
}

#[tokio::test]
async fn test_log_stats() {
    let parser = LogParser::new();
    let entries = vec![
        parser.parse(1, r#"{"level": "INFO", "message": "Test 1"}"#.to_string()),
        parser.parse(2, r#"{"level": "ERROR", "message": "Test 2"}"#.to_string()),
        parser.parse(3, r#"{"level": "INFO", "message": "Test 3"}"#.to_string()),
    ];

    let stats = LogStats::compute(&entries);

    assert_eq!(stats.total_count, 3);
    assert!(stats.error_rate > 0.0);
}
