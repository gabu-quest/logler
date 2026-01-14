use crate::types::{LogEntry, LogLevel};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use uuid::Uuid;

/// A node in the span/thread hierarchy tree
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpanNode {
    /// Unique identifier for this node
    pub id: String,

    /// Type of node (thread, span, correlation, etc.)
    pub node_type: NodeType,

    /// Display name for this node
    pub name: Option<String>,

    /// Parent node ID (None for root nodes)
    pub parent_id: Option<String>,

    /// Child nodes
    pub children: Vec<SpanNode>,

    /// Log entry IDs belonging to this node
    pub entry_ids: Vec<Uuid>,

    /// First log entry timestamp
    pub start_time: Option<DateTime<Utc>>,

    /// Last log entry timestamp
    pub end_time: Option<DateTime<Utc>>,

    /// Duration in milliseconds
    pub duration_ms: Option<i64>,

    /// Number of log entries
    pub entry_count: usize,

    /// Number of errors in this node and descendants
    pub error_count: usize,

    /// Log level distribution
    pub level_counts: HashMap<String, usize>,

    /// Depth in the tree (0 for root)
    pub depth: usize,

    /// Relationship confidence (0.0-1.0, 1.0 = explicit, <1.0 = inferred)
    pub confidence: f64,

    /// Evidence for the relationship
    pub relationship_evidence: Vec<String>,
}

/// Type of hierarchy node
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum NodeType {
    Thread,
    Span,
    Correlation,
    Trace,
    Inferred,
}

/// Complete thread/span hierarchy
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThreadHierarchy {
    /// Root nodes (can be multiple)
    pub roots: Vec<SpanNode>,

    /// Total number of nodes in the tree
    pub total_nodes: usize,

    /// Maximum depth of the tree
    pub max_depth: usize,

    /// Total duration in milliseconds (from earliest to latest)
    pub total_duration_ms: Option<i64>,

    /// Number of parallel/concurrent spans detected
    pub concurrent_count: usize,

    /// Bottleneck information
    pub bottleneck: Option<BottleneckInfo>,

    /// Nodes with errors
    pub error_nodes: Vec<String>,

    /// Detection method used
    pub detection_method: DetectionMethod,
}

/// Information about a bottleneck
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BottleneckInfo {
    pub node_id: String,
    pub node_name: Option<String>,
    pub duration_ms: i64,
    pub percentage_of_total: f64,
}

/// Method used to detect hierarchy
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum DetectionMethod {
    /// Explicit parent_span_id fields (OpenTelemetry)
    Explicit,
    /// Thread naming patterns (worker-1.task-a)
    NamingPattern,
    /// Temporal proximity + log messages
    Temporal,
    /// Correlation ID chaining
    CorrelationChain,
    /// Mixed methods
    Mixed(Vec<String>),
}

/// Builder for constructing hierarchies from log entries
pub struct HierarchyBuilder {
    /// Map of span_id -> parent_span_id for explicit relationships
    span_parents: HashMap<String, String>,

    /// Map of span_id -> log entry IDs
    span_entries: HashMap<String, Vec<Uuid>>,

    /// Map of thread_id -> log entry IDs
    thread_entries: HashMap<String, Vec<Uuid>>,

    /// All log entries indexed by ID
    entries_by_id: HashMap<Uuid, LogEntry>,

    /// Detected naming patterns
    #[allow(dead_code)]
    naming_patterns: Vec<NamingPattern>,

    /// Configuration for hierarchy detection
    config: HierarchyConfig,
}

/// Pattern for detecting parent-child relationships from names
#[allow(dead_code)]
#[derive(Debug, Clone)]
struct NamingPattern {
    pattern_type: PatternType,
    regex: regex::Regex,
}

#[allow(dead_code)]
#[derive(Debug, Clone, Copy)]
enum PatternType {
    Dot,   // worker-1.task-a
    Colon, // main:subtask-1
    Dash,  // req-123-auth
}

/// Configuration for hierarchy detection
#[derive(Debug, Clone)]
pub struct HierarchyConfig {
    /// Maximum depth to traverse
    pub max_depth: usize,

    /// Whether to use naming pattern inference
    pub use_naming_patterns: bool,

    /// Whether to use temporal inference
    pub use_temporal_inference: bool,

    /// Maximum time gap (ms) for temporal inference
    pub max_temporal_gap_ms: i64,

