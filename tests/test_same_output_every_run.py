"""The same command on the same files prints the same output, run after run.

Each command runs three times, each in its own process with its own PYTHONHASHSEED, over
files built to expose every place an order could come from a hash map or a set: one trace
spread over several files (each file starts with its own message), entries with five custom
fields, ids that tie on count, more thread ids than `schema` shows, and a line with no level.
Only what is random on purpose is blanked: the entry UUIDs and the timings.

The library calls that build a result from a set are run the same way: a small script per
call prints its result as JSON (no sort_keys) over files that give it a real tie.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

SEEDS = ("1", "2", "3")
SRC = str(Path(__file__).resolve().parent.parent / "src")
NAMES = ("api", "auth", "billing", "cache", "db", "edge")
UUID_LEN = 36
TIMING_KEYS = {"search_time_ms", "elapsed_ms", "query_time_ms", "generated_at"}


@pytest.fixture(scope="module")
def logs(tmp_path_factory) -> list[str]:
    folder = tmp_path_factory.mktemp("same_output")
    paths = []
    for i, name in enumerate(NAMES):
        lines = []
        for j in range(6):
            entry = {
                "timestamp": f"2026-11-14T10:00:0{j}.{i}00Z",
                "message": f"{name} step {j}" if j != 2 else f"{name} failed to reach peer {j}",
                # two threads per file: twelve ids, each with the same count
                "thread_id": f"{name}-worker-{j % 2}",
                "correlation_id": "req-1",
                "trace_id": "trace-1",
                "span_id": f"span-{name}",
                "service": name,
                "alpha": j,
                "bravo": f"b{j}",
                "charlie": j * 2,
                "delta": name,
                f"{name}_only": True,
            }
            if j == 2:
                entry["level"] = "ERROR"
            elif j != 3:  # line 3 has no level at all
                entry["level"] = "INFO"
            if name != "api":
                entry["parent_span_id"] = "span-api"
            lines.append(json.dumps(entry))
        path = folder / f"{name}.log"
        path.write_text("\n".join(lines) + "\n")
        paths.append(str(path))
    return paths


PIN_TRACE = "trace-pin"
SERVICES = ("svc-m", "svc-c", "svc-q", "svc-a", "svc-t")
PIN_COMMAND = ["llm", "hierarchy", PIN_TRACE]


@pytest.fixture(scope="module")
def lib_logs(tmp_path_factory) -> dict[str, str]:
    """Files whose library results hold two or more values with no order of their own."""
    folder = tmp_path_factory.mktemp("same_output_lib")

    def write(name: str, entries: list[dict]) -> str:
        path = folder / name
        path.write_text("".join(json.dumps(e) + "\n" for e in entries))
        return str(path)

    def folder_text(name: str, lines: list[str]) -> str:
        path = folder / name
        path.write_text("".join(line + "\n" for line in lines))
        return str(path)

    # Two threads with twelve messages each that the other lacks, five services, four levels.
    threads = []
    for who, levels in (("ta", ("INFO", "WARN", "ERROR", "DEBUG")), ("tb", ("INFO", "ERROR"))):
        for j in range(12):
            threads.append(
                {
                    "timestamp": f"2026-11-14T10:00:{j:02d}Z",
                    "level": levels[j % len(levels)],
                    "message": f"{who} message {j}",
                    "thread_id": who,
                    "service": SERVICES[j % len(SERVICES)],
                }
            )
    # Five services on one request. Only a logfmt line keeps `service` in its fields,
    # which is where `trace_request` looks.
    request = [
        f"ts=2026-11-14T10:01:0{j}Z level=INFO msg=step{j} correlation_id=req-svc service={name}"
        for j, name in enumerate(SERVICES)
    ]
    periods = [
        {
            "timestamp": f"2026-11-14T{hour}:00:{j:02d}Z",
            "level": "ERROR",
            "message": f"{word} error {j}",
            "thread_id": f"p-{hour}",
        }
        for hour, word in (("11", "before"), ("12", "after"))
        for j in range(6)
    ]
    # One correlation id that spawns six children.
    chain = [
        {
            "timestamp": f"2026-11-14T13:00:{j:02d}Z",
            "level": "INFO",
            "message": f"spawn {j}",
            "correlation_id": "req-parent",
            "child_correlation_id": f"req-child-{'zyxwvu'[j]}",
        }
        for j in range(6)
    ]
    # Five lines that carry only a trace id and one timestamp.
    pin = [
        {"timestamp": "2026-11-14T14:00:00Z", "trace_id": PIN_TRACE, "message": f"pin {name}"}
        for name in ("e", "d", "c", "b", "a")
    ]
    return {
        "threads": write("threads.log", threads),
        "request": folder_text("request.log", request),
        "periods": write("periods.log", periods),
        "chain": write("chain.log", chain),
        "pin": write("pin.log", pin),
    }


LIB_SCRIPT = """
import json, sys
from logler.comparison import compare_threads, compare_time_periods
from logler.helpers import trace_request
from logler.hierarchy import detect_correlation_chains, diff_hierarchies
from logler.parser import LogEntry
from logler.tracker import ThreadTracker

