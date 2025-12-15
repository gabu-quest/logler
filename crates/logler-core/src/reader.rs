use crate::parser::LogParser;
use crate::types::LogEntry;
use anyhow::{Context, Result};
use futures::pin_mut;
use std::path::PathBuf;
use tokio::fs::File;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio_stream::Stream;
use tokio_stream::StreamExt;

/// Async log reader with streaming and tail support.
pub struct LogReader {
    path: PathBuf,
    parser: LogParser,
}

impl LogReader {
    pub fn new(path: PathBuf) -> Self {
        Self {
            parser: LogParser::new(path.to_string_lossy()),
            path,
        }
    }

    pub fn with_parser(path: PathBuf, parser: LogParser) -> Self {
        Self { path, parser }
    }

    /// Read all log entries from the file.
    pub async fn read_all(&self) -> Result<Vec<LogEntry>> {
        let mut entries = Vec::new();
        let stream = self.stream().await?;
        pin_mut!(stream);

        while let Some(entry) = stream.next().await {
            entries.push(entry?);
        }

        Ok(entries)
    }

    /// Stream log entries from the file.
    pub async fn stream(&self) -> Result<impl Stream<Item = Result<LogEntry>>> {
        let file = File::open(&self.path)
            .await
            .with_context(|| format!("Failed to open file: {:?}", self.path))?;

        let reader = BufReader::new(file);
        let mut lines = reader.lines();
        let parser = self.parser.clone();

        let mut line_number = 0;

        Ok(async_stream::stream! {
            while let Ok(Some(line)) = lines.next_line().await {
                line_number += 1;
                let entry = parser.parse_line(line_number, &line)?;
                yield Ok(entry);
            }
        })
    }

    /// Read last N entries.
    pub async fn tail(&self, n: usize) -> Result<Vec<LogEntry>> {
        let all_entries = self.read_all().await?;
        let start = all_entries.len().saturating_sub(n);
        Ok(all_entries[start..].to_vec())
    }

    /// Read first N entries.
    pub async fn head(&self, n: usize) -> Result<Vec<LogEntry>> {
        let mut entries = Vec::new();
        let stream = self.stream().await?;
        pin_mut!(stream);
        let mut count = 0;

        while let Some(entry) = stream.next().await {
            entries.push(entry?);
            count += 1;
            if count >= n {
                break;
            }
        }

        Ok(entries)
    }
}
