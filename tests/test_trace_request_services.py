"""`trace_request` names the services of the entries of a request, in JSON and in logfmt."""

import json

import pytest

from logler.helpers import trace_request
from logler.investigate import RUST_AVAILABLE

pytestmark = pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust backend required")


def _json_line(j, **extra):
    return json.dumps(
        {
            "timestamp": f"2026-11-14T10:01:0{j}Z",
            "level": "INFO",
            "message": f"step{j}",
            "correlation_id": "req-1",
            **extra,
        }
    )


def test_json_log_lists_the_services_of_its_entries(tmp_path):
    path = tmp_path / "req.jsonl"
    path.write_text(
        "\n".join(
            [
                _json_line(0, service="gateway"),
                _json_line(1, service="billing"),
                _json_line(2, service="billing"),
                _json_line(3),
            ]
        )
        + "\n"
    )
    result = trace_request([str(path)], "req-1")
    assert result["total_entries"] == 4
    assert result["services"] == ["billing", "gateway"]


def test_json_log_with_no_service_has_none(tmp_path):
    path = tmp_path / "req.jsonl"
    path.write_text(_json_line(0) + "\n")
    assert trace_request([str(path)], "req-1")["services"] == []


def test_logfmt_keeps_working(tmp_path):
    path = tmp_path / "req.log"
    path.write_text(
        "".join(
            f"ts=2026-11-14T10:01:0{j}Z level=INFO msg=step{j} correlation_id=req-1 service={name}\n"
            for j, name in enumerate(["gateway", "billing"])
        )
    )
    assert trace_request([str(path)], "req-1")["services"] == ["billing", "gateway"]
