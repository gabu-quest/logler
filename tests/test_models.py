"""The exported pydantic models accept what the public `investigate` functions return.

Each test validates the real output of one function on one fixture, and checks that every key
the API returns is a declared field of the model (a model that declares none of them would
validate anything, with every field at its default).
"""

import json
import types as pytypes
import typing
from typing import Any, Literal, NotRequired, TypedDict

import pytest

from logler import investigate, models
from logler import types as wire

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


# ---------------------------------------------------------------------------
# The typed dicts of `logler.types` against the real output of the functions that return them.
# One checker, driven by the annotations: no list of keys is written by hand.
# ---------------------------------------------------------------------------


def _unwrap(annotation):
    """The annotation under `NotRequired`, `Required` and `Annotated`."""
    while typing.get_origin(annotation) in (NotRequired, typing.Required, typing.Annotated):
        annotation = typing.get_args(annotation)[0]
    return annotation


def _is_union(annotation):
    return typing.get_origin(annotation) in (typing.Union, pytypes.UnionType)


def _describe(annotation):
    if annotation is type(None):
        return "None"
    if isinstance(annotation, type) and typing.get_origin(annotation) is None:
        return annotation.__name__
    return str(annotation).replace("typing.", "")


def _typed_dicts_in(annotation):
    """Every typed dict an annotation can hold: in a union, a list or a mapping's values."""
    annotation = _unwrap(annotation)
    args = typing.get_args(annotation)
    if typing.is_typeddict(annotation):
        return [annotation]
    if _is_union(annotation) or typing.get_origin(annotation) is list:
        return [c for arg in args for c in _typed_dicts_in(arg)]
    if typing.get_origin(annotation) is dict and len(args) == 2:
        return _typed_dicts_in(args[1])
    return []


def _value_problems(annotation, value, path, visited):
    """Every way `value` differs from `annotation`; `visited` collects the typed dicts seen."""
    annotation = _unwrap(annotation)
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    wrong = f"{path}: expected {_describe(annotation)}, got {type(value).__name__}"
    if annotation is typing.Any:
        return []
    if annotation is type(None) or annotation is None:
        return [] if value is None else [wrong]
    if typing.is_typeddict(annotation):
        return typed_dict_problems(annotation, value, path, visited)
    if _is_union(annotation):
        # each alternative counts its own visits; only the one that is taken keeps them
        attempts = []
        for arg in args:
            seen: set = set()
            attempts.append((arg, _value_problems(arg, value, path, seen), seen))
        for _, problems, seen in attempts:
            if not problems:
                visited |= seen
                return []
        others = [a for a in attempts if a[0] is not type(None)]
        if len(others) == 1 and isinstance(value, dict | list):  # `X | None` holding a container
            visited |= others[0][2]
            return others[0][1]
        return [wrong]
    if origin is typing.Literal:
        if any(value == arg and type(value) is type(arg) for arg in args):
            return []
        return [f"{path}: expected {_describe(annotation)}, got {value!r}"]
    if annotation is bool:
        return [] if isinstance(value, bool) else [wrong]
    if annotation is int:
        return [] if isinstance(value, int) and not isinstance(value, bool) else [wrong]
    if annotation is float:
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        return [] if ok else [wrong]
    if annotation is str:
        return [] if isinstance(value, str) else [wrong]
    if annotation is list or origin is list:
        if not isinstance(value, list):
            return [wrong]
        problems = []
        for i, item in enumerate(value):
            if args:
                problems += _value_problems(args[0], item, f"{path}[{i}]", visited)
        return problems
    if annotation is dict or origin is dict:
        if not isinstance(value, dict):
            return [wrong]
        problems = []
        for name, item in value.items():
            if args and args[0] is str and not isinstance(name, str):
                problems.append(f"{path}: key {name!r} is not a str")
            elif args:
                problems += _value_problems(args[1], item, f"{path}[{name!r}]", visited)
        return problems
    raise TypeError(f"the checker does not know the annotation {annotation!r} at {path}")


