#![allow(non_local_definitions)]

use logler_core::index::LoadError;
use logler_core::investigate::NoEntryAtLine;
use logler_core::*;
use pyo3::create_exception;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use regex::Regex;
use std::path::PathBuf;
use std::sync::{PoisonError, RwLock, RwLockReadGuard, RwLockWriteGuard};

create_exception!(
    logler_rs,
    LineNotFoundError,
    PyValueError,
    "A line number that has no entry in the file: the caller's error."
);

/// Python wrapper for Investigator
#[pyclass]
struct PyInvestigator {
    /// A load takes the write side and every other call the read side, each inside its
    /// GIL-released section: a call made from another thread during a load waits for the
    /// load, as it did when the GIL kept the two apart.
    investigator: RwLock<Investigator>,
}

impl PyInvestigator {
    fn read(&self) -> RwLockReadGuard<'_, Investigator> {
        self.investigator
            .read()
            .unwrap_or_else(PoisonError::into_inner)
    }

    fn write(&self) -> RwLockWriteGuard<'_, Investigator> {
        self.investigator
            .write()
            .unwrap_or_else(PoisonError::into_inner)
    }
}

#[pymethods]
impl PyInvestigator {
    #[new]
    fn new() -> Self {
        Self {
            investigator: RwLock::new(Investigator::new()),
        }
    }

    /// Load log files
    fn load_files(&self, py: Python<'_>, files: Vec<String>) -> PyResult<()> {
        let paths = to_paths(&files);
        py.detach(|| self.write().load_files(&paths))
            .map_err(engine_err)
    }

    /// Load log files with optional parser config (force_format/custom_regex)
    fn load_files_with_config(
        &self,
        py: Python<'_>,
        files: Vec<String>,
        force_format: Option<String>,
        custom_regex: Option<String>,
    ) -> PyResult<()> {
        let paths = to_paths(&files);
        let config = build_parser_config(force_format.as_deref(), custom_regex.as_deref())?;
        py.detach(|| self.write().load_files_with_config(&paths, &config))
            .map_err(engine_err)
    }

    /// Search logs (input and output as JSON strings)
    fn search(&self, py: Python<'_>, query_json: String) -> PyResult<String> {
        let query: SearchQuery = serde_json::from_str(&query_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        py.detach(|| to_json(self.read().search(&query)))
            .map_err(engine_err)
    }

    /// Follow thread
    fn follow_thread(
        &self,
        py: Python<'_>,
        files: Vec<String>,
        thread_id: Option<String>,
        correlation_id: Option<String>,
        trace_id: Option<String>,
    ) -> PyResult<String> {
        let paths = to_paths(&files);
        py.detach(|| {
            to_json(
                self.read()
                    .follow_thread(&paths, thread_id, correlation_id, trace_id),
            )
        })
        .map_err(engine_err)
    }

    /// Get context around a log entry
    fn get_context(
        &self,
        py: Python<'_>,
        file: String,
        line_number: i64,
        lines_before: usize,
        lines_after: usize,
        include_related_threads: bool,
    ) -> PyResult<String> {
        // A negative line has no entry: the same error as a line past the end.
        let Ok(line) = usize::try_from(line_number) else {
            return Err(engine_err(anyhow::Error::new(NoEntryAtLine {
                file,
                line: line_number,
            })));
        };
        py.detach(|| {
            to_json(self.read().get_context(
                &file,
                line,
                lines_before,
                lines_after,
                include_related_threads,
            ))
        })
        .map_err(engine_err)
    }

    /// Find patterns
    fn find_patterns(
        &self,
        py: Python<'_>,
        files: Vec<String>,
        min_occurrences: usize,
    ) -> PyResult<String> {
        let paths = to_paths(&files);
        py.detach(|| to_json(self.read().find_patterns(&paths, min_occurrences)))
            .map_err(engine_err)
    }

    /// Get metadata
    fn get_metadata(&self, py: Python<'_>, files: Vec<String>) -> PyResult<String> {
        let paths = to_paths(&files);
        py.detach(|| to_json(self.read().get_metadata(&paths)))
            .map_err(engine_err)
    }

    /// Each thread id's count of entries per level, and its total, as JSON
    fn thread_level_counts(&self, py: Python<'_>, files: Vec<String>) -> PyResult<String> {
        let paths = to_paths(&files);
        py.detach(|| to_json(Ok(self.read().thread_level_counts(&paths))))
            .map_err(engine_err)
    }

    /// Extract all unique IDs from loaded files
    fn extract_ids(&self, py: Python<'_>, filters_json: Option<String>) -> PyResult<String> {
        let filters = filters_json
            .map(|json_str| serde_json::from_str::<SearchFilters>(&json_str))
            .transpose()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        py.detach(|| to_json(self.read().extract_ids(filters.as_ref())))
            .map_err(engine_err)
    }

    /// Return a page of raw entries by direct index iteration (no search overhead).
    fn get_entries_page(&self, py: Python<'_>, offset: usize, limit: usize) -> PyResult<String> {
        py.detach(|| to_json(Ok(self.read().get_entries_page(offset, limit))))
            .map_err(engine_err)
    }

    /// Build hierarchical view of threads/spans
    #[allow(clippy::too_many_arguments)] // the Python signature, plus `py` for the GIL release
    fn build_hierarchy(
        &self,
        py: Python<'_>,
        files: Vec<String>,
        root_identifier: String,
        max_depth: Option<usize>,
        use_naming_patterns: Option<bool>,
        use_temporal_inference: Option<bool>,
        min_confidence: Option<f64>,
    ) -> PyResult<String> {
        let paths = to_paths(&files);

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

        py.detach(|| {
            to_json(
                self.read()
                    .build_hierarchy(&paths, &root_identifier, Some(config)),
            )
        })
        .map_err(engine_err)
    }
}

fn to_paths(files: &[String]) -> Vec<PathBuf> {
    files.iter().map(PathBuf::from).collect()
}

/// An engine result as JSON text; the serialization runs with the result, off the GIL.
fn to_json<T: serde::Serialize>(result: anyhow::Result<T>) -> anyhow::Result<String> {
    Ok(serde_json::to_string(&result?)?)
}

/// The one mapping of an engine error to a Python exception. A log file that cannot be
/// opened or read becomes `OSError(errno, strerror, filename)`, which Python turns into
/// `FileNotFoundError`, `PermissionError`, `IsADirectoryError` and the like; every other
/// engine error is a `RuntimeError`, except a line number with no entry, which is
/// `LineNotFoundError` (a `ValueError`).
fn engine_err(e: anyhow::Error) -> PyErr {
    if let Some(none) = e.downcast_ref::<NoEntryAtLine>() {
        return LineNotFoundError::new_err(none.to_string());
    }
    if let Some(load) = e.downcast_ref::<LoadError>() {
        if let Some(code) = load.source.raw_os_error() {
            let text = std::io::Error::from_raw_os_error(code).to_string();
            let reason = text.split(" (os error").next().unwrap_or(&text).to_string();
            let filename = load.path.to_string_lossy().into_owned();
            return PyErr::new::<pyo3::exceptions::PyOSError, _>((code, reason, filename));
        }
    }
    PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string())
}

