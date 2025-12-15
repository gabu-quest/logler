use crate::types::LogEntry;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraceExporter {
    pub endpoint: String,
    pub service_name: String,
}

impl TraceExporter {
    pub fn new(endpoint: String, service_name: String) -> Self {
        Self {
            endpoint,
            service_name,
        }
    }

    /// Export a log entry as an OpenTelemetry trace (placeholder).
    pub async fn export(&self, _entry: &LogEntry) -> anyhow::Result<()> {
        // TODO: Implement OTLP export if needed.
        Ok(())
    }
}