def typed_dict_problems(cls, data, path="$", visited=None):
    """Every way `data` differs from the typed dict `cls`, nested typed dicts included.

    A key `cls` does not declare, a required key missing from `data`, and a value the annotation
    of its key does not allow (type, `Literal`, union, list items, mapping values, nested typed
    dicts). `visited`, when given, collects every typed dict that was looked at.
    """
    if visited is None:
        visited = set()
    if not isinstance(data, dict):
        return [f"{path}: expected a dict for {cls.__name__}, got {type(data).__name__}"]
    visited.add(cls)
    hints = typing.get_type_hints(cls, include_extras=True)
    problems = [
        f"{path}: key {k!r} is not declared by {cls.__name__}" for k in data if k not in hints
    ]
    problems += [
        f"{path}: required key {k!r} of {cls.__name__} is missing"
        for k in sorted(cls.__required_keys__)
        if k not in data
    ]
    for key, value in data.items():
        if key in hints:
            problems += _value_problems(hints[key], value, f"{path}.{key}", visited)
    return problems


def _required_reach(cls):
    """The typed dicts reachable from `cls` through required keys, `cls` itself left out."""
    reached: set = set()
    todo = [cls]
    while todo:
        current = todo.pop()
        hints = typing.get_type_hints(current, include_extras=True)
        for key in current.__required_keys__:
            for target in _typed_dicts_in(hints[key]):
                if target is not cls and target not in reached:
                    reached.add(target)
                    todo.append(target)
    return reached


def check_typed(cls, *outputs, not_exercised=None):
    """Every problem of the outputs against `cls`, and every typed dict none of them reached.

    A typed dict reachable from `cls` through required keys that nothing in the outputs reached (an
    empty list, a None) is a problem, unless `not_exercised` names it with the reason no
    ordinary input produces one: `{TypedDictClass: "reason"}`.
    """
    visited: set = set()
    problems = [p for data in outputs for p in typed_dict_problems(cls, data, "$", visited)]
    excused = not_exercised or {}
    reach = _required_reach(cls)
    for target, reason in excused.items():
        if target in visited:
            problems.append(
                f"$: not_exercised names {target.__name__}, but the call checked one: remove it"
            )
        elif target not in reach:
            problems.append(
                f"$: not_exercised names {target.__name__}, which is not reachable from "
                f"{cls.__name__} through required keys"
            )
        elif not isinstance(reason, str) or not reason.strip():
            problems.append(f"$: not_exercised needs a reason for {target.__name__}")
    missed = sorted(t.__name__ for t in reach if t not in visited and t not in excused)
    if missed:
        names = ", ".join(missed)
        verb = "are" if len(missed) > 1 else "is"
        what = "them" if len(missed) > 1 else "it"
        problems.append(
            f"$: {names} {verb} reachable through required keys of {cls.__name__} "
            f"but nothing of {what} was checked"
        )
    return problems


def assert_typed(cls, *outputs, not_exercised=None):
    """`data` is described by the typed dict `cls`: keys, value types, nested, nothing unseen."""
    assert check_typed(cls, *outputs, not_exercised=not_exercised) == []


class _Inner(TypedDict):
    name: str


class _Outer(TypedDict):
    id: int
    inner: _Inner
    items: list[_Inner]
    maybe: NotRequired[_Inner | None]


def test_checker_accepts_a_matching_output():
    data = {"id": 1, "inner": {"name": "a"}, "items": [{"name": "b"}], "maybe": None}
    assert_typed(_Outer, data)
    assert_typed(_Outer, {"id": 1, "inner": {"name": "a"}, "items": []})


def test_checker_rejects_a_key_the_output_has_and_the_class_does_not_declare():
    data = {"id": 1, "inner": {"name": "a"}, "items": [], "extra": 2}
    assert typed_dict_problems(_Outer, data) == ["$: key 'extra' is not declared by _Outer"]


def test_checker_rejects_a_required_key_the_output_lacks():
    assert typed_dict_problems(_Outer, {"id": 1, "inner": {"name": "a"}}) == [
        "$: required key 'items' of _Outer is missing"
    ]


