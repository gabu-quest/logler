use axum::{
    extract::{Path, Query, State, WebSocketUpgrade},
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use axum::extract::ws::{Message, WebSocket};
use futures::{sink::SinkExt, stream::StreamExt};
use logler_core::{LogFilter, LogReader, LogStats};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use uuid::Uuid;

use crate::state::AppState;

// Health check
pub async fn health() -> &'static str {
    "OK"
}

#[derive(Deserialize)]
pub struct OpenFileRequest {
    pub path: String,
}

#[derive(Serialize)]
pub struct OpenFileResponse {
    pub file_id: Uuid,
    pub path: String,
}

// Open a log file
pub async fn open_file(
    State(state): State<AppState>,
    Json(req): Json<OpenFileRequest>,
) -> Result<Json<OpenFileResponse>, AppError> {
    let path = PathBuf::from(&req.path);

    if !path.exists() {
        return Err(AppError::NotFound("File not found".to_string()));
    }

    let reader = LogReader::new(path.clone());
    let entries = reader.read_all().await?;

    // Track all entries
    for entry in &entries {
        state.thread_tracker.track(entry);
    }

    let file_id = Uuid::new_v4();
    state.open_files.insert(file_id, path.clone());
    state.log_entries.insert(file_id, entries);

    Ok(Json(OpenFileResponse {
        file_id,
        path: req.path,
    }))
}

#[derive(Deserialize)]
pub struct ListFilesQuery {
    pub directory: Option<String>,
}

#[derive(Serialize)]
pub struct FileInfo {
    pub path: String,
    pub size: u64,
}

// List log files in a directory
pub async fn list_files(
    Query(query): Query<ListFilesQuery>,
) -> Result<Json<Vec<FileInfo>>, AppError> {
    let dir = query.directory.unwrap_or_else(|| ".".to_string());
    let path = PathBuf::from(dir);

    let mut files = Vec::new();

    if let Ok(entries) = std::fs::read_dir(path) {
        for entry in entries.flatten() {
            if let Ok(metadata) = entry.metadata() {
                if metadata.is_file() {
                    if let Some(path_str) = entry.path().to_str() {
                        if path_str.ends_with(".log") || path_str.contains("log") {
                            files.push(FileInfo {
                                path: path_str.to_string(),
                                size: metadata.len(),
                            });
                        }
                    }
                }
            }
        }
    }

    Ok(Json(files))
}

#[derive(Deserialize)]
pub struct GetLogsQuery {
    pub file_id: Uuid,
    pub offset: Option<usize>,
    pub limit: Option<usize>,
}

// Get logs from an opened file
pub async fn get_logs(
    State(state): State<AppState>,
    Query(query): Query<GetLogsQuery>,
) -> Result<Json<Vec<logler_core::LogEntry>>, AppError> {
    let entries = state
        .log_entries
        .get(&query.file_id)
        .ok_or_else(|| AppError::NotFound("File not found".to_string()))?;

    let offset = query.offset.unwrap_or(0);
    let limit = query.limit.unwrap_or(100);

    let result = entries
        .iter()
        .skip(offset)
        .take(limit)
        .cloned()
        .collect();

    Ok(Json(result))
}

// Search logs
pub async fn search_logs(
    State(state): State<AppState>,
    Json(req): Json<SearchRequest>,
) -> Result<Json<Vec<logler_core::LogEntry>>, AppError> {
    let entries = state
        .log_entries
        .get(&req.file_id)
        .ok_or_else(|| AppError::NotFound("File not found".to_string()))?;

    let result = entries
        .iter()
        .filter(|entry| {
            entry.message.contains(&req.query)
                || entry.raw.contains(&req.query)
        })
        .take(req.limit.unwrap_or(100))
        .cloned()
        .collect();

    Ok(Json(result))
}

#[derive(Deserialize)]
pub struct SearchRequest {
    pub file_id: Uuid,
    pub query: String,
    pub limit: Option<usize>,
}

// Filter logs
pub async fn filter_logs(
    State(state): State<AppState>,
    Json(filter): Json<FilterRequest>,
) -> Result<Json<Vec<logler_core::LogEntry>>, AppError> {
    let entries = state
        .log_entries
        .get(&filter.file_id)
        .ok_or_else(|| AppError::NotFound("File not found".to_string()))?;

    let log_filter = LogFilter {
        levels: filter.levels,
        pattern: filter.pattern,
        regex: filter.regex,
        thread_id: filter.thread_id,
        correlation_id: filter.correlation_id,
        trace_id: filter.trace_id,
        service_name: filter.service_name,
        time_start: filter.time_start,
        time_end: filter.time_end,
    };

    let result = entries
        .iter()
        .filter(|entry| log_filter.matches(entry))
        .cloned()
        .collect();

    Ok(Json(result))
}

