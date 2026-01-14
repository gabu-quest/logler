use crate::types::{LogEntry, SpanInfo, ThreadContext, TraceContext};
use chrono::Utc;
use dashmap::DashMap;
use std::sync::Arc;
use uuid::Uuid;

/// Thread tracker for correlating logs by thread/correlation/trace IDs.
#[derive(Clone)]
pub struct ThreadTracker {
    threads: Arc<DashMap<String, ThreadContext>>,
    traces: Arc<DashMap<String, TraceContext>>,
    correlations: Arc<DashMap<String, Vec<Uuid>>>, // correlation_id -> log IDs
}

impl ThreadTracker {
    pub fn new() -> Self {
        Self {
            threads: Arc::new(DashMap::new()),
            traces: Arc::new(DashMap::new()),
            correlations: Arc::new(DashMap::new()),
        }
    }

    /// Track a log entry and update thread/trace contexts.
    pub fn track(&self, entry: &LogEntry) {
        // Track by thread ID
        if let Some(thread_id) = &entry.thread_id {
            self.track_thread(thread_id.clone(), entry);
        }

        // Track by correlation ID
        if let Some(correlation_id) = &entry.correlation_id {
            self.correlations
                .entry(correlation_id.clone())
                .or_default()
                .push(entry.id);
        }

        // Track by trace ID
        if let Some(trace_id) = &entry.trace_id {
            self.track_trace(trace_id.clone(), entry);
        }
    }

    fn track_thread(&self, thread_id: String, entry: &LogEntry) {
        let timestamp = entry.timestamp.unwrap_or_else(Utc::now);
        let is_error = matches!(
            entry.level,
            Some(crate::types::LogLevel::Error | crate::types::LogLevel::Fatal)
        );

        self.threads
            .entry(thread_id)
            .and_modify(|ctx| {
                ctx.last_seen = timestamp;
                ctx.log_count += 1;
                if is_error {
                    ctx.error_count += 1;
                }
                if let Some(corr_id) = &entry.correlation_id {
                    if !ctx.correlation_ids.contains(corr_id) {
                        ctx.correlation_ids.push(corr_id.clone());
                    }
                }
            })
            .or_insert_with(|| ThreadContext {
                thread_id: entry.thread_id.clone().unwrap_or_default(),
                first_seen: timestamp,
                last_seen: timestamp,
                log_count: 1,
                error_count: if is_error { 1 } else { 0 },
                correlation_ids: entry
                    .correlation_id
                    .as_ref()
                    .map(|id| vec![id.clone()])
                    .unwrap_or_default(),
            });
    }

    fn track_trace(&self, trace_id: String, entry: &LogEntry) {
        let timestamp = entry.timestamp.unwrap_or_else(Utc::now);

        self.traces
            .entry(trace_id.clone())
            .and_modify(|ctx| {
                if let Some(service) = &entry.service_name {
                    if !ctx.services.contains(service) {
                        ctx.services.push(service.clone());
                    }
                }

                // Track span
                if let Some(span_id) = &entry.span_id {
                    if let Some(span) = ctx.spans.iter_mut().find(|s| s.span_id == *span_id) {
                        span.logs.push(entry.id);
                        if let Some(end_time) = entry.timestamp {
                            if span.end_time.is_none() || span.end_time.unwrap() < end_time {
                                span.end_time = Some(end_time);
                                if let Some(duration) = span.end_time.map(|end| {
                                    end.signed_duration_since(span.start_time)
                                        .num_milliseconds()
                                        as f64
                                }) {
                                    span.duration_ms = Some(duration);
                                }
                            }
                        }
                    } else {
                        ctx.spans.push(SpanInfo {
                            span_id: span_id.clone(),
                            parent_span_id: entry.parent_span_id.clone(),
                            operation_name: entry
                                .fields
                                .get("operation")
                                .and_then(|v| v.as_str())
                                .map(String::from),
                            start_time: timestamp,
                            end_time: None,
                            duration_ms: None,
                            logs: vec![entry.id],
                        });
                    }
                }

                // Update trace end time
                if ctx.end_time.is_none() || ctx.end_time.unwrap() < timestamp {
                    ctx.end_time = Some(timestamp);
                    ctx.duration_ms = Some(
                        ctx.end_time
                            .unwrap()
                            .signed_duration_since(ctx.start_time)
                            .num_milliseconds() as f64,
                    );
                }
            })
            .or_insert_with(|| TraceContext {
                trace_id,
                spans: if let Some(span_id) = &entry.span_id {
                    vec![SpanInfo {
                        span_id: span_id.clone(),
                        parent_span_id: entry.parent_span_id.clone(),
                        operation_name: entry
                            .fields
                            .get("operation")
                            .and_then(|v| v.as_str())
                            .map(String::from),
                        start_time: timestamp,
                        end_time: None,
                        duration_ms: None,
                        logs: vec![entry.id],
                    }]
                } else {
                    Vec::new()
                },
                services: entry
                    .service_name
                    .as_ref()
                    .map(|s| vec![s.clone()])
                    .unwrap_or_default(),
                start_time: timestamp,
                end_time: None,
                duration_ms: None,
            });
    }

    /// Get thread context by thread ID.
    pub fn get_thread(&self, thread_id: &str) -> Option<ThreadContext> {
        self.threads.get(thread_id).map(|ctx| ctx.clone())
    }

    /// Get all tracked threads.
    pub fn get_all_threads(&self) -> Vec<ThreadContext> {
        self.threads
            .iter()
            .map(|entry| entry.value().clone())
            .collect()
    }

    /// Get trace context by trace ID.
    pub fn get_trace(&self, trace_id: &str) -> Option<TraceContext> {
        self.traces.get(trace_id).map(|ctx| ctx.clone())
    }

    /// Get all traces.
    pub fn get_all_traces(&self) -> Vec<TraceContext> {
        self.traces
            .iter()
            .map(|entry| entry.value().clone())
            .collect()
    }

    /// Get log IDs by correlation ID.
    pub fn get_by_correlation(&self, correlation_id: &str) -> Option<Vec<Uuid>> {
        self.correlations.get(correlation_id).map(|ids| ids.clone())
    }

    /// Get all correlation IDs.
    pub fn get_all_correlations(&self) -> Vec<String> {
        self.correlations
            .iter()
            .map(|entry| entry.key().clone())
            .collect()
    }

    /// Clear all tracking data.
    pub fn clear(&self) {
        self.threads.clear();
        self.traces.clear();
        self.correlations.clear();
    }
}

impl Default for ThreadTracker {
    fn default() -> Self {
        Self::new()
    }
}