def test_checker_goes_down_into_a_field_a_list_and_an_optional():
    data = {
        "id": 1,
        "inner": {"name": "a", "x": 1},
        "items": [{"name": "b"}, {"nom": "c"}],
        "maybe": {"name": "d", "y": 2},
    }
    assert typed_dict_problems(_Outer, data) == [
        "$.inner: key 'x' is not declared by _Inner",
        "$.items[1]: key 'nom' is not declared by _Inner",
        "$.items[1]: required key 'name' of _Inner is missing",
        "$.maybe: key 'y' is not declared by _Inner",
    ]


class _Scalars(TypedDict):
    text: str
    count: int
    ratio: float
    flag: bool
    nothing: None
    anything: Any
    mode: Literal["a", "b"]
    either: int | str
    maybe: str | None
    numbers: list[int]
    by_name: dict[str, float]
    inner: _Inner


_SCALARS = {
    "text": "t",
    "count": 1,
    "ratio": 0.5,
    "flag": True,
    "nothing": None,
    "anything": object(),
    "mode": "a",
    "either": "x",
    "maybe": None,
    "numbers": [1, 2],
    "by_name": {"k": 1.5},
    "inner": {"name": "n"},
}


def test_checker_accepts_values_the_annotations_allow():
    assert typed_dict_problems(_Scalars, _SCALARS) == []
    # an int is accepted where a float is declared; a union and an optional take either side
    loose = {**_SCALARS, "ratio": 3, "either": 4, "maybe": "m", "anything": None}
    assert typed_dict_problems(_Scalars, loose) == []


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("text", 1, "$.text: expected str, got int"),
        ("count", "1", "$.count: expected int, got str"),
        ("count", 1.5, "$.count: expected int, got float"),
        ("count", True, "$.count: expected int, got bool"),
        ("ratio", "x", "$.ratio: expected float, got str"),
        ("ratio", False, "$.ratio: expected float, got bool"),
        ("flag", 1, "$.flag: expected bool, got int"),
        ("nothing", 0, "$.nothing: expected None, got int"),
        ("mode", "c", "$.mode: expected Literal['a', 'b'], got 'c'"),
        ("either", 1.5, "$.either: expected int | str, got float"),
        ("maybe", 3, "$.maybe: expected str | None, got int"),
        ("numbers", "ab", "$.numbers: expected list[int], got str"),
        ("numbers", [1, "x"], "$.numbers[1]: expected int, got str"),
        ("by_name", [], "$.by_name: expected dict[str, float], got list"),
        ("by_name", {"k": "v"}, "$.by_name['k']: expected float, got str"),
        ("by_name", {1: 1.0}, "$.by_name: key 1 is not a str"),
        ("inner", 5, "$.inner: expected a dict for _Inner, got int"),
        ("inner", {"name": 5}, "$.inner.name: expected str, got int"),
    ],
)
def test_checker_rejects_a_value_the_annotation_does_not_allow(key, value, expected):
    assert typed_dict_problems(_Scalars, {**_SCALARS, key: value}) == [expected]


class _Deep(TypedDict):
    value: int


class _Mid(TypedDict):
    deep: _Deep | None


class _Side(TypedDict):
    x: int


class _Top(TypedDict):
    mids: list[_Mid]
    side: NotRequired[_Side]


class _Node(TypedDict):
    children: list["_Node"]


def test_checker_fails_when_a_nested_class_was_never_looked_at():
    assert check_typed(_Top, {"mids": []}) == [
        "$: _Deep, _Mid are reachable through required keys of _Top but nothing of them was checked"
    ]
    assert check_typed(_Top, {"mids": [{"deep": None}]}) == [
        "$: _Deep is reachable through required keys of _Top but nothing of it was checked"
    ]
    # a class behind a NotRequired key is not demanded, and the class itself needs no visit
    assert check_typed(_Top, {"mids": [{"deep": {"value": 1}}]}) == []
    assert check_typed(_Node, {"children": []}) == []


def test_checker_takes_a_named_class_the_input_cannot_produce():
    top = {"mids": [{"deep": None}]}
    assert check_typed(_Top, top, not_exercised={_Deep: "no input gives one"}) == []
    assert check_typed(_Top, {"mids": []}, not_exercised={_Deep: "no input gives one"}) == [
        "$: _Mid is reachable through required keys of _Top but nothing of it was checked"
    ]


