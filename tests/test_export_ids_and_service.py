"""A trace export: the log's span ids when they are valid, stable ids otherwise, one
service per span, and one converter behind the library and `llm export`.

The expected ids are SHA-256 digests computed apart from the code under test.
"""

import json

import pytest

from logler import investigate
from logler import types as wire
from logler.investigate import (
    RUST_AVAILABLE,
    export_to_jaeger,
    export_to_otlp,
    export_to_zipkin,
)
from tests.conftest import invoke
from tests.test_models import assert_typed

pytestmark = pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust backend required")

TRACE = "4e4af1e8fe818e12e32bac7236e10825"  # sha256("req-123")[:32]
ROOT = "a1b2c3d4e5f60718"  # "A1B2C3D4E5F60718" kept, in lower case
ONE = "badc3b1222bae1ff"  # sha256("s-one")[:16]
PLAIN = "1b9e598d57da2c7f"  # sha256(TRACE + "/1")[:16]: the second root, no span id of its own
ROOT_US = 1_794_650_460_000_000  # 2026-11-14T10:01:00Z
CHILD_US = ROOT_US + 250_000


def _node(node_id, name, node_type="Span", children=(), service=None, **extra):
    return {
        "id": node_id,
        "node_type": node_type,
        "name": name,
        "children": list(children),
        "entry_ids": [f"e-{name}"],
        "entry_count": 1,
        "error_count": 0,
        "service": service,
        **extra,
    }


SMALL = {
    "roots": [
        _node(
            "A1B2C3D4E5F60718",
            "root",
            start_time="2026-11-14T10:01:00Z",
            duration_ms=1500,
            service="gateway",
            children=[
                _node(
                    "s-one",
                    "one",
                    start_time="2026-11-14T10:01:00.250Z",
                    duration_ms=250,
                    entry_count=2,
                    error_count=1,
                    service="billing",
                )
            ],
        ),
        _node("entry:x", "plain", node_type="Inferred", duration_ms=None),
    ]
}


def _attr(key, value):
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": value}}


def _resource(service, span):
    return {
        "resource": {"attributes": [_attr("service.name", service)]},
        "scopeSpans": [{"scope": {"name": "logler"}, "spans": [span]}],
    }


def test_otlp_export_is_the_otlp_json_shape():
    out = export_to_otlp(SMALL, identifier="req-123")
    assert out == {
        "resourceSpans": [
            _resource(
                "gateway",
                {
                    "traceId": TRACE,
                    "spanId": ROOT,
                    "name": "root",
                    "startTimeUnixNano": "1794650460000000000",
                    "endTimeUnixNano": "1794650461500000000",
                    "attributes": [
                        _attr("node_type", "Span"),
                        _attr("entry_count", 1),
                        _attr("error_count", 0),
                    ],
                },
            ),
            _resource(
                "billing",
                {
                    "traceId": TRACE,
                    "spanId": ONE,
                    "parentSpanId": ROOT,
                    "name": "one",
                    "startTimeUnixNano": "1794650460250000000",
                    "endTimeUnixNano": "1794650460500000000",
                    "attributes": [
                        _attr("node_type", "Span"),
                        _attr("entry_count", 2),
                        _attr("error_count", 1),
                    ],
                    "status": {"code": 2},
                },
            ),
            _resource(
                "logler-export",
                {
                    "traceId": TRACE,
                    "spanId": PLAIN,
                    "name": "plain",
                    "startTimeUnixNano": "0",
                    "endTimeUnixNano": "0",
                    "attributes": [
                        _attr("node_type", "Inferred"),
                        _attr("entry_count", 1),
                        _attr("error_count", 0),
                    ],
                },
            ),
        ]
    }


def test_otlp_export_is_described_by_its_typed_dict():
    assert_typed(
        wire.OtlpExport,
        export_to_otlp(SMALL, identifier="req-123"),
        export_to_otlp({"roots": []}),
    )


def _jaeger_tags(node_type, entries, errors):
    tags = [
        {"key": "node_type", "type": "string", "value": node_type},
        {"key": "entry_count", "type": "int64", "value": entries},
        {"key": "error_count", "type": "int64", "value": errors},
    ]
    if errors:
        tags.append({"key": "error", "type": "bool", "value": True})
    return tags


