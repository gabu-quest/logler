import marimo

__generated_with = "0.18.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(
        r"""
    # Logler Tour: Format Detection & Template Mining

    When you encounter an unfamiliar log file, logler can automatically
    detect its format and mine recurring templates using the Drain algorithm.

    **What you'll learn:**
    1. Auto-detecting log formats (JSON, syslog, CLF, logfmt)
    2. Confidence scoring and alternatives
    3. Drain template mining for pattern discovery
    4. Template clustering and variable extraction
    """
    )
    return


@app.cell
def _():
    import json
    import tempfile
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    temp_dir = tempfile.mkdtemp()
    return Path, datetime, json, temp_dir, tempfile, timedelta, timezone


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 1. Format Detection

    Create sample files in different formats and detect them:
    """
    )
    return


@app.cell
def _(Path, datetime, json, temp_dir, timedelta, timezone):
    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

    # JSON log file
    json_file = Path(temp_dir) / "app.jsonl"
    with open(json_file, "w") as _f:
        for _i in range(30):
            _f.write(
                json.dumps(
                    {
                        "timestamp": (base_time + timedelta(seconds=_i)).isoformat(),
                        "level": "INFO" if _i % 5 != 0 else "ERROR",
                        "message": f"Processing request {_i}",
                        "service": "api-gateway",
                    }
                )
                + "\n"
            )

    # Syslog file
    syslog_file = Path(temp_dir) / "system.log"
    with open(syslog_file, "w") as _f:
        for _i in range(30):
            _f.write(
                f"Jan 15 10:{_i // 60:02d}:{_i % 60:02d} web-prod-01 "
                f"nginx[{1000+_i}]: GET /api/endpoint-{_i} 200\n"
            )

    # Logfmt file
    logfmt_file = Path(temp_dir) / "metrics.log"
    with open(logfmt_file, "w") as _f:
        for _i in range(30):
            _f.write(
                f'level=info msg="request handled" method=GET '
                f"path=/api/v{_i % 3 + 1} status=200 duration={50 + _i * 3}ms\n"
            )

    print("Created 3 sample log files:")
    print(f"  - {json_file.name}: JSON format (30 lines)")
    print(f"  - {syslog_file.name}: Syslog format (30 lines)")
    print(f"  - {logfmt_file.name}: Logfmt format (30 lines)")
    return json_file, logfmt_file, syslog_file


@app.cell
def _(json_file, logfmt_file, syslog_file):
    from logler.format_detector import detect_format

    files = {
        "app.jsonl": str(json_file),
        "system.log": str(syslog_file),
        "metrics.log": str(logfmt_file),
    }

    print("=== Format Detection ===\n")
    for name, path in files.items():
        _result = detect_format(path)
        print(f"--- {name} ---")
        print(f"  Format: {_result.format}")
        print(f"  Confidence: {_result.confidence:.1%}")
        print(f"  Match rate: {_result.match_rate:.1%}")
        print(f"  Sample size: {_result.sample_size}")
        if _result.detected_fields:
            print(f"  Fields: {', '.join(_result.detected_fields[:5])}")
        print()
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 2. Confidence Analysis

    When detection is uncertain, alternatives show other possible formats:
    """
    )
    return


@app.cell
def _(Path, temp_dir):
    from logler.format_detector import detect_format as _detect_format

    # Create a mixed file for ambiguous detection
    mixed_file = Path(temp_dir) / "mixed.log"
    with open(mixed_file, "w") as _f:
        for _i in range(15):
            _f.write(f'{{"ts": "2024-01-15T10:00:{_i:02d}Z", "msg": "json line {_i}"}}\n')
        for _i in range(15):
            _f.write(f"Jan 15 10:01:{_i:02d} server app[{_i}]: syslog line {_i}\n")

    _result = _detect_format(str(mixed_file))

    print("=== Confidence Analysis ===\n")
    print(f"Primary format: {_result.format} (confidence: {_result.confidence:.1%})")
    print(f"Mixed content: {_result.mixed}")
    print("\nAlternatives:")
    for alt in _result.alternatives:
        print(
            f"  {alt['format']}: confidence={alt['confidence']:.1%}, match_rate={alt['match_rate']:.1%}"
        )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 3. Template Mining

    The Drain algorithm discovers recurring log templates by
    clustering similar messages and extracting variable positions:
    """
    )
    return


@app.cell
def _():
    from logler.format_detector import mine_templates

    # Create messages with known templates
    messages = (
        [f"User user_{_i} logged in from 192.168.1.{_i}" for _i in range(40)]
        + [f"Request to /api/endpoint_{_i} took {100 + _i}ms" for _i in range(35)]
        + [f"Database query SELECT * FROM table_{_i} returned {_i * 10} rows" for _i in range(25)]
    )

    mining_result = mine_templates(messages, max_clusters=100)

    print("=== Template Mining ===\n")
    print(f"Total messages: {mining_result.total_lines}")
    print(f"Unique templates: {mining_result.unique_templates}")
    print(f"Coverage: {mining_result.coverage:.1%}")
    return (mining_result,)


@app.cell
def _(mining_result):
    print("=== Template Clusters ===\n")

    for _i, template in enumerate(mining_result.templates, 1):
        print(f"Template #{_i}:")
        print(f"  Pattern: {template['template']}")
        print(f"  Count: {template['count']} ({template['percentage']:.1f}%)")
        print(f"  Variables: {len(template['variable_positions'])} positions")
        if template["examples"]:
            print(f"  Example: {template['examples'][0][:70]}")
        print()
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## Summary

    You've learned logler's auto-detection capabilities:

    - **`detect_format()`** — Classify log format with confidence scores
    - **Alternatives** — See what other formats were considered
    - **Mixed detection** — Identify files with multiple formats
    - **`mine_templates()`** — Drain algorithm for template discovery
    - **Variable extraction** — `<*>` marks dynamic positions in templates

    **Use cases:**
    - Automatically configure parsers for unknown log files
    - Discover recurring patterns without manual regex writing
    - Quantify log message diversity (unique templates vs total messages)
    - Identify the most common log patterns for monitoring rules

    **Previous tours:**
    - **Tour 16**: Numeric extraction and metrics
    - **Tour 15**: Advanced filtering
    """
    )
    return


@app.cell
def _(temp_dir):
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)
    print("Cleaned up temp files")
    return


if __name__ == "__main__":
    app.run()