def test_checker_counts_what_any_of_several_outputs_reached():
    full = {"mids": [{"deep": {"value": 1}}]}
    assert check_typed(_Top, {"mids": []}, full) == []
    assert check_typed(_Top, {"mids": []}, {"mids": [{"deep": None}]}) == [
        "$: _Deep is reachable through required keys of _Top but nothing of it was checked"
    ]
    assert check_typed(_Top, full, {"mids": [{"deep": {"value": "x"}}]}) == [
        "$.mids[0].deep.value: expected int, got str"
    ]


def test_checker_rejects_a_not_exercised_entry_that_is_wrong():
    full = {"mids": [{"deep": {"value": 1}}]}
    assert check_typed(_Top, full, not_exercised={_Deep: "stale"}) == [
        "$: not_exercised names _Deep, but the call checked one: remove it"
    ]
    assert check_typed(_Top, full, not_exercised={_Side: "off the path"}) == [
        "$: not_exercised names _Side, which is not reachable from _Top through required keys"
    ]
    assert check_typed(_Top, {"mids": [{"deep": None}]}, not_exercised={_Deep: ""}) == [
        "$: not_exercised needs a reason for _Deep"
    ]


def _typed_dicts_of_types_module():
    return [
        c for c in vars(wire).values() if typing.is_typeddict(c) and c.__module__ == wire.__name__
    ]


def test_every_not_required_key_of_types_is_seen_as_optional_by_typing():
    """With `from __future__ import annotations` typing cannot see `NotRequired`, so a class
    would call every key required; the module must not use it."""
    classes = _typed_dicts_of_types_module()
    assert len(classes) >= 40
    for cls in classes:
        marked = {
            k
            for k, hint in typing.get_type_hints(cls, include_extras=True).items()
            if typing.get_origin(hint) is NotRequired
        }
        assert sorted(marked - cls.__optional_keys__) == [], cls.__name__
        assert sorted(cls.__optional_keys__ - marked) == [], cls.__name__


# The typed dicts name their function in the docstring ("Return type of :func:`x`"); no function
# annotation names one, so each test below calls the function and names the class itself. A test
# that needs an input the module fixture cannot give writes its own small file with tmp_path.

CHAIN_LINES = [
    # a parent request that spawns two child requests
    {
        "timestamp": "2024-01-15T11:00:00.000Z",
        "level": "INFO",
        "message": "spawn a",
        "correlation_id": "req-parent",
        "child_correlation_id": "req-child-a",
    },
    {
        "timestamp": "2024-01-15T11:00:00.100Z",
        "level": "INFO",
        "message": "spawn b",
        "correlation_id": "req-parent",
        "child_correlation_id": "req-child-b",
    },
    # one trace whose root span and child span both log an error
    {
        "timestamp": "2024-01-15T11:00:01.000Z",
        "level": "ERROR",
        "message": "root failed",
        "trace_id": "trace-err",
        "span_id": "e-root",
        "thread_id": "w1",
    },
    {
        "timestamp": "2024-01-15T11:00:01.500Z",
        "level": "ERROR",
        "message": "child failed",
        "trace_id": "trace-err",
        "span_id": "e-child",
        "parent_span_id": "e-root",
        "thread_id": "w2",
    },
    {
        "timestamp": "2024-01-15T11:00:02.000Z",
        "level": "INFO",
        "message": "root end",
        "trace_id": "trace-err",
        "span_id": "e-root",
        "thread_id": "w1",
    },
]


@pytest.fixture(scope="module")
def chain_files(tmp_path_factory):
    """Five JSON lines: request `req-parent` spawns `req-child-a` and `req-child-b` (two
    correlation chains); trace `trace-err` has a root span and a child span that each log an
    ERROR (one propagation chain, child to root)."""
    path = tmp_path_factory.mktemp("chains") / "chains.log"
    path.write_text("".join(json.dumps(line) + "\n" for line in CHAIN_LINES))
    return [str(path)]


@pytest.fixture
def untimed_files(tmp_path):
    """Two plain lines with no timestamp, no level and no id."""
    path = tmp_path / "untimed.log"
    path.write_text("hello\nworld\n")
    return [str(path)]


