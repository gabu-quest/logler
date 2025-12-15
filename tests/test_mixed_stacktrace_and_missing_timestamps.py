from __future__ import annotations

from pathlib import Path


def test_multiline_and_missing_timestamps(investigate_module, tmp_path):
    # Combine stack trace, missing timestamps, and syslog in one file
    path = tmp_path / "weird_mix.log"
    lines = [
        "2024-01-01 00:00:00 ERROR main failed to start",
        "Traceback (most recent call last):",
        "  File \"app.py\", line 10, in <module>",
        "  File \"service.py\", line 5, in run",
        "RuntimeError: boom",
        "level=info msg=\"logfmt without ts\"",
        "<5>missing-ts-host app: still logs",
        "just text with WARN and thread=bg",
    ]
    path.write_text("\n".join(lines))

    inv = investigate_module.Investigator()
    inv.load_files([str(path)], parser_format=None)
    results = inv.search(limit=None)
    entries = [item["entry"] for item in results["results"]]

    assert len(entries) == len(lines)
    # Syslog priority 5 should map to INFO/WARN-ish
    syslog_entry = next(e for e in entries if e["raw"].startswith("<5>"))
    assert syslog_entry["level"] in ("INFO", "WARN")
    # Logfmt entry with no ts should still parse format
    assert any(e.get("format") == "Logfmt" for e in entries)