def _process(service):
    return {
        "serviceName": service,
        "tags": [{"key": "exported_by", "type": "string", "value": "logler"}],
    }


def test_jaeger_export_has_one_process_per_service():
    out = export_to_jaeger(SMALL, identifier="req-123")
    span = {"traceID": TRACE, "logs": [], "warnings": []}
    assert out == {
        "data": [
            {
                "traceID": TRACE,
                "spans": [
                    {
                        **span,
                        "spanID": ROOT,
                        "operationName": "root",
                        "references": [],
                        "startTime": ROOT_US,
                        "duration": 1_500_000,
                        "tags": _jaeger_tags("Span", 1, 0),
                        "processID": "p1",
                    },
                    {
                        **span,
                        "spanID": ONE,
                        "operationName": "one",
                        "references": [{"refType": "CHILD_OF", "traceID": TRACE, "spanID": ROOT}],
                        "startTime": CHILD_US,
                        "duration": 250_000,
                        "tags": _jaeger_tags("Span", 2, 1),
                        "processID": "p2",
                    },
                    {
                        **span,
                        "spanID": PLAIN,
                        "operationName": "plain",
                        "references": [],
                        "startTime": 0,
                        "duration": 0,
                        "tags": _jaeger_tags("Inferred", 1, 0),
                        "processID": "p3",
                    },
                ],
                "processes": {
                    "p1": _process("gateway"),
                    "p2": _process("billing"),
                    "p3": _process("logler-export"),
                },
                "warnings": [],
            }
        ]
    }


def test_zipkin_export_names_ids_parent_and_endpoint():
    out = export_to_zipkin(SMALL, identifier="req-123")
    assert out == [
        {
            "traceId": TRACE,
            "id": ROOT,
            "name": "root",
            "timestamp": ROOT_US,
            "duration": 1_500_000,
            "localEndpoint": {"serviceName": "gateway"},
            "tags": {"node_type": "Span", "entry_count": "1"},
        },
        {
            "traceId": TRACE,
            "id": ONE,
            "name": "one",
            "timestamp": CHILD_US,
            "duration": 250_000,
            "localEndpoint": {"serviceName": "billing"},
            "tags": {"node_type": "Span", "entry_count": "2", "error": "true"},
            "parentId": ROOT,
        },
        {
            "traceId": TRACE,
            "id": PLAIN,
            "name": "plain",
            "timestamp": 0,
            "duration": 0,
            "localEndpoint": {"serviceName": "logler-export"},
            "tags": {"node_type": "Inferred", "entry_count": "1"},
        },
    ]


HOSTILE = {
    "roots": [
        _node(
            "A1B2C3D4E5F60718",
            "root",
            children=[
                _node("s-one", "one"),
                # The same span listed twice, as under two parents
                _node("s-one", "one again", children=[_node("deadbeef", "short")]),
                # Equal after stripping "-" and padding to 16 characters
                _node("a-b", "dash"),
                _node("ab", "nodash"),
                _node("123e4567-e89b-12d3-a456-426614174000", "uuid"),
            ],
        ),
        _node("a1b2c3d4e5f60718", "root again"),
    ]
}
HOSTILE_IDS = {
    "root": ROOT,
    "one": ONE,
    "one again": "ce0176b393f78083",  # sha256("s-one#1")[:16]
    "short": "2baf1f40105d9501",  # sha256("deadbeef")[:16]
    "dash": "d44362d67d921091",  # sha256("a-b")[:16]
    "nodash": "fb8e20fc2e4c3f24",  # sha256("ab")[:16]
    "uuid": "986c0dc956dc822b",  # sha256("123e4567-...")[:16]
    "root again": "a74eb6c23defd76a",  # sha256("a1b2c3d4e5f60718#1")[:16]
}


def test_span_ids_kept_derived_and_never_shared():
    spans = export_to_zipkin(HOSTILE, identifier="req-123")
    assert {s["name"]: s["id"] for s in spans} == HOSTILE_IDS
    assert len(spans) == 8
    parents = {s["name"]: s.get("parentId") for s in spans}
    assert parents == {
        "root": None,
        "one": ROOT,
        "one again": ROOT,
        "short": "ce0176b393f78083",
        "dash": ROOT,
        "nodash": ROOT,
        "uuid": ROOT,
        "root again": None,
    }