def test_typed_search_full(files):
    data = investigate.search(files=files)
    assert_typed(wire.SearchResult, data)
    by_line = {item["entry"]["line_number"]: item for item in data["results"]}
    assert sorted(by_line) == [1, 2, 3, 4, 5, 6, 7]
    assert by_line[3]["entry"]["level"] == "UNKNOWN"
    assert by_line[2]["context_after"][0]["level"] == "UNKNOWN"
    assert by_line[2]["context_before"][0]["level"] == "INFO"


def test_typed_search_summary(files):
    """`by_file` and `full_results_available` are returned only when something matched."""
    full = investigate.search(files=files, output_format="summary")
    empty = investigate.search(files=files, query="zzz-nothing", output_format="summary")
    assert_typed(wire.SearchSummaryResult, full, empty)
    assert full["by_file"] == {files[0]: 7}
    assert full["full_results_available"] is True
    assert "by_file" not in empty
    assert "full_results_available" not in empty


def test_typed_search_count(files):
    assert_typed(wire.SearchCountResult, investigate.search(files=files, output_format="count"))


def test_typed_search_compact(files):
    assert_typed(wire.SearchCompactResult, investigate.search(files=files, output_format="compact"))


def test_typed_extract_ids(files, untimed_files):
    data = investigate.extract_ids(files=files)
    untimed = investigate.extract_ids(files=untimed_files)
    assert_typed(wire.ExtractedIds, data, untimed)
    assert data["thread_ids"][0] == {
        "id": "worker-1",
        "count": 4,
        "first_seen": "2024-01-15T10:00:00Z",
        "last_seen": "2024-01-15T10:00:03Z",
    }
    assert data["time_range"] == {"start": "2024-01-15T10:00:00Z", "end": "2024-01-15T10:00:03Z"}
    assert untimed["time_range"] is None


def test_typed_follow_thread(files):
    assert_typed(
        wire.FollowThreadResult, investigate.follow_thread(files=files, thread_id="worker-1")
    )


def test_typed_get_context(files):
    data = investigate.get_context(file=files[0], line_number=5, lines_before=1, lines_after=1)
    assert_typed(wire.ContextResult, data)


def test_typed_find_patterns(files):
    assert_typed(wire.PatternResult, investigate.find_patterns(files=files, min_occurrences=1))


def test_typed_get_metadata(files, untimed_files):
    timed = investigate.get_metadata(files=files)[0]
    untimed = investigate.get_metadata(files=untimed_files)[0]
    assert_typed(wire.FileMetadataInfo, timed, untimed)
    assert untimed["time_range"] is None


def test_typed_follow_thread_hierarchy(hierarchy):
    assert_typed(wire.HierarchyResult, hierarchy)


def test_typed_hierarchy_with_correlation_chains(files, chain_files, hierarchy):
    """`follow_thread_hierarchy` returns none of the five chain keys; with chains on, the
    function adds two, and three more only when a chain was found."""
    five = {
        "correlation_chains",
        "chained_correlation_ids",
        "has_correlation_chains",
        "correlation_chain_count",
        "related_correlation_ids",
    }
    assert five & set(hierarchy) == set()
    off = investigate.build_hierarchy_with_correlation_chains(
        files=files, root_identifier="trace-123", include_correlation_chains=False
    )
    assert five & set(off) == set()
    none = investigate.build_hierarchy_with_correlation_chains(
        files=files, root_identifier="trace-123"
    )
    assert five & set(none) == {"correlation_chains", "chained_correlation_ids"}
    found = investigate.build_hierarchy_with_correlation_chains(
        files=chain_files, root_identifier="req-parent"
    )
    assert five & set(found) == five
    assert found["correlation_chain_count"] == 2
    assert found["related_correlation_ids"] == ["req-child-a", "req-child-b"]
    assert_typed(wire.HierarchyResult, hierarchy, off, none, found)


def test_typed_analyze_error_flow(hierarchy, chain_files):
    """The module fixture has no error that spread; the trace in `chain_files` has one."""
    spread = investigate.analyze_error_flow(
        investigate.follow_thread_hierarchy(files=chain_files, root_identifier="trace-err")
    )
    assert [c["root_cause"] for c in spread["propagation_chains"]] == ["e-child"]
    assert_typed(wire.ErrorFlowResult, investigate.analyze_error_flow(hierarchy), spread)