    /// Minimum confidence score to include (0.0-1.0)
    pub min_confidence: f64,

    /// Custom parent-child patterns
    pub custom_patterns: Vec<String>,
}

impl Default for HierarchyConfig {
    fn default() -> Self {
        Self {
            max_depth: 50,
            use_naming_patterns: true,
            use_temporal_inference: true,
            max_temporal_gap_ms: 1000,
            min_confidence: 0.5,
            custom_patterns: Vec::new(),
        }
    }
}

impl HierarchyBuilder {
    /// Create a new hierarchy builder
    pub fn new(config: HierarchyConfig) -> Self {
        Self {
            span_parents: HashMap::new(),
            span_entries: HashMap::new(),
            thread_entries: HashMap::new(),
            entries_by_id: HashMap::new(),
            naming_patterns: Self::default_naming_patterns(),
            config,
        }
    }

    /// Add a log entry to the builder
    pub fn add_entry(&mut self, entry: LogEntry) {
        let entry_id = entry.id;

        // Index by entry ID
        self.entries_by_id.insert(entry_id, entry.clone());

        // Track span relationships
        if let Some(span_id) = &entry.span_id {
            self.span_entries
                .entry(span_id.clone())
                .or_default()
                .push(entry_id);

            // Record explicit parent relationship
            if let Some(parent_span_id) = &entry.parent_span_id {
                self.span_parents
                    .insert(span_id.clone(), parent_span_id.clone());
            }
        }

        // Track thread relationships
        if let Some(thread_id) = &entry.thread_id {
            self.thread_entries
                .entry(thread_id.clone())
                .or_default()
                .push(entry_id);
        }
    }

    /// Build the hierarchy for a specific root identifier
    pub fn build(&self, root_identifier: &str) -> Option<ThreadHierarchy> {
        // Try to find the root (could be span_id, thread_id, correlation_id, or trace_id)
        let root_entries = self.find_root_entries(root_identifier)?;

        if root_entries.is_empty() {
            return None;
        }

        // Determine detection method
        let detection_method = self.determine_detection_method(&root_entries);

        // Build tree from roots
        let mut roots = Vec::new();
        let mut all_node_ids = HashMap::new();

        // Group entries by potential parent relationship
        let grouped = self.group_entries_by_hierarchy(&root_entries);

        for (parent_key, entries) in grouped {
            if let Some(node) = self.build_node(&parent_key, &entries, 0, &mut all_node_ids) {
                roots.push(node);
            }
        }

        // Calculate hierarchy statistics
        let total_nodes = all_node_ids.len();
        let max_depth = roots
            .iter()
            .map(|r| self.calculate_max_depth(r))
            .max()
            .unwrap_or(0);

        let total_duration_ms = self.calculate_total_duration(&root_entries);
        let concurrent_count = self.count_concurrent_spans(&roots);
        let bottleneck = self.find_bottleneck(&roots);
        let error_nodes = self.collect_error_nodes(&roots);

        Some(ThreadHierarchy {
            roots,
            total_nodes,
            max_depth,
            total_duration_ms,
            concurrent_count,
            bottleneck,
            error_nodes,
            detection_method,
        })
    }

    /// Find entries matching the root identifier
    fn find_root_entries(&self, identifier: &str) -> Option<Vec<&LogEntry>> {
        let mut entries = Vec::new();

        // Try span_id
        if let Some(entry_ids) = self.span_entries.get(identifier) {
            for id in entry_ids {
                if let Some(entry) = self.entries_by_id.get(id) {
                    entries.push(entry);
                }
            }
        }

        // Try thread_id
        if entries.is_empty() {
            if let Some(entry_ids) = self.thread_entries.get(identifier) {
                for id in entry_ids {
                    if let Some(entry) = self.entries_by_id.get(id) {
                        entries.push(entry);
                    }
                }
            }
        }

        // Try correlation_id or trace_id
        if entries.is_empty() {
            for entry in self.entries_by_id.values() {
                if entry.correlation_id.as_deref() == Some(identifier)
                    || entry.trace_id.as_deref() == Some(identifier)
                {
                    entries.push(entry);
                }
            }
        }

        if entries.is_empty() {
            None
        } else {
            Some(entries)
        }
    }

    /// Group entries by their hierarchical relationships
    fn group_entries_by_hierarchy<'a>(
        &self,
        entries: &[&'a LogEntry],
    ) -> HashMap<String, Vec<&'a LogEntry>> {
        let mut groups: HashMap<String, Vec<&'a LogEntry>> = HashMap::new();