def test_two_nodes_of_one_span_id_in_jaeger():
    spans = export_to_jaeger(HOSTILE, identifier="req-123")["data"][0]["spans"]
    assert {s["operationName"]: s["spanID"] for s in spans} == HOSTILE_IDS


@pytest.mark.parametrize(
    ("identifier", "trace_id"),
    [
        ("req-123", TRACE),
        ("0123456789ABCDEF0123456789ABCDEF", "0123456789abcdef0123456789abcdef"),
        # No identifier: derived from the ids of the roots, sha256("A1B2...\nentry:x")[:32]
        (None, "c34e71753eae2c7149d716f54b583b09"),
    ],
)
def test_trace_id(identifier, trace_id):
    jaeger = export_to_jaeger(SMALL, identifier=identifier)["data"][0]
    assert jaeger["traceID"] == trace_id
    assert {s["traceID"] for s in jaeger["spans"]} == {trace_id}
    assert {s["traceId"] for s in export_to_zipkin(SMALL, identifier=identifier)} == {trace_id}
    otlp = export_to_otlp(SMALL, identifier=identifier)["resourceSpans"]
    assert [s["traceId"] for r in otlp for s in r["scopeSpans"][0]["spans"]] == [trace_id] * 3


ZERO_SPAN = "fcdb4b423f4e5283"  # sha256("0" * 16)[:16]
ZERO_TRACE = "84e0c0eafaa95a34c293f278ac52e45c"  # sha256("0" * 32)[:32]


def test_an_all_zero_id_is_not_kept():
    """OTLP and W3C trace context call an all-zero id invalid; a logger writes it when no
    span is active. It is replaced like any other id that is not usable."""
    tree = {"roots": [_node("0" * 16, "root", children=[_node("0000000000000000", "again")])]}
    spans = export_to_zipkin(tree, identifier="0" * 32)
    assert [(s["name"], s["id"], s.get("parentId"), s["traceId"]) for s in spans] == [
        ("root", ZERO_SPAN, None, ZERO_TRACE),
        # The second node of the same id: sha256("0" * 16 + "#1")[:16]
        ("again", "be590deab7020377", ZERO_SPAN, ZERO_TRACE),
    ]
    jaeger = export_to_jaeger(tree, identifier="0" * 32)["data"][0]
    assert (jaeger["traceID"], [s["spanID"] for s in jaeger["spans"]]) == (
        ZERO_TRACE,
        [ZERO_SPAN, "be590deab7020377"],
    )
    otlp = export_to_otlp(tree, identifier="0" * 32)["resourceSpans"][0]["scopeSpans"][0]
    assert [(s["traceId"], s["spanId"]) for s in otlp["spans"]] == [
        (ZERO_TRACE, ZERO_SPAN),
        (ZERO_TRACE, "be590deab7020377"),
    ]


def test_nodes_with_no_service_are_under_the_default_service():
    # A hierarchy from before nodes named their service has no "service" key at all.
    for tree in (
        HOSTILE,
        {"roots": [{k: v for k, v in HOSTILE["roots"][0].items() if k != "service"}]},
    ):
        assert {s["localEndpoint"]["serviceName"] for s in export_to_zipkin(tree)} == {
            "logler-export"
        }
    otlp = export_to_otlp(HOSTILE)["resourceSpans"]
    assert [r["resource"]["attributes"] for r in otlp] == [[_attr("service.name", "logler-export")]]
    assert len(otlp[0]["scopeSpans"][0]["spans"]) == 8
    jaeger = export_to_jaeger(HOSTILE, service_name="mine")["data"][0]
    assert jaeger["processes"] == {"p1": _process("mine")}


def test_the_exporters_take_no_entries():
    for export in (export_to_jaeger, export_to_zipkin, export_to_otlp):
        with pytest.raises(TypeError, match="entries"):
            export(SMALL, entries=[])


# --- On a real log, and through the command -----------------------------------------------

