"""
Log format auto-detection and template mining (M6).

Provides:
- detect_format(): Classify log files (JSON, syslog, CLF, logfmt, custom)
  with confidence scores.
- mine_templates(): Drain-algorithm template mining to discover recurring
  log patterns and extract variable fields.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


# ============================================================================
# Format Detection (M6.1 + M6.2)
# ============================================================================


@dataclass
class FormatCandidate:
    """A potential log format match with confidence score."""

    format: str
    confidence: float
    match_rate: float
    detected_fields: List[str] = field(default_factory=list)


@dataclass
class FormatDetection:
    """Result of format detection for a single file."""

    format: str
    confidence: float
    sample_size: int
    match_rate: float
    alternatives: List[Dict[str, Any]]
    detected_fields: List[str]
    sample_lines: List[str]
    mixed: bool = False


# Regex patterns for well-known log formats
_SYSLOG_BSD = re.compile(r"^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+\S+")
_SYSLOG_RFC5424 = re.compile(r"^<\d{1,3}>\d?\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_COMMON_LOG = re.compile(
    r"^\S+\s+\S+\s+\S+\s+\["
    r"\d{2}/[A-Z][a-z]{2}/\d{4}:\d{2}:\d{2}:\d{2}\s+[+-]\d{4}"
    r'\]\s+"[A-Z]+\s+'
)
_LOGFMT_KV = re.compile(r"[a-zA-Z_][\w]*=[^\s]+")


def detect_format(
    file_path: str,
    sample_size: int = 50,
    custom_formats: Optional[Dict[str, Any]] = None,
) -> FormatDetection:
    """Detect the log format of a file by sampling lines.

    Reads up to sample_size non-empty lines and scores each against
    known format patterns. Returns the best match with confidence.

    Args:
        file_path: Path to the log file.
        sample_size: Number of non-empty lines to sample.
        custom_formats: Optional dict of {name: {regex: str}} from config.

    Returns:
        FormatDetection with best format, confidence, alternatives.
    """
    lines = _read_sample_lines(file_path, sample_size)
    if not lines:
        return FormatDetection(
            format="unknown",
            confidence=0.0,
            sample_size=0,
            match_rate=0.0,
            alternatives=[],
            detected_fields=[],
            sample_lines=[],
        )

    candidates: List[FormatCandidate] = []

    # Test JSON
    candidates.append(_score_json(lines))

    # Test Syslog (BSD + RFC5424 combined)
    candidates.append(_score_syslog(lines))

    # Test Apache/Nginx Common Log Format
    candidates.append(_score_common_log(lines))

    # Test Logfmt
    candidates.append(_score_logfmt(lines))

    # Test custom formats from config
    if custom_formats:
        for name, fmt_config in custom_formats.items():
            regex_str = fmt_config.get("regex") if isinstance(fmt_config, dict) else None
            if regex_str:
                candidate = _score_custom(lines, name, regex_str)
                if candidate:
                    candidates.append(candidate)

    # Sort by confidence descending
    candidates.sort(key=lambda c: c.confidence, reverse=True)

    best = (
        candidates[0]
        if candidates
        else FormatCandidate(format="unknown", confidence=0.0, match_rate=0.0)
    )

    # Detect mixed formats: if top two candidates both have match_rate > 0.3
    # and neither dominates (neither > 0.8)
    mixed = False
    if len(candidates) >= 2:
        top_two = candidates[:2]
        if (
            top_two[0].match_rate < 0.8
            and top_two[1].match_rate > 0.3
            and top_two[0].format != "unknown"
            and top_two[1].format != "unknown"
        ):
            mixed = True

    alternatives = [
        {
            "format": c.format,
            "confidence": round(c.confidence, 4),
            "match_rate": round(c.match_rate, 4),
        }
        for c in candidates[1:]
        if c.confidence > 0.01
    ]

    return FormatDetection(
        format=best.format,
        confidence=round(best.confidence, 4),
        sample_size=len(lines),
        match_rate=round(best.match_rate, 4),
        alternatives=alternatives,
        detected_fields=best.detected_fields,
        sample_lines=lines[:5],
        mixed=mixed,
    )


def _read_sample_lines(file_path: str, max_lines: int) -> List[str]:
    """Read up to max_lines non-empty, non-comment lines from a file."""
    lines: List[str] = []
    try:
        with open(file_path, "r", errors="replace") as f:
            for raw in f:
                stripped = raw.rstrip("\n\r")
                if not stripped or stripped.startswith("#"):
                    continue
                lines.append(stripped)
                if len(lines) >= max_lines:
                    break
    except (OSError, IOError):
        pass
    return lines


def _score_json(lines: List[str]) -> FormatCandidate:
    """Score lines as JSON format."""
    matches = 0
    all_fields: set = set()
    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith(("{", "[")):
            continue
        try:
            data = json.loads(stripped)
            if isinstance(data, dict):
                matches += 1
                all_fields.update(data.keys())
        except (json.JSONDecodeError, ValueError):
            pass

    rate = matches / len(lines) if lines else 0.0
    # JSON is highly specific — high bonus
    confidence = rate * 0.98 if rate > 0.5 else rate * 0.5
    return FormatCandidate(
        format="json",
        confidence=confidence,
        match_rate=rate,
        detected_fields=sorted(all_fields),
    )


def _score_syslog(lines: List[str]) -> FormatCandidate:
    """Score lines as syslog format (BSD or RFC5424)."""
    matches = 0
    for line in lines:
        if _SYSLOG_BSD.match(line) or _SYSLOG_RFC5424.match(line):
            matches += 1

    rate = matches / len(lines) if lines else 0.0
    # Syslog regex is fairly specific
    confidence = rate * 0.90
    fields = ["timestamp", "hostname", "program", "message"]
    return FormatCandidate(
        format="syslog",
        confidence=confidence,
        match_rate=rate,
        detected_fields=fields if rate > 0.3 else [],
    )


def _score_common_log(lines: List[str]) -> FormatCandidate:
    """Score lines as Apache/Nginx Common Log Format."""
    matches = 0
    for line in lines:
        if _COMMON_LOG.match(line):
            matches += 1

    rate = matches / len(lines) if lines else 0.0
    # CLF is highly specific
    confidence = rate * 0.95
    fields = ["remote_host", "ident", "user", "timestamp", "method", "path", "status", "bytes"]
    return FormatCandidate(
        format="common_log",
        confidence=confidence,
        match_rate=rate,
        detected_fields=fields if rate > 0.3 else [],
    )


def _score_logfmt(lines: List[str]) -> FormatCandidate:
    """Score lines as logfmt (key=value pairs)."""
    matches = 0
    all_fields: set = set()
    for line in lines:
        kv_matches = _LOGFMT_KV.findall(line)
        if len(kv_matches) >= 3:
            matches += 1
            for kv in kv_matches:
                key = kv.split("=", 1)[0]
                all_fields.add(key)

    rate = matches / len(lines) if lines else 0.0
    # Logfmt is less specific (many formats have key=value pairs)
    confidence = rate * 0.80
    return FormatCandidate(
        format="logfmt",
        confidence=confidence,
        match_rate=rate,
        detected_fields=sorted(all_fields),
    )


def _score_custom(lines: List[str], name: str, regex_str: str) -> Optional[FormatCandidate]:
    """Score lines against a custom regex format."""
    try:
        pattern = re.compile(regex_str)
    except re.error:
        return None

    matches = 0
    all_fields: set = set()
    for line in lines:
        m = pattern.search(line)
        if m:
            matches += 1
            all_fields.update(m.groupdict().keys())

    rate = matches / len(lines) if lines else 0.0
    # Custom formats are user-defined — if they match, high specificity
    confidence = rate * 0.92
    return FormatCandidate(
        format=f"custom:{name}",
        confidence=confidence,
        match_rate=rate,
        detected_fields=sorted(all_fields),
    )


# ============================================================================
# Drain Algorithm for Template Mining (M6.3)
# ============================================================================


@dataclass
class LogTemplate:
    """A discovered log template (cluster of similar messages)."""

    template: str
    count: int
    examples: List[str]
    variable_positions: List[int]


@dataclass
class TemplateResult:
    """Result of template mining."""

    templates: List[Dict[str, Any]]
    total_lines: int
    unique_templates: int
    coverage: float


class _DrainNode:
    """Internal node in the Drain parse tree."""

    __slots__ = ("children", "clusters")

    def __init__(self) -> None:
        self.children: Dict[str, _DrainNode] = {}
        self.clusters: List[_DrainCluster] = []


class _DrainCluster:
    """A cluster of log messages sharing a common template."""

    __slots__ = ("tokens", "count", "examples")

    def __init__(self, tokens: List[str]) -> None:
        self.tokens = list(tokens)
        self.count = 1
        self.examples: List[str] = []

    def template_str(self) -> str:
        return " ".join(self.tokens)


class DrainParser:
    """Drain algorithm for log template mining.

    Implements the Drain approach (He et al., 2017):
    1. Group messages by token count (length).
    2. Walk down a fixed-depth prefix tree.
    3. At leaf nodes, match against existing clusters by token similarity.
    4. Merge into existing cluster or create new one.

    Attributes:
        depth: Number of prefix tokens to use for tree routing (default 3).
        sim_threshold: Minimum fraction of tokens that must match (default 0.5).
        max_clusters: Maximum number of clusters to track (default 200).
    """

    def __init__(
        self,
        depth: int = 3,
        sim_threshold: float = 0.5,
        max_clusters: int = 200,
        max_examples: int = 3,
    ) -> None:
        self.depth = depth
        self.sim_threshold = sim_threshold
        self.max_clusters = max_clusters
        self.max_examples = max_examples
        # Root: token_count -> DrainNode
        self._root: Dict[int, _DrainNode] = {}
        self._cluster_count = 0

    def add_message(self, message: str) -> Optional[_DrainCluster]:
        """Process a single log message through the Drain tree.

        Returns the cluster the message was assigned to, or None if skipped.
        """
        tokens = _tokenize(message)
        if not tokens:
            return None

        token_count = len(tokens)

        # Get or create length-group node
        if token_count not in self._root:
            self._root[token_count] = _DrainNode()

        node = self._root[token_count]

        # Walk down prefix tree using only the FIRST token as routing key.
        # Deeper routing causes over-fragmentation when variable tokens
        # (usernames, IDs, paths) appear early in the message.
        # The similarity check at leaf level handles the rest.
        first_token = tokens[0]
        key = first_token if not _is_variable_token(first_token) else "<*>"
        if key not in node.children:
            node.children[key] = _DrainNode()
        node = node.children[key]

        # Find best matching cluster at this leaf
        best_cluster = None
        best_sim = -1.0

        for cluster in node.clusters:
            sim = _sequence_similarity(tokens, cluster.tokens)
            if sim > best_sim:
                best_sim = sim
                best_cluster = cluster

        if best_cluster is not None and best_sim >= self.sim_threshold:
            # Merge into existing cluster
            best_cluster.count += 1
            # Update template: variable positions become <*>
            _merge_tokens(best_cluster.tokens, tokens)
            if len(best_cluster.examples) < self.max_examples:
                best_cluster.examples.append(message)
            return best_cluster
        else:
            # Create new cluster
            if self._cluster_count >= self.max_clusters:
                return None  # Skip — cluster limit reached
            new_cluster = _DrainCluster(tokens)
            new_cluster.examples.append(message)
            node.clusters.append(new_cluster)
            self._cluster_count += 1
            return new_cluster

    def get_clusters(self) -> List[_DrainCluster]:
        """Collect all clusters from the tree."""
        clusters: List[_DrainCluster] = []
        self._collect(self._root, clusters)
        return clusters

    def _collect(
        self,
        nodes: Any,
        result: List[_DrainCluster],
    ) -> None:
        if isinstance(nodes, dict):
            for v in nodes.values():
                self._collect(v, result)
        elif isinstance(nodes, _DrainNode):
            result.extend(nodes.clusters)
            for child in nodes.children.values():
                self._collect(child, result)


def _tokenize(message: str) -> List[str]:
    """Split a log message into tokens."""
    return message.split()


def _is_variable_token(token: str) -> bool:
    """Heuristic: is this token likely a variable value?"""
    # Pure numbers
    if re.match(r"^-?\d+(\.\d+)?$", token):
        return True
    # Hex strings
    if re.match(r"^0x[0-9a-fA-F]+$", token):
        return True
    # UUIDs
    if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", token):
        return True
    # IP addresses
    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", token):
        return True
    # Paths (start with /)
    if token.startswith("/") and len(token) > 1:
        return True
    return False


def _sequence_similarity(tokens_a: List[str], tokens_b: List[str]) -> float:
    """Compute fraction of matching tokens between two sequences."""
    if len(tokens_a) != len(tokens_b):
        return 0.0
    if not tokens_a:
        return 0.0
    matches = sum(1 for a, b in zip(tokens_a, tokens_b) if a == b or a == "<*>" or b == "<*>")
    return matches / len(tokens_a)


def _merge_tokens(template: List[str], tokens: List[str]) -> None:
    """Merge new tokens into template, replacing mismatches with <*>."""
    for i, (t, tok) in enumerate(zip(template, tokens)):
        if t != tok and t != "<*>":
            template[i] = "<*>"


def mine_templates(
    messages: Sequence[str],
    max_clusters: int = 200,
    sim_threshold: float = 0.5,
    depth: int = 3,
) -> TemplateResult:
    """Mine log templates from a sequence of messages using the Drain algorithm.

    Args:
        messages: Log message strings to analyze.
        max_clusters: Maximum number of template clusters.
        sim_threshold: Minimum token similarity for cluster merge (0.0-1.0).
        depth: Prefix tree depth for routing.

    Returns:
        TemplateResult with templates, counts, and coverage statistics.
    """
    parser = DrainParser(
        depth=depth,
        sim_threshold=sim_threshold,
        max_clusters=max_clusters,
    )

    assigned_count = 0
    total = len(messages)

    for msg in messages:
        cluster = parser.add_message(msg)
        if cluster is not None:
            assigned_count += 1

    clusters = parser.get_clusters()
    clusters.sort(key=lambda c: c.count, reverse=True)

    templates: List[Dict[str, Any]] = []
    for cluster in clusters:
        template_str = cluster.template_str()
        variable_positions = [i for i, t in enumerate(cluster.tokens) if t == "<*>"]
        templates.append(
            {
                "template": template_str,
                "count": cluster.count,
                "percentage": round(100.0 * cluster.count / total, 2) if total else 0.0,
                "examples": cluster.examples,
                "variable_positions": variable_positions,
            }
        )

    coverage = assigned_count / total if total else 0.0

    return TemplateResult(
        templates=templates,
        total_lines=total,
        unique_templates=len(templates),
        coverage=round(coverage, 4),
    )