#[derive(Deserialize)]
pub struct FilterRequest {
    pub file_id: Uuid,
    pub levels: Option<Vec<logler_core::LogLevel>>,
    pub pattern: Option<String>,
    pub regex: Option<String>,
    pub thread_id: Option<String>,
    pub correlation_id: Option<String>,
    pub trace_id: Option<String>,
    pub service_name: Option<String>,
    pub time_start: Option<chrono::DateTime<chrono::Utc>>,
    pub time_end: Option<chrono::DateTime<chrono::Utc>>,
}

// Get statistics
pub async fn get_stats(
    State(state): State<AppState>,
    Query(query): Query<GetLogsQuery>,
) -> Result<Json<LogStats>, AppError> {
    let entries = state
        .log_entries
        .get(&query.file_id)
        .ok_or_else(|| AppError::NotFound("File not found".to_string()))?;

    let stats = LogStats::compute(&entries);
    Ok(Json(stats))
}

// Get all threads
pub async fn get_threads(
    State(state): State<AppState>,
) -> Result<Json<Vec<logler_core::types::ThreadContext>>, AppError> {
    let threads = state.thread_tracker.get_all_threads();
    Ok(Json(threads))
}

// Get thread by ID
pub async fn get_thread(
    State(state): State<AppState>,
    Path(thread_id): Path<String>,
) -> Result<Json<logler_core::types::ThreadContext>, AppError> {
    state
        .thread_tracker
        .get_thread(&thread_id)
        .map(Json)
        .ok_or_else(|| AppError::NotFound("Thread not found".to_string()))
}

// Get all traces
pub async fn get_traces(
    State(state): State<AppState>,
) -> Result<Json<Vec<logler_core::types::TraceContext>>, AppError> {
    let traces = state.thread_tracker.get_all_traces();
    Ok(Json(traces))
}

// Get trace by ID
pub async fn get_trace(
    State(state): State<AppState>,
    Path(trace_id): Path<String>,
) -> Result<Json<logler_core::types::TraceContext>, AppError> {
    state
        .thread_tracker
        .get_trace(&trace_id)
        .map(Json)
        .ok_or_else(|| AppError::NotFound("Trace not found".to_string()))
}

// Get all correlation IDs
pub async fn get_correlations(
    State(state): State<AppState>,
) -> Result<Json<Vec<String>>, AppError> {
    let correlations = state.thread_tracker.get_all_correlations();
    Ok(Json(correlations))
}

// Get logs by correlation ID
pub async fn get_correlation_logs(
    State(state): State<AppState>,
    Path(correlation_id): Path<String>,
    Query(query): Query<GetLogsQuery>,
) -> Result<Json<Vec<logler_core::LogEntry>>, AppError> {
    let log_ids = state
        .thread_tracker
        .get_by_correlation(&correlation_id)
        .ok_or_else(|| AppError::NotFound("Correlation ID not found".to_string()))?;

    let entries = state
        .log_entries
        .get(&query.file_id)
        .ok_or_else(|| AppError::NotFound("File not found".to_string()))?;

    let result = entries
        .iter()
        .filter(|entry| log_ids.contains(&entry.id))
        .cloned()
        .collect();

    Ok(Json(result))
}

// WebSocket handler for real-time log streaming
pub async fn websocket_handler(
    ws: WebSocketUpgrade,
    State(state): State<AppState>,
) -> Response {
    ws.on_upgrade(move |socket| handle_socket(socket, state))
}

async fn handle_socket(socket: WebSocket, state: AppState) {
    let (mut sender, mut receiver) = socket.split();

    // Handle incoming messages
    let mut recv_task = tokio::spawn(async move {
        while let Some(Ok(msg)) = receiver.next().await {
            if let Message::Text(text) = msg {
                tracing::debug!("Received WebSocket message: {}", text);
                // Handle commands from client (e.g., subscribe to file)
            } else if let Message::Close(_) = msg {
                break;
            }
        }
    });

    // Send updates (simplified - in real impl would watch files)
    let mut send_task = tokio::spawn(async move {
        // Placeholder for real-time updates
        loop {
            tokio::time::sleep(tokio::time::Duration::from_secs(1)).await;

            // In a real implementation, we would:
            // 1. Watch files for changes
            // 2. Parse new lines
            // 3. Send them to the client

            if sender.send(Message::Text("heartbeat".to_string())).await.is_err() {
                break;
            }
        }
    });

    // If either task exits, abort the other
    tokio::select! {
        _ = (&mut send_task) => recv_task.abort(),
        _ = (&mut recv_task) => send_task.abort(),
    }
}

// Error handling
#[derive(Debug)]
pub enum AppError {
    NotFound(String),
    Internal(String),
}

impl From<anyhow::Error> for AppError {
    fn from(err: anyhow::Error) -> Self {
        AppError::Internal(err.to_string())
    }
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let (status, message) = match self {
            AppError::NotFound(msg) => (StatusCode::NOT_FOUND, msg),
            AppError::Internal(msg) => (StatusCode::INTERNAL_SERVER_ERROR, msg),
        };

        (status, Json(serde_json::json!({ "error": message }))).into_response()
    }
}