case, threads, periods, chain, request = sys.argv[1:6]


def tree(prefix, ids):
    kids = [{"id": f"{prefix}-{i}", "duration_ms": 5, "children": []} for i in ids]
    return {"roots": [{"id": "root", "duration_ms": 50, "children": kids}]}


def tracker():
    t = ThreadTracker()
    for j, name in enumerate("zyxwv"):
        t.track(LogEntry(line_number=j, raw="", thread_id="t", correlation_id=f"c-{name}",
                         trace_id="tr", service_name=f"svc-{name}"))
    return t


calls = {
    "compare_threads": lambda: compare_threads([threads], thread_a="ta", thread_b="tb"),
    "compare_time_periods": lambda: compare_time_periods(
        [periods], "2026-11-14T11:00:00Z", "2026-11-14T11:59:59Z",
        "2026-11-14T12:00:00Z", "2026-11-14T12:59:59Z"),
    "trace_request": lambda: trace_request([request], "req-svc"),
    "detect_correlation_chains": lambda: detect_correlation_chains([chain]),
    "diff_hierarchies": lambda: diff_hierarchies(tree("a", "zyxwvu"), tree("b", "tsrqpo")),
    "tracker thread": lambda: tracker().get_thread("t"),
    "tracker trace": lambda: tracker().get_trace("tr"),
}
print(json.dumps(calls[case](), default=str))
"""
LIB_CASES = (
    "compare_threads",
    "compare_time_periods",
    "trace_request",
    "detect_correlation_chains",
    "diff_hierarchies",
    "tracker thread",
    "tracker trace",
)


def _with_files(flag: str, files: list[str]) -> list[str]:
    return [arg for f in files for arg in (flag, f)]


def _commands(files: list[str]) -> dict[str, list[str]]:
    sample = ["llm", "sample", *files, "--size", "7", "--strategy"]
    return {
        "hierarchy by trace id": ["llm", "hierarchy", "trace-1", *_with_files("-f", files)],
        "hierarchy by correlation id": ["llm", "hierarchy", "req-1", *_with_files("-f", files)],
        "bottleneck": ["llm", "bottleneck", "trace-1", *_with_files("-f", files)],
        "correlate": ["llm", "correlate", "req-1", *_with_files("-f", files)],
        "search": ["llm", "search", *files],
        "search by level": ["llm", "search", *files, "--level", "ERROR"],
        "ids": ["llm", "ids", *files],
        "summarize": ["llm", "summarize", *files],
        "triage": ["llm", "triage", *files],
        "schema": ["llm", "schema", *files],
        "sample diverse": [*sample, "diverse"],
        "sample errors_focused": [*sample, "errors_focused"],
        "sample head": [*sample, "head"],
        "sample tail": [*sample, "tail"],
        "sample edges": [*sample, "edges"],
        "verify-pattern": [
            "llm",
            "verify-pattern",
            *files,
            "--pattern",
            r"step (\d)",
            "--extract-groups",
        ],
        "emit": ["llm", "emit", *files],
        "metrics": ["llm", "metrics", *files],
        "templates": ["llm", "templates", *files],
        "detect": ["llm", "detect", *files],
        "export jaeger": ["llm", "export", "trace-1", *_with_files("-f", files)],
        "export zipkin": [
            "llm",
            "export",
            "trace-1",
            "--format",
            "zipkin",
            *_with_files("-f", files),
        ],
        "export otlp": [
            "llm",
            "export",
            "trace-1",
            "--format",
            "otlp",
            *_with_files("-f", files),
        ],
        "sql": [
            "llm",
            "sql",
            "SELECT file, line_number, message FROM logs",
            *_with_files("-f", files),
        ],
        "compare": ["llm", "compare", "api-worker-0", "db-worker-1", *_with_files("-f", files)],
        "diff": [
            "llm",
            "diff",
            *files,
            "--before-start",
            "2026-11-14T10:00:00Z",
            "--before-end",
            "2026-11-14T10:00:02Z",
            "--after-start",
            "2026-11-14T10:00:02Z",
            "--after-end",
            "2026-11-14T10:00:06Z",
        ],
        "stats": ["stats", *files, "--json"],
    }


def _is_uuid(value) -> bool:
    return isinstance(value, str) and len(value) == UUID_LEN and value.count("-") == 4


def _blank(x):
    """Blank only what is random on purpose: entry UUIDs and timings. Keeps key order."""
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if k == "entry_ids" or (k == "id" and _is_uuid(v)) or k in TIMING_KEYS:
                out[k] = None
            else:
                out[k] = _blank(v)
        return out
    if isinstance(x, list):
        return [_blank(v) for v in x]
    return x


def _normalise(text: str) -> str:
    """JSON text (one document, or one per line) with the blanked fields; else the text."""
    try:
        docs = [json.loads(text)]
    except ValueError:
        try:
            docs = [json.loads(line) for line in text.splitlines() if line.strip()]
        except ValueError:
            return text
    return json.dumps([_blank(d) for d in docs])


def _env(seed: str) -> dict[str, str]:
    """One hash seed, and the package under test: the `src` folder, as tests/conftest.py does."""
    return {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": SRC}


def _run(args: list[str], seed: str) -> subprocess.CompletedProcess:
    env = _env(seed)
    return subprocess.run(
        [sys.executable, "-m", "logler.cli", *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


@pytest.fixture(scope="module")
def outputs(logs):
    """Every command run under every seed, in parallel, once."""
    commands = _commands(logs)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            (name, seed): pool.submit(_run, args, seed)
            for name, args in commands.items()
            for seed in SEEDS
        }
        return {key: f.result() for key, f in futures.items()}


@pytest.mark.parametrize("name", list(_commands([])))
def test_the_same_files_give_the_same_output_in_every_process(name, outputs):
    results = [outputs[(name, seed)] for seed in SEEDS]
    for r in results:
        assert r.returncode == 0, f"{name} exited {r.returncode}: {r.stderr[-300:]}"
        assert r.stdout.strip(), f"{name} printed nothing"
    texts = [_normalise(r.stdout) for r in results]
    assert texts[0] == texts[1] == texts[2], f"{name} differs between processes"


def _run_lib(case: str, lib_logs: dict[str, str], seed: str) -> subprocess.CompletedProcess:
    env = _env(seed)
    args = [case, *(lib_logs[k] for k in ("threads", "periods", "chain", "request"))]
    return subprocess.run(
        [sys.executable, "-c", LIB_SCRIPT, *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


@pytest.fixture(scope="module")
def lib_outputs(lib_logs):
    """Every library call run under every seed, in parallel, once."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            (case, seed): pool.submit(_run_lib, case, lib_logs, seed)
            for case in LIB_CASES
            for seed in SEEDS
        }
        return {key: f.result() for key, f in futures.items()}


@pytest.mark.parametrize("case", LIB_CASES)
def test_a_library_call_returns_the_same_result_in_every_process(case, lib_outputs):
    results = [lib_outputs[(case, seed)] for seed in SEEDS]
    for r in results:
        assert r.returncode == 0, f"{case} exited {r.returncode}: {r.stderr[-300:]}"
        assert r.stdout.strip(), f"{case} printed nothing"
    texts = [_normalise(r.stdout) for r in results]
    assert texts[0] == texts[1] == texts[2], f"{case} differs between processes"


def test_roots_with_one_trace_id_and_one_timestamp_keep_the_order_of_the_lines(lib_logs):
    """Regression pin: the Rust side sorts siblings by line (hierarchy.rs, sort_siblings)."""
    args = [*PIN_COMMAND, "-f", lib_logs["pin"]]
    runs = [_run(args, seed) for seed in SEEDS]
    for r in runs:
        assert r.returncode == 0, r.stderr[-300:]
    for r in runs:
        names = [n["name"] for n in json.loads(r.stdout)["roots"]]
        assert names == ["pin e", "pin d", "pin c", "pin b", "pin a"]
