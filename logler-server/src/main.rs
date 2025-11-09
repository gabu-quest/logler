mod api;
mod file_watcher;
mod state;

use anyhow::Result;
use axum::{
    routing::{get, post},
    Router,
};
use std::net::SocketAddr;
use tower_http::cors::CorsLayer;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

use crate::state::AppState;

#[tokio::main]
async fn main() -> Result<()> {
    // Initialize tracing
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "logler_server=debug,logler_core=debug,tower_http=debug".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    tracing::info!("Starting logler server...");

    // Create application state
    let state = AppState::new();

    // Build our application with routes
    let app = Router::new()
        .route("/health", get(api::health))
        .route("/api/files", get(api::list_files))
        .route("/api/files/open", post(api::open_file))
        .route("/api/logs", get(api::get_logs))
        .route("/api/logs/search", post(api::search_logs))
        .route("/api/logs/filter", post(api::filter_logs))
        .route("/api/logs/stats", get(api::get_stats))
        .route("/api/threads", get(api::get_threads))
        .route("/api/threads/:thread_id", get(api::get_thread))
        .route("/api/traces", get(api::get_traces))
        .route("/api/traces/:trace_id", get(api::get_trace))
        .route("/api/correlations", get(api::get_correlations))
        .route("/api/correlations/:correlation_id", get(api::get_correlation_logs))
        .route("/ws", get(api::websocket_handler))
        .layer(CorsLayer::permissive())
        .with_state(state);

    // Run the server
    let addr = SocketAddr::from(([0, 0, 0, 0], 3000));
    tracing::info!("Listening on {}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