def test_typed_analyze_bottlenecks(hierarchy):
    assert_typed(wire.BottleneckAnalysis, investigate.analyze_bottlenecks(hierarchy))


def test_typed_diff_hierarchies(hierarchy):
    assert_typed(wire.HierarchyDiffResult, investigate.diff_hierarchies(hierarchy, hierarchy))


def test_typed_detect_correlation_chains(files, chain_files):
    """The module fixture has one correlation id and no chain; `chain_files` has two."""
    none = investigate.detect_correlation_chains(files=files)
    two = investigate.detect_correlation_chains(files=chain_files)
    assert none["chains"] == []
    assert [c["child_correlation_id"] for c in two["chains"]] == ["req-child-a", "req-child-b"]
    assert_typed(wire.CorrelationChainResult, none, two)


def test_typed_compare_threads(files):
    data = investigate.compare_threads(files=files, thread_a="worker-1", thread_b="worker-2")
    assert_typed(wire.ThreadComparison, data)


def test_typed_compare_time_periods(files):
    data = investigate.compare_time_periods(
        files=files,
        period_a_start="2024-01-15T10:00:00Z",
        period_a_end="2024-01-15T10:00:00.600Z",
        period_b_start="2024-01-15T10:00:00.600Z",
        period_b_end="2024-01-15T10:00:02Z",
    )
    assert_typed(wire.PeriodComparison, data)


def test_typed_cross_service_timeline(files):
    data = investigate.cross_service_timeline(
        files={"api": files, "db": files}, trace_id="trace-123"
    )
    assert_typed(wire.CrossServiceTimelineResult, data)


def test_typed_smart_sample(files):
    """`coverage` is an empty dict when the population is empty."""
    data = investigate.smart_sample(files=files, strategy="representative", sample_size=3)
    nothing = investigate.smart_sample(files=files, level="FATAL")
    assert nothing["total_population"] == 0
    assert nothing["coverage"] == {}
    assert_typed(wire.SampleResult, data, nothing)


def test_typed_export_to_jaeger(hierarchy):
    assert_typed(wire.JaegerExport, investigate.export_to_jaeger(hierarchy))


def test_typed_export_to_zipkin(hierarchy):
    """`parentId` is returned only for a span that has a parent."""
    spans = investigate.export_to_zipkin(hierarchy)
    assert len(spans) == 2
    assert "parentId" not in spans[0]
    assert spans[1]["parentId"] == spans[0]["id"]
    assert_typed(wire.ZipkinSpan, *spans)


def test_typed_extract_metrics(files):
    assert_typed(wire.MetricsExtractionResult, investigate.extract_metrics(files=files))


def test_typed_extract_metrics_conditional_keys(files, tmp_path):
    """`buckets` is returned only when `bucket_size` is given; `unit` only when every point of
    the field has the same unit (`timeout=30s` has one, a JSON number has none)."""
    path = tmp_path / "latency.log"
    path.write_text(
        json.dumps({"timestamp": "2024-01-15T10:00:00Z", "level": "INFO", "message": "x", "ms": 5})
        + "\n"
    )
    plain = investigate.extract_metrics(files=files)
    bucketed = investigate.extract_metrics(files=files, bucket_size="1m")
    no_unit = investigate.extract_metrics(files=[str(path)])
    assert_typed(wire.MetricsExtractionResult, plain, bucketed, no_unit)
    assert list(plain["fields"]["timeout"]) == [
        "count",
        "stats",
        "first_timestamp",
        "last_timestamp",
        "anomalies",
        "unit",
    ]
    assert list(bucketed["fields"]["timeout"])[-2:] == ["buckets", "unit"]
    assert list(no_unit["fields"]) == ["ms"]
    assert "unit" not in no_unit["fields"]["ms"]


def test_typed_detect_formats(files):
    assert_typed(wire.FormatDetectionResult, investigate.detect_formats(files=files))


def test_typed_mine_log_templates(files):
    assert_typed(wire.TemplateMiningResult, investigate.mine_log_templates(files=files))
