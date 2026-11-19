"""The exported pydantic models accept what the public `investigate` functions return.

Each test validates the real output of one function on one fixture, and checks that every key
the API returns is a declared field of the model (a model that declares none of them would
validate anything, with every field at its default).
"""

import json

import pytest

from logler import investigate, models

PLAIN = [
    "2024-01-15 10:00:02 INFO [worker-1] started request_id=abc",
    "2024-01-15 10:00:03 ERROR [worker-1] failed to connect db timeout=30s",
    "no level here",
]
JSON_ENTRIES = [
    {
        "timestamp": "2024-01-15T10:00:00.000Z",
        "level": "INFO",
        "message": "root start",
        "trace_id": "trace-123",
        "span_id": "span-root",
        "thread_id": "worker-1",
        "service_name": "api",
    },
    {
        "timestamp": "2024-01-15T10:00:00.200Z",
        "level": "INFO",
        "message": "child start",
        "trace_id": "trace-123",
        "span_id": "span-child",
        "parent_span_id": "span-root",
        "thread_id": "worker-2",
        "service_name": "db",
    },
    {
        "timestamp": "2024-01-15T10:00:00.500Z",
        "level": "ERROR",
        "message": "child error",
        "trace_id": "trace-123",
        "span_id": "span-child",
        "parent_span_id": "span-root",
        "thread_id": "worker-2",
        "service_name": "db",
    },
    {
        "timestamp": "2024-01-15T10:00:01.000Z",
        "level": "INFO",
        "message": "root end",
        "trace_id": "trace-123",
        "span_id": "span-root",
        "thread_id": "worker-1",
        "service_name": "api",
    },
]


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    """Seven lines: three plain (one with no level), four JSON lines of one trace with a
    root span, a child span of it, and an error in the child."""
    path = tmp_path_factory.mktemp("models") / "app.log"
    lines = PLAIN + [json.dumps(entry) for entry in JSON_ENTRIES]
    path.write_text("\n".join(lines) + "\n")
    return [str(path)]


@pytest.fixture(scope="module")
def hierarchy(files):
    return investigate.follow_thread_hierarchy(files=files, root_identifier="trace-123")


def declared(model):
    return set(model.model_fields) | {f.alias for f in model.model_fields.values() if f.alias}


def assert_declares(model, data):
    """Every key of `data` is a declared field of `model`."""
    assert sorted(set(data) - declared(model)) == []


def test_search_results(files):
    data = investigate.search(files=files)
    assert_declares(models.SearchResults, data)
    assert_declares(models.SearchResult, data["results"][0])
    assert_declares(models.LogEntry, data["results"][0]["entry"])
    result = models.SearchResults.model_validate(data)
    assert result.total_matches == 7
    assert len(result.results) == 7
    assert sorted(r.entry.line_number for r in result.results) == [1, 2, 3, 4, 5, 6, 7]


def test_search_summary(files):
    data = investigate.search(files=files, output_format="summary")
    assert_declares(models.SearchSummary, data)
    summary = models.SearchSummary.model_validate(data)
    assert summary.total_matches == 7
    assert summary.log_levels == {"INFO": 4, "ERROR": 2, "UNKNOWN": 1}
    assert summary.by_file == data["by_file"]


def test_search_count(files):
    data = investigate.search(files=files, output_format="count")
    assert_declares(models.SearchCount, data)
    assert models.SearchCount.model_validate(data).total_matches == 7


def test_follow_thread(files):
    data = investigate.follow_thread(files=files, thread_id="worker-1")
    assert_declares(models.ThreadTimeline, data)
    timeline = models.ThreadTimeline.model_validate(data)
    assert timeline.total_entries == 4
    assert timeline.unique_spans == ["span-root"]
    assert timeline.duration_ms == 3000


def test_find_patterns(files):
    data = investigate.find_patterns(files=files, min_occurrences=1)
    assert_declares(models.PatternResults, data)
    assert_declares(models.PatternMatch, data["patterns"][0])
    patterns = models.PatternResults.model_validate(data)
    assert len(patterns.patterns) == len(data["patterns"])
    assert patterns.patterns[0].occurrences == data["patterns"][0]["occurrences"]
    assert patterns.patterns[0].affected_threads == data["patterns"][0]["affected_threads"]


def test_get_metadata(files):
    data = investigate.get_metadata(files=files)[0]
    assert_declares(models.FileMetadata, data)
    meta = models.FileMetadata.model_validate(data)
    assert meta.lines == 7
    assert meta.log_levels == {"UNKNOWN": 1, "ERROR": 2, "INFO": 4}
    assert meta.unique_threads == 2


def test_get_context(files):
    data = investigate.get_context(file=files[0], line_number=5, lines_before=1, lines_after=1)
    assert_declares(models.ContextResult, data)
    context = models.ContextResult.model_validate(data)
    assert context.target.message == "child start"
    assert [e.message for e in context.context_before] == ["root start"]
    assert [e.message for e in context.context_after] == ["child error"]


def test_follow_thread_hierarchy_is_accepted(hierarchy):
    tree = models.ThreadHierarchy.model_validate(hierarchy)
    assert_declares(models.ThreadHierarchy, hierarchy)
    root = hierarchy["roots"][0]
    child = root["children"][0]
    assert_declares(models.SpanNode, root)
    assert_declares(models.SpanNode, child)
    assert_declares(models.BottleneckInfo, hierarchy["bottleneck"])
    assert tree.total_nodes == 2
    assert tree.roots[0].id == "span-root"
    assert tree.roots[0].children[0].id == "span-child"
    assert tree.roots[0].children[0].entry_ids == child["entry_ids"]
    assert tree.bottleneck is not None
    assert tree.bottleneck.node_id == "span-root"


def test_analyze_error_flow(hierarchy):
    data = investigate.analyze_error_flow(hierarchy)
    assert_declares(models.ErrorAnalysis, data)
    assert_declares(models.RootCause, data["root_causes"][0])
    assert_declares(models.ImpactSummary, data["impact_summary"])
    analysis = models.ErrorAnalysis.model_validate(data)
    assert analysis.has_errors is True
    assert [c.node_id for c in analysis.root_causes] == ["span-child"]
    assert analysis.root_causes[0].path == ["span-root", "span-child"]


def test_cross_service_timeline(files):
    data = investigate.cross_service_timeline(
        files={"api": files, "db": files}, trace_id="trace-123"
    )
    assert_declares(models.CrossServiceTimeline, data)
    assert_declares(models.TimelineEntry, data["timeline"][0])
    timeline = models.CrossServiceTimeline.model_validate(data)
    assert len(timeline.timeline) == len(data["timeline"])
    assert timeline.timeline[0].service == "api"


def test_smart_sample(files):
    data = investigate.smart_sample(files=files, strategy="representative", sample_size=3)
    assert_declares(models.SamplingResult, data)
    sample = models.SamplingResult.model_validate(data)
    assert sample.sample_size == 3
    assert len(sample.samples) == 3
    assert sample.total_population == 7


def test_detect_correlation_chains(files):
    data = investigate.detect_correlation_chains(files=files)
    assert_declares(models.CorrelationChains, data)
    chains = models.CorrelationChains.model_validate(data)
    assert chains.root_ids == ["abc"]
    assert chains.total_correlation_ids == 1
