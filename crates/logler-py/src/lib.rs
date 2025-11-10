use logler_core::*;
use pyo3::prelude::*;
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
            .get_context(&file, line_number, lines_before, lines_after, include_related_threads)
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

/// Python module
#[pymodule]
fn logler_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<PyInvestigator>()?;
    m.add_function(wrap_pyfunction!(search, m)?)?;
    m.add_function(wrap_pyfunction!(follow_thread, m)?)?;
    m.add_function(wrap_pyfunction!(find_patterns, m)?)?;
    m.add_function(wrap_pyfunction!(get_metadata, m)?)?;
    Ok(())
}
