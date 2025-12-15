use anyhow::anyhow;
use clap::{Parser, Subcommand};
use logler_core::{LogFilter, LogReader};
use std::path::PathBuf;

#[derive(Parser)]
#[command(name = "logler")]
#[command(about = "Advanced local log viewing tool", long_about = None)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// View a log file
    View {
        /// Path to the log file
        path: PathBuf,
        /// Number of lines to show
        #[arg(short = 'n', long)]
        lines: Option<usize>,
        /// Follow the log file
        #[arg(short, long)]
        follow: bool,
        /// Filter by log level
        #[arg(short, long)]
        level: Option<String>,
    },
    /// Search in log files
    Search {
        /// Path to the log file
        path: PathBuf,
        /// Search query
        query: String,
    },
    /// Show statistics
    Stats {
        /// Path to the log file
        path: PathBuf,
    },
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt::init();

    let cli = Cli::parse();

    match cli.command {
        Commands::View {
            path,
            lines,
            follow: _,
            level,
        } => {
            let reader = LogReader::new(path);
            let entries = if let Some(n) = lines {
                reader.tail(n).await?
            } else {
                reader.read_all().await?
            };

            // Apply level filter if specified
            let filtered: Vec<_> = if let Some(level_str) = level {
                let target_level = logler_core::types::LogLevel::from_str(&level_str)
                    .filter(|lvl| *lvl != logler_core::types::LogLevel::Unknown)
                    .ok_or_else(|| anyhow!("Unknown log level: {}", level_str))?;
                entries
                    .into_iter()
                    .filter(|e| e.level == Some(target_level))
                    .collect()
            } else {
                entries
            };

            // Print logs with colors
            for entry in filtered {
                println!("{}", format_log_entry(&entry));
            }
        }
        Commands::Search { path, query } => {
            let reader = LogReader::new(path);
            let entries = reader.read_all().await?;

            let mut filter = LogFilter::new();
            filter.pattern = Some(query);

            let results: Vec<_> = entries.into_iter().filter(|e| filter.matches(e)).collect();

            println!("Found {} matching entries:\n", results.len());
            for entry in results {
                println!("{}", format_log_entry(&entry));
            }
        }
        Commands::Stats { path } => {
            let reader = LogReader::new(path);
            let entries = reader.read_all().await?;
            let stats = logler_core::LogStats::compute(&entries);

            println!("Log Statistics:");
            println!("================");
            println!("Total entries: {}", stats.total_count);
            println!("\nBy level:");
            for (level, count) in &stats.level_counts {
                println!("  {}: {}", level, count);
            }
            println!("\nError rate: {:.2}%", stats.error_rate);
            if let Some(first) = stats.first_timestamp {
                println!("First entry: {}", first);
            }
            if let Some(last) = stats.last_timestamp {
                println!("Last entry: {}", last);
            }
        }
    }

    Ok(())
}

fn format_log_entry(entry: &logler_core::LogEntry) -> String {
    let level_str = entry
        .level
        .map(|lvl| lvl.as_str().to_string())
        .unwrap_or_else(|| "UNKNOWN".to_string());
    let timestamp = entry
        .timestamp
        .map(|t| t.to_rfc3339())
        .unwrap_or_else(|| "N/A".to_string());

    format!(
        "[{}] {} {} {}",
        entry.line_number, timestamp, level_str, entry.message
    )
}
