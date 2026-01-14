from __future__ import annotations


def test_mixed_formats_parse_levels_and_formats(investigate_module, tmp_path):
    inv = investigate_module.Investigator()
    mixed = tmp_path / "mixed.log"
    lines = [
        '{"timestamp":"2024-01-01T00:00:00Z","level":"INFO","message":"json ok","service":"api"}',
        "<3>2024-01-01T00:00:01Z host app: syslog panic",
        'level=warn ts="2024-01-01T00:00:02Z" msg="logfmt line" trace_id=abcd1234',
        "no-ts WARN thread=weird message only",
        'badjson{"level":"info"',
    ]
    mixed.write_text("\n".join(lines))

    inv.load_files([str(mixed)])
    results = inv.search(limit=None)
    entries = [item["entry"] for item in results["results"]]

    assert len(entries) == len(lines)
    syslog_entry = next(e for e in entries if e.get("raw", "").startswith("<3>"))
    assert syslog_entry.get("level") == "ERROR"  # syslog <3> -> ERROR
    assert any(e.get("format") == "Logfmt" for e in entries)
    assert any(e.get("format") == "Syslog" for e in entries)


def test_custom_regex_parses_weird_lines(investigate_module, tmp_path):
    inv = investigate_module.Investigator()
    target = tmp_path / "weird.log"
    target.write_text("02-02-2024 10:00:00|ERROR|payment failed")

    regex = (
        r"(?P<timestamp>\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2})\|(?P<level>[A-Z]+)\|(?P<message>.+)"
    )
    inv.load_files([str(target)], custom_regex=regex)

    results = inv.search(query="payment", limit=None)
    assert results["total_matches"] == 1
    entry = results["results"][0]["entry"]
    assert entry.get("format") == "Custom"
    assert entry["level"] == "ERROR"
    assert entry.get("timestamp")
    assert entry["message"].endswith("payment failed")