/// Parses single log lines with the same parser the index uses.
#[pyclass]
struct PyLineParser {
    parser: logler_core::parser::LogParser,
}

#[pymethods]
impl PyLineParser {
    #[new]
    #[pyo3(signature = (file_name=None, force_format=None, custom_regex=None))]
    fn new(
        file_name: Option<String>,
        force_format: Option<String>,
        custom_regex: Option<String>,
    ) -> PyResult<Self> {
        let config = build_parser_config(force_format.as_deref(), custom_regex.as_deref())?;
        Ok(Self {
            parser: config.build_for_file(file_name.unwrap_or_default()),
        })
    }

    /// Parse one line; returns the entry as JSON (same shape as `get_entries_page`).
    fn parse_line(&self, line_number: usize, raw: &str) -> PyResult<String> {
        let entry = self
            .parser
            .parse_line(line_number, raw)
            .map_err(engine_err)?;
        to_json(Ok(entry)).map_err(engine_err)
    }
}

/// The level a word names (`warning`, `ERR`, `Crit`), spelled as entries and filters spell
/// it (`Warn`, `Error`, `Fatal`); `None` for a word that names no level. The words are the
/// parser's own table, so a level the parser reads can always be asked for by the same word.
/// `unknown` names the level of a line whose level word is not in that table.
#[pyfunction]
fn level_name(word: &str) -> Option<String> {
    let word = word.trim();
    let level = LogLevel::from_word(word).or_else(|| {
        word.eq_ignore_ascii_case("unknown")
            .then_some(LogLevel::Unknown)
    })?;
    serde_json::to_value(level).ok()?.as_str().map(String::from)
}

/// Python module
#[pymodule]
fn logler_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyInvestigator>()?;
    m.add_class::<PyLineParser>()?;
    m.add("LineNotFoundError", m.py().get_type::<LineNotFoundError>())?;
    m.add_function(wrap_pyfunction!(level_name, m)?)?;
    Ok(())
}

/// The one place a format name and a regex string become a `ParserConfig`.
fn build_parser_config(
    force_format: Option<&str>,
    custom_regex: Option<&str>,
) -> PyResult<logler_core::ParserConfig> {
    let mut config = logler_core::ParserConfig::new();

    if let Some(format_str) = force_format {
        config = config.with_force_format(parse_format_string(format_str)?);
    }

    if let Some(re) = custom_regex {
        let regex = Regex::new(re)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        config = config.with_custom_regex(regex);
    }

    Ok(config)
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
