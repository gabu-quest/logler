#![allow(non_local_definitions)]

use logler_core::*;
use pyo3::prelude::*;
use regex::Regex;
use std::path::PathBuf;

/// Python wrapper for Investigator
#[pyclass]
struct PyInvestigator {
    investigator: Investigator,
}

#[pymethods]
impl PyInvestigator {
    #[new]
    fn new() -> Self {
        Self {
            investigator: Investigator::new(),
        }
    }

    /// Load log files
    fn load_files(&mut self, files: Vec<String>) -> PyResult<()> {
        let paths: Vec<PathBuf> = files.iter().map(PathBuf::from).collect();
        self.investigator
            .load_files(&paths)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    /// Load log files with optional parser config (force_format/custom_regex)
    fn load_files_with_config(
        &mut self,
        files: Vec<String>,
        force_format: Option<String>,
        custom_regex: Option<String>,
    ) -> PyResult<()> {
        let paths: Vec<PathBuf> = files.iter().map(PathBuf::from).collect();

        let mut config = logler_core::ParserConfig::new();

        if let Some(format_str) = force_format.as_ref() {
            let fmt = parse_format_string(format_str)?;
            config = config.with_force_format(fmt);
        }

        if let Some(re) = custom_regex.as_ref() {
            let regex = Regex::new(re)
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
            config = config.with_custom_regex(regex);
        }

        self.investigator
            .load_files_with_config(&paths, &config)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    /// Search logs (input and output as JSON strings)
    fn search(&self, query_json: String) -> PyResult<String> {
        let query: SearchQuery = serde_json::from_str(&query_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;

        let results = self
            .investigator
            .search(&query)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        serde_json::to_string(&results)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    /// Follow thread
    fn follow_thread(
        &self,
        files: Vec<String>,
        thread_id: Option<String>,
        correlation_id: Option<String>,
        trace_id: Option<String>,
    ) -> PyResult<String> {
        let paths: Vec<PathBuf> = files.iter().map(PathBuf::from).collect();
        let timeline = self
            .investigator
            .follow_thread(&paths, thread_id, correlation_id, trace_id)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        serde_json::to_string(&timeline)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    /// Get context around a log entry
    fn get_context(
        &self,
        file: String,
        line_number: usize,
        lines_before: usize,
        lines_after: usize,
        include_related_threads: bool,
    ) -> PyResult<String> {
        let context = self
            .investigator
            .get_context(
                &file,
                line_number,
                lines_before,
                lines_after,
                include_related_threads,
            )
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        serde_json::to_string(&context)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    /// Find patterns
    fn find_patterns(&self, files: Vec<String>, min_occurrences: usize) -> PyResult<String> {
        let paths: Vec<PathBuf> = files.iter().map(PathBuf::from).collect();
        let patterns = self
            .investigator
            .find_patterns(&paths, min_occurrences)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        serde_json::to_string(&patterns)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    /// Get metadata
    fn get_metadata(&self, files: Vec<String>) -> PyResult<String> {
        let paths: Vec<PathBuf> = files.iter().map(PathBuf::from).collect();
        let metadata = self
            .investigator
            .get_metadata(&paths)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        serde_json::to_string(&metadata)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    /// Execute SQL query on loaded logs (requires 'sql' feature)
    #[cfg(feature = "sql")]
    fn sql_query(&self, query: String) -> PyResult<String> {
        self.investigator
            .sql_query(&query)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    /// Get available SQL tables (requires 'sql' feature)
    #[cfg(feature = "sql")]
    fn sql_tables(&self) -> PyResult<Vec<String>> {
        self.investigator
            .sql_tables()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    /// Get SQL table schema (requires 'sql' feature)
    #[cfg(feature = "sql")]
    fn sql_schema(&self, table: String) -> PyResult<String> {
        self.investigator
            .sql_schema(&table)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    /// Build hierarchical view of threads/spans
    fn build_hierarchy(
        &self,
        files: Vec<String>,
        root_identifier: String,
        max_depth: Option<usize>,
        use_naming_patterns: Option<bool>,
        use_temporal_inference: Option<bool>,
        min_confidence: Option<f64>,
    ) -> PyResult<String> {
        let paths: Vec<PathBuf> = files.iter().map(PathBuf::from).collect();

        let mut config = logler_core::hierarchy::HierarchyConfig::default();
        if let Some(depth) = max_depth {
            config.max_depth = depth;
        }
        if let Some(use_patterns) = use_naming_patterns {
            config.use_naming_patterns = use_patterns;
        }
        if let Some(use_temporal) = use_temporal_inference {
            config.use_temporal_inference = use_temporal;
        }
        if let Some(confidence) = min_confidence {
            config.min_confidence = confidence;
        }

        let hierarchy = self
            .investigator
            .build_hierarchy(&paths, &root_identifier, Some(config))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        serde_json::to_string(&hierarchy)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }
}

/// Standalone search function (convenience)
#[pyfunction]
fn search(files: Vec<String>, query: String, limit: Option<usize>) -> PyResult<String> {
    let paths: Vec<PathBuf> = files.iter().map(PathBuf::from).collect();
    let mut investigator = Investigator::new();
    investigator
        .load_files(&paths)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    let search_query = SearchQuery {
        files: paths,
        query: Some(query),
        filters: SearchFilters::default(),
        limit,
        context_lines: Some(3),
    };

    let results = investigator
        .search(&search_query)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    serde_json::to_string(&results)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
}

/// Standalone follow_thread function (convenience)
#[pyfunction]
fn follow_thread(
    files: Vec<String>,
    thread_id: Option<String>,
    correlation_id: Option<String>,
    trace_id: Option<String>,
) -> PyResult<String> {
    let paths: Vec<PathBuf> = files.iter().map(PathBuf::from).collect();
    let mut investigator = Investigator::new();
    investigator
        .load_files(&paths)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    let timeline = investigator
        .follow_thread(&paths, thread_id, correlation_id, trace_id)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    serde_json::to_string(&timeline)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
}

/// Standalone find_patterns function (convenience)
#[pyfunction]
fn find_patterns(files: Vec<String>, min_occurrences: Option<usize>) -> PyResult<String> {
    let paths: Vec<PathBuf> = files.iter().map(PathBuf::from).collect();
    let mut investigator = Investigator::new();
    investigator
        .load_files(&paths)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    let patterns = investigator
        .find_patterns(&paths, min_occurrences.unwrap_or(3))
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    serde_json::to_string(&patterns)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
}

/// Standalone get_metadata function (convenience)
#[pyfunction]
fn get_metadata(files: Vec<String>) -> PyResult<String> {
    let paths: Vec<PathBuf> = files.iter().map(PathBuf::from).collect();
    let mut investigator = Investigator::new();
    investigator
        .load_files(&paths)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    let metadata = investigator
        .get_metadata(&paths)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    serde_json::to_string(&metadata)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
}

/// Standalone build_hierarchy function (convenience)
#[pyfunction]
fn build_hierarchy(
    files: Vec<String>,
    root_identifier: String,
    max_depth: Option<usize>,
    use_naming_patterns: Option<bool>,
    use_temporal_inference: Option<bool>,
    min_confidence: Option<f64>,
) -> PyResult<String> {
    let paths: Vec<PathBuf> = files.iter().map(PathBuf::from).collect();
    let mut investigator = Investigator::new();
    investigator
        .load_files(&paths)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    let mut config = logler_core::hierarchy::HierarchyConfig::default();
    if let Some(depth) = max_depth {
        config.max_depth = depth;
    }
    if let Some(use_patterns) = use_naming_patterns {
        config.use_naming_patterns = use_patterns;
    }
    if let Some(use_temporal) = use_temporal_inference {
        config.use_temporal_inference = use_temporal;
    }
    if let Some(confidence) = min_confidence {
        config.min_confidence = confidence;
    }

    let hierarchy = investigator
        .build_hierarchy(&paths, &root_identifier, Some(config))
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    serde_json::to_string(&hierarchy)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
}

/// Python module
#[pymodule]
fn logler_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<PyInvestigator>()?;
    m.add_function(wrap_pyfunction!(search, m)?)?;
    m.add_function(wrap_pyfunction!(follow_thread, m)?)?;
    m.add_function(wrap_pyfunction!(find_patterns, m)?)?;
    m.add_function(wrap_pyfunction!(get_metadata, m)?)?;
    m.add_function(wrap_pyfunction!(build_hierarchy, m)?)?;
    Ok(())
}

fn parse_format_string(fmt: &str) -> PyResult<logler_core::LogFormat> {
    let fmt_lower = fmt.to_lowercase();
    match fmt_lower.as_str() {
        "json" => Ok(logler_core::LogFormat::Json),
        "plain" | "plaintext" | "text" => Ok(logler_core::LogFormat::PlainText),
        "syslog" => Ok(logler_core::LogFormat::Syslog),
        "commonlog" | "clf" => Ok(logler_core::LogFormat::CommonLog),
        "logfmt" => Ok(logler_core::LogFormat::Logfmt),
        "custom" => Ok(logler_core::LogFormat::Custom),
        other => Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
            "Unknown log format: {}",
            other
        ))),
    }
}