LOG_ROOT = "a1b2c3d4e5f60718"
LOG_CHILD = "1122334455667788"
LINES = [
    {
        "timestamp": "2026-11-14T10:01:00Z",
        "level": "INFO",
        "message": "root",
        "trace_id": "t1",
        "span_id": LOG_ROOT,
        "service": "gateway",
    },
    {
        "timestamp": "2026-11-14T10:01:01Z",
        "level": "ERROR",
        "message": "child",
        "trace_id": "t1",
        "span_id": LOG_CHILD,
        "parent_span_id": LOG_ROOT,
        "service": "billing",
    },
    {"timestamp": "2026-11-14T10:01:02Z", "level": "INFO", "message": "plain", "trace_id": "t1"},
    # A second line of the child, under another service: the node keeps the first.
    {
        "timestamp": "2026-11-14T10:01:03Z",
        "level": "INFO",
        "message": "child again",
        "trace_id": "t1",
        "span_id": LOG_CHILD,
        "parent_span_id": LOG_ROOT,
        "service": "ledger",
    },
]
EXPORTERS = {"jaeger": export_to_jaeger, "zipkin": export_to_zipkin, "otlp": export_to_otlp}


@pytest.fixture
def trace_log(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in LINES))
    return str(path)


def _library_export(path, export_format):
    hierarchy = investigate.follow_thread_hierarchy([path], root_identifier="t1")
    return EXPORTERS[export_format](hierarchy, identifier="t1")


def test_real_log_keeps_its_span_ids_parent_and_services(trace_log):
    spans = _library_export(trace_log, "zipkin")
    assert [(s["name"], s["id"], s.get("parentId"), s["localEndpoint"]) for s in spans] == [
        ("root", LOG_ROOT, None, {"serviceName": "gateway"}),
        ("child", LOG_CHILD, LOG_ROOT, {"serviceName": "billing"}),
        # sha256(sha256("t1")[:32] + "/1")[:16]: the second root, with no span id
        ("plain", "45ebc264816e12ec", None, {"serviceName": "logler-export"}),
    ]
    assert {s["traceId"] for s in spans} == {"628b49d96dcde97a430dd4f597705899"}


def test_each_node_names_the_service_of_its_first_entry_that_has_one(trace_log):
    hierarchy = investigate.follow_thread_hierarchy([trace_log], root_identifier="t1")

    def walk(node):
        yield node["name"], node["entry_count"], node["service"]
        for child in node["children"]:
            yield from walk(child)

    assert [n for root in hierarchy["roots"] for n in walk(root)] == [
        ("root", 1, "gateway"),
        ("child", 2, "billing"),
        ("plain", 1, None),
    ]


def test_a_plain_text_log_puts_every_span_under_the_default_service(tmp_path):
    path = tmp_path / "plain.log"
    path.write_text(
        "2026-11-14T10:01:00Z INFO [worker-1] start\n2026-11-14T10:01:01Z ERROR [worker-1] failed\n"
    )
    hierarchy = investigate.follow_thread_hierarchy([str(path)], root_identifier="worker-1")
    assert [(r["name"], r["entry_count"], r["service"]) for r in hierarchy["roots"]] == [
        ("2026-11-14T10:01:00Z INFO [worker-1] start", 2, None)
    ]
    spans = export_to_zipkin(hierarchy, identifier="worker-1")
    assert [s["localEndpoint"] for s in spans] == [{"serviceName": "logler-export"}]


@pytest.mark.parametrize("export_format", ["jaeger", "zipkin", "otlp"])
def test_command_export_is_the_library_export(trace_log, export_format):
    code, out, _ = invoke(["export", "t1", "-f", trace_log, "--format", export_format])
    assert code == 0
    assert json.loads(out) == {
        "identifier": "t1",
        "format": export_format,
        "span_count": 3,
        "export": _library_export(trace_log, export_format),
    }


@pytest.mark.parametrize("export_format", ["jaeger", "zipkin", "otlp"])
def test_an_export_run_twice_is_the_same(trace_log, export_format):
    assert _library_export(trace_log, export_format) == _library_export(trace_log, export_format)
    first = invoke(["export", "t1", "-f", trace_log, "--format", export_format])
    second = invoke(["export", "t1", "-f", trace_log, "--format", export_format])
    assert first == second
    assert first[0] == 0
