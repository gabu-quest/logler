use crate::index::LogIndex;
use crate::types::*;
use anyhow::Result;
use duckdb::{params, Connection};
use std::path::PathBuf;

/// SQL query engine for advanced log investigation
pub struct SqlEngine {
    conn: Connection,
}

impl SqlEngine {
    /// Create a new SQL engine
    pub fn new() -> Result<Self> {
        let conn = Connection::open_in_memory()?;
        Ok(Self { conn })
    }

    /// Load log files into SQL tables
    pub fn load_files(&mut self, indices: &std::collections::HashMap<String, LogIndex>) -> Result<()> {
        // Create logs table
        self.conn.execute(
            "CREATE TABLE logs (
                file TEXT,
                line_number INTEGER,
                timestamp TIMESTAMP,
                level TEXT,
                message TEXT,
                thread_id TEXT,
                correlation_id TEXT,
                trace_id TEXT,
                span_id TEXT,
                raw TEXT
            )",
            [],
        )?;

        // Insert entries from all indices
        for (file_path, index) in indices {
            if let Some(entries) = &index.entries {
                for entry in entries {
                    self.conn.execute(
                        "INSERT INTO logs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        params![
                            file_path,
                            entry.line_number as i64,
                            entry.timestamp.map(|t| t.to_rfc3339()),
                            entry.level.map(|l| l.as_str()),
                            &entry.message,
                            &entry.thread_id,
                            &entry.correlation_id,
                            &entry.trace_id,
                            &entry.span_id,
                            &entry.raw,
                        ],
                    )?;
                }
            }
        }

        Ok(())
    }

    /// Execute a SQL query and return results as JSON
    pub fn query(&self, sql: &str) -> Result<String> {
        let mut stmt = self.conn.prepare(sql)?;
        let column_count = stmt.column_count();
        let column_names: Vec<String> = stmt.column_names().into_iter().map(String::from).collect();

        let rows = stmt.query_map([], |row| {
            let mut obj = serde_json::Map::new();
            for i in 0..column_count {
                let col_name = &column_names[i];
                let value: serde_json::Value = match row.get_ref(i)? {
                    duckdb::types::ValueRef::Null => serde_json::Value::Null,
                    duckdb::types::ValueRef::Boolean(b) => serde_json::Value::Bool(b),
                    duckdb::types::ValueRef::TinyInt(i) => serde_json::json!(i),
                    duckdb::types::ValueRef::SmallInt(i) => serde_json::json!(i),
                    duckdb::types::ValueRef::Int(i) => serde_json::json!(i),
                    duckdb::types::ValueRef::BigInt(i) => serde_json::json!(i),
                    duckdb::types::ValueRef::HugeInt(i) => serde_json::json!(i),
                    duckdb::types::ValueRef::Float(f) => serde_json::json!(f),
                    duckdb::types::ValueRef::Double(f) => serde_json::json!(f),
                    duckdb::types::ValueRef::Text(s) => serde_json::Value::String(String::from_utf8_lossy(s).to_string()),
                    duckdb::types::ValueRef::Timestamp(_, _) => {
                        serde_json::Value::String(row.get::<_, String>(i)?)
                    }
                    _ => serde_json::Value::String(row.get::<_, String>(i)?),
                };
                obj.insert(col_name.clone(), value);
            }
            Ok(serde_json::Value::Object(obj))
        })?;

        let results: Vec<serde_json::Value> = rows.collect::<std::result::Result<_, _>>()?;
        Ok(serde_json::to_string(&results)?)
    }

    /// Get available tables
    pub fn get_tables(&self) -> Result<Vec<String>> {
        let mut stmt = self.conn.prepare("SELECT name FROM sqlite_master WHERE type='table'")?;
        let tables = stmt
            .query_map([], |row| row.get(0))?
            .collect::<std::result::Result<Vec<String>, _>>()?;
        Ok(tables)
    }

    /// Get table schema
    pub fn get_schema(&self, table: &str) -> Result<String> {
        let query = format!("PRAGMA table_info('{}')", table);
        self.query(&query)
    }
}

impl Default for SqlEngine {
    fn default() -> Self {
        Self::new().unwrap()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sql_query() {
        let mut engine = SqlEngine::new().unwrap();

        // Create test table
        engine.conn.execute(
            "CREATE TABLE test (id INTEGER, name TEXT)",
            [],
        ).unwrap();

        engine.conn.execute(
            "INSERT INTO test VALUES (1, 'foo')",
            [],
        ).unwrap();

        let result = engine.query("SELECT * FROM test").unwrap();
        assert!(result.contains("foo"));
    }
}