        for entry in entries {
            // Determine the grouping key based on hierarchy level
            let key = if let Some(span_id) = &entry.span_id {
                format!("span:{}", span_id)
            } else if let Some(thread_id) = &entry.thread_id {
                format!("thread:{}", thread_id)
            } else if let Some(correlation_id) = &entry.correlation_id {
                format!("correlation:{}", correlation_id)
            } else {
                format!("entry:{}", entry.id)
            };

            groups.entry(key).or_default().push(entry);
        }

        groups
    }

    /// Build a single node in the hierarchy
    fn build_node(
        &self,
        key: &str,
        entries: &[&LogEntry],
        depth: usize,
        all_nodes: &mut HashMap<String, ()>,
    ) -> Option<SpanNode> {
        if depth > self.config.max_depth || entries.is_empty() {
            return None;
        }

        all_nodes.insert(key.to_string(), ());

        // Extract node information
        let (node_type, id) = self.parse_node_key(key);
        let name = self.infer_node_name(entries);
        let parent_id = self.find_parent_id(entries);

        // Collect entry IDs and calculate stats
        let entry_ids: Vec<Uuid> = entries.iter().map(|e| e.id).collect();
        let (start_time, end_time) = self.calculate_time_range(entries);
        let duration_ms = self.calculate_duration(&start_time, &end_time);
        let error_count = entries.iter().filter(|e| self.is_error(e)).count();
        let level_counts = self.calculate_level_counts(entries);

        // Find children
        let mut children = Vec::new();
        let child_entries = self.find_children(entries);

        for (child_key, child_entry_list) in child_entries {
            if let Some(child_node) =
                self.build_node(&child_key, &child_entry_list, depth + 1, all_nodes)
            {
                children.push(child_node);
            }
        }

        // Calculate confidence
        let (confidence, evidence) = self.calculate_confidence(entries, &parent_id);

        Some(SpanNode {
            id,
            node_type,
            name,
            parent_id,
            children,
            entry_ids,
            start_time,
            end_time,
            duration_ms,
            entry_count: entries.len(),
            error_count,
            level_counts,
            depth,
            confidence,
            relationship_evidence: evidence,
        })
    }

    /// Find child entries for given parent entries
    fn find_children(&self, parent_entries: &[&LogEntry]) -> HashMap<String, Vec<&LogEntry>> {
        let mut children: HashMap<String, Vec<&LogEntry>> = HashMap::new();

        // Extract potential parent identifiers
        let parent_span_ids: Vec<String> = parent_entries
            .iter()
            .filter_map(|e| e.span_id.clone())
            .collect();

        // Find entries with matching parent_span_id
        for entry in self.entries_by_id.values() {
            if let Some(parent_span_id) = &entry.parent_span_id {
                if parent_span_ids.contains(parent_span_id) {
                    let key = if let Some(span_id) = &entry.span_id {
                        format!("span:{}", span_id)
                    } else {
                        format!("entry:{}", entry.id)
                    };

                    children.entry(key).or_default().push(entry);
                }
            }
        }

        // If no explicit children and naming patterns enabled, try inference
        if children.is_empty() && self.config.use_naming_patterns {
            children.extend(self.infer_children_from_naming(parent_entries));
        }

        children
    }

    /// Infer children from naming patterns (worker-1 → worker-1.task-a)
    fn infer_children_from_naming(
        &self,
        parent_entries: &[&LogEntry],
    ) -> HashMap<String, Vec<&LogEntry>> {
        let mut children: HashMap<String, Vec<&LogEntry>> = HashMap::new();

        for parent in parent_entries {
            let parent_id = parent
                .thread_id
                .as_ref()
                .or(parent.correlation_id.as_ref())
                .or(parent.span_id.as_ref());

            if let Some(parent_id) = parent_id {
                // Look for entries with IDs that start with parent_id
                for entry in self.entries_by_id.values() {
                    if let Some(child_id) = entry
                        .thread_id
                        .as_ref()
                        .or(entry.correlation_id.as_ref())
                        .or(entry.span_id.as_ref())
                    {
                        if self.is_child_by_naming(parent_id, child_id) {
                            let key = format!("thread:{}", child_id);
                            children.entry(key).or_default().push(entry);
                        }
                    }
                }
            }
        }

        children
    }

    /// Check if child_id is a child of parent_id based on naming
    fn is_child_by_naming(&self, parent_id: &str, child_id: &str) -> bool {
        // Pattern: parent.child, parent:child, parent-child
        child_id.starts_with(&format!("{}.", parent_id))
            || child_id.starts_with(&format!("{}:", parent_id))
            || (child_id.starts_with(&format!("{}-", parent_id)) && child_id != parent_id)
    }

    /// Parse node key into type and ID
    fn parse_node_key(&self, key: &str) -> (NodeType, String) {
        if let Some(id) = key.strip_prefix("span:") {
            (NodeType::Span, id.to_string())
        } else if let Some(id) = key.strip_prefix("thread:") {
            (NodeType::Thread, id.to_string())
        } else if let Some(id) = key.strip_prefix("correlation:") {
            (NodeType::Correlation, id.to_string())
        } else if let Some(id) = key.strip_prefix("trace:") {
            (NodeType::Trace, id.to_string())
        } else {
            (NodeType::Inferred, key.to_string())
        }
    }

    /// Infer a human-readable name for the node
    fn infer_node_name(&self, entries: &[&LogEntry]) -> Option<String> {
        // Try to find operation name from fields
        for entry in entries {
            if let Some(op_name) = entry.fields.get("operation_name").and_then(|v| v.as_str()) {
                return Some(op_name.to_string());
            }
            if let Some(op_name) = entry.fields.get("name").and_then(|v| v.as_str()) {
                return Some(op_name.to_string());
            }
        }

        None
    }

    /// Find parent ID from entries
    fn find_parent_id(&self, entries: &[&LogEntry]) -> Option<String> {
        entries.first().and_then(|e| e.parent_span_id.clone())
    }

    /// Calculate time range for entries
    fn calculate_time_range(
        &self,
        entries: &[&LogEntry],
    ) -> (Option<DateTime<Utc>>, Option<DateTime<Utc>>) {
        let timestamps: Vec<DateTime<Utc>> = entries.iter().filter_map(|e| e.timestamp).collect();

        if timestamps.is_empty() {
            (None, None)
        } else {
            let start = timestamps.iter().min().copied();
            let end = timestamps.iter().max().copied();
            (start, end)
        }
    }

    /// Calculate duration between two timestamps
    fn calculate_duration(
        &self,
        start: &Option<DateTime<Utc>>,
        end: &Option<DateTime<Utc>>,
    ) -> Option<i64> {
        match (start, end) {
            (Some(s), Some(e)) => Some(e.timestamp_millis() - s.timestamp_millis()),
            _ => None,
        }
    }

    /// Calculate total duration for a set of entries
    fn calculate_total_duration(&self, entries: &[&LogEntry]) -> Option<i64> {
        let (start, end) = self.calculate_time_range(entries);
        self.calculate_duration(&start, &end)
    }

    /// Check if entry is an error
    fn is_error(&self, entry: &LogEntry) -> bool {
        matches!(entry.level, Some(LogLevel::Error) | Some(LogLevel::Fatal))
    }

    /// Calculate level distribution
    fn calculate_level_counts(&self, entries: &[&LogEntry]) -> HashMap<String, usize> {
        let mut counts = HashMap::new();
        for entry in entries {
            if let Some(level) = entry.level {
                *counts.entry(level.as_str().to_string()).or_insert(0) += 1;
            }
        }
        counts
    }

    /// Calculate confidence and evidence for relationship
    fn calculate_confidence(
        &self,
        _entries: &[&LogEntry],
        parent_id: &Option<String>,
    ) -> (f64, Vec<String>) {
        let mut evidence = Vec::new();
        let mut confidence: f64 = 0.0;

        // Explicit parent_span_id = highest confidence
        if parent_id.is_some() {
            evidence.push("explicit_parent_span_id".to_string());
            confidence = 1.0;
        } else {
            // Inferred relationships have lower confidence
            if self.config.use_naming_patterns {
                evidence.push("naming_pattern".to_string());
                confidence = 0.8;
            }
            if self.config.use_temporal_inference {
                evidence.push("temporal_proximity".to_string());
                confidence = confidence.max(0.6);
            }
        }

        (confidence, evidence)
    }

    /// Determine which detection method was used
    fn determine_detection_method(&self, entries: &[&LogEntry]) -> DetectionMethod {
        let has_explicit = entries.iter().any(|e| e.parent_span_id.is_some());
        let has_naming = self.config.use_naming_patterns;
        let has_temporal = self.config.use_temporal_inference;

        if has_explicit && !has_naming && !has_temporal {
            DetectionMethod::Explicit
        } else if has_explicit && (has_naming || has_temporal) {
            let mut methods = vec!["explicit".to_string()];
            if has_naming {
                methods.push("naming_pattern".to_string());
            }
            if has_temporal {
                methods.push("temporal".to_string());
            }
            DetectionMethod::Mixed(methods)
        } else if has_naming {
            DetectionMethod::NamingPattern
        } else if has_temporal {
            DetectionMethod::Temporal
        } else {
            DetectionMethod::Explicit
        }
    }

    /// Calculate maximum depth recursively
    fn calculate_max_depth(&self, node: &SpanNode) -> usize {
        fn max_depth(node: &SpanNode) -> usize {
            if node.children.is_empty() {
                node.depth
            } else {
                node.children
                    .iter()
                    .map(max_depth)
                    .max()
                    .unwrap_or(node.depth)
            }
        }
        max_depth(node)
    }

    /// Count concurrent spans
    fn count_concurrent_spans(&self, roots: &[SpanNode]) -> usize {
        // Simple heuristic: count nodes at the same depth level
        let mut max_concurrent = 0;
        let mut depth_counts: HashMap<usize, usize> = HashMap::new();

        fn count_at_depth(node: &SpanNode, counts: &mut HashMap<usize, usize>) {
            *counts.entry(node.depth).or_insert(0) += 1;
            for child in &node.children {
                count_at_depth(child, counts);
            }
        }

        for root in roots {
            count_at_depth(root, &mut depth_counts);
        }

        for count in depth_counts.values() {
            max_concurrent = max_concurrent.max(*count);
        }

        max_concurrent.saturating_sub(1) // Subtract 1 to not count the parent
    }

    /// Find bottleneck (slowest node)
    fn find_bottleneck(&self, roots: &[SpanNode]) -> Option<BottleneckInfo> {
        let mut bottleneck: Option<(String, Option<String>, i64)> = None;
        let mut total_duration = 0i64;

        fn find_slowest(
            node: &SpanNode,
            current_slowest: &mut Option<(String, Option<String>, i64)>,
            total: &mut i64,
        ) {
            if let Some(duration) = node.duration_ms {
                *total += duration;

                match current_slowest {
                    None => *current_slowest = Some((node.id.clone(), node.name.clone(), duration)),
                    Some((_, _, max_duration)) if duration > *max_duration => {
                        *current_slowest = Some((node.id.clone(), node.name.clone(), duration));
                    }
                    _ => {}
                }
            }

            for child in &node.children {
                find_slowest(child, current_slowest, total);
            }
        }

        for root in roots {
            find_slowest(root, &mut bottleneck, &mut total_duration);
        }

        bottleneck.map(|(node_id, node_name, duration_ms)| {
            let percentage = if total_duration > 0 {
                (duration_ms as f64 / total_duration as f64) * 100.0
            } else {
                0.0
            };

            BottleneckInfo {
                node_id,
                node_name,
                duration_ms,
                percentage_of_total: percentage,
            }
        })
    }

    /// Collect all nodes with errors
    fn collect_error_nodes(&self, roots: &[SpanNode]) -> Vec<String> {
        let mut error_nodes = Vec::new();

        fn collect_errors(node: &SpanNode, errors: &mut Vec<String>) {
            if node.error_count > 0 {
                errors.push(node.id.clone());
            }
            for child in &node.children {
                collect_errors(child, errors);
            }
        }

        for root in roots {
            collect_errors(root, &mut error_nodes);
        }

        error_nodes
    }

    /// Default naming patterns
    fn default_naming_patterns() -> Vec<NamingPattern> {
        vec![
            // worker-1.task-a
            NamingPattern {
                pattern_type: PatternType::Dot,
                regex: regex::Regex::new(r"^([^.]+)\.(.+)$").unwrap(),
            },
            // main:subtask-1
            NamingPattern {
                pattern_type: PatternType::Colon,
                regex: regex::Regex::new(r"^([^:]+):(.+)$").unwrap(),
            },
            // req-123-auth
            NamingPattern {
                pattern_type: PatternType::Dash,
                regex: regex::Regex::new(r"^(.+)-([^-]+)$").unwrap(),
            },
        ]
    }
}
