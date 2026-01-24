# Logler Field Guide: Example-Driven Survival Manual

So you’ve found yourself staring at a mess of logs. Let’s dive into the examples and learn Logler by doing. Each script is runnable; most work with the bundled sample logs under `examples/logs`.

## How to run

```bash
source .venv/bin/activate  # or your env
python examples/en/<number>_<name>.py
```

## What to reach for (cheat sheet)

- Need a quick terminal viewer? `logler view`.
- Want a web UI? Use [logler-web](https://github.com/gabu-quest/logler-web).
- Need LLM-speed queries? Use `logler.investigate` (Rust backend).
- Token budget hurting? Use summary/count/compact outputs.
- Want SQL over logs? Build with `--features sql` and use `Investigator.sql_query()`.

## Example tour (serious help, slightly wry)

### 01_production_incident_investigation.py
“Everything is on fire” starter kit: search errors, find patterns, follow a failed request, run SQL timelines, and locate resolution lines. Uses `examples/logs/production_incident.log`.

### 02_advanced_sql_analysis.py
DuckDB-powered deep dive: anomaly detection, error correlations, latency stats, hotspot threads, cascading failures, recovery timing. Great when you want math, not vibes.

### 03_distributed_tracing.py
Cross-service trace walkthrough: follows correlation/trace IDs, builds a call flow, and highlights failure propagation across services.

### 04_memory_leak_detection.py
Targets runaway memory usage patterns; shows how to surface gradual drifts and repeated leak signatures.

### 05_cross_service_investigation.py
Multi-service timeline builder; good for “which service sneezed first?” questions across separate logs.

### 06_token_efficient_investigation.py
LLM rationing: compares full vs summary vs count vs compact outputs. Use this before you torch your context window.

### 07_auto_insights_analysis.py
One-liner `analyze_with_insights()` that spits out patterns and suggestions. Perfect for “tell me what matters” moments.

### 08_investigation_sessions.py
Stateful investigations with undo/redo and note-taking. Use when you need to keep a trail instead of scribbling in a scratch buffer.

### 09_smart_sampling.py
Representative/diverse/errors-focused/chronological sampling to shrink huge logs while keeping useful coverage.

### 10_comparison_and_diff.py
Before/after and success/failure diffing. Ideal for “did the deployment break it?” or “why did this request explode?”.

### 11_explain_errors.py
Plain-English explanations with next steps for common error tropes plus live examples from the sample logs.

### 12_complete_workflow.py
End-to-end investigation script: metadata → search → patterns → timelines → SQL → summary. Good template for your own flow.

### 13_chaos_resilience_lab.py
Diabolical scenario: failed vs happy vs flaky payments with circuit breakers, retries, and SQL dashboards. Shows comparisons, timelines, and service impact counts. Uses `examples/logs/chaos_fest.log`.

## Library highlights to reuse

- `investigate.search(..., output_format="summary|count|compact")` for token-thrifty queries.
- `investigate.find_patterns()` to surface repeated errors automatically.
- `investigate.follow_thread(... correlation_id=...)` for timelines.
- `investigate.compare_threads()` and `compare_time_periods()` for diffs.
- `Investigator.sql_query()` for ad-hoc analytics (build with `--features sql`).
- `investigate.smart_sample()` to downsample responsibly.
- `investigate.analyze_with_insights()` when you want auto-prioritized findings.

## Pro tips

- Keep `LOGLER_ROOT` set when serving to avoid wandering the filesystem.
- For Rust speed + SQL, rebuild with `maturin develop --features sql`.
- Start with summary/count, then drill into full logs only where it hurts.
- Save your sanity: use the examples as copy/paste templates and tweak the file paths/IDs.
