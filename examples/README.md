# Logler Examples

Interactive marimo notebook tours for learning logler's LLM-optimized log investigation.

## Structure

```
examples/
├── tours/              # Interactive marimo notebook tours (14 tours)
│   ├── tour_01_fundamentals.py
│   ├── tour_02_thread_tracking.py
│   ├── tour_03_hierarchy.py
│   ├── tour_04_investigation.py
│   ├── tour_05_patterns.py
│   ├── tour_06_flamegraph.py
│   ├── tour_07_error_flow.py
│   ├── tour_08_comparison.py
│   ├── tour_09_tracing_exports.py
│   ├── tour_10_sampling.py
│   ├── tour_11_ai_insights.py
│   ├── tour_12_multi_file_interleaving.py
│   ├── tour_13_live_watching.py
│   └── tour_14_performance.py
└── logs/               # Sample log files for tours
```

## Quick Start

```bash
# Install marimo
uv add --dev marimo

# Run any tour in your browser
uv run marimo edit examples/tours/tour_01_fundamentals.py
```

## Tour Overview

| Tour | Topic | What You'll Learn |
|------|-------|-------------------|
| 01 | Fundamentals | Search, filter, output formats (full/summary/count) |
| 02 | Thread Tracking | Thread grouping, correlation IDs, follow_thread |
| 03 | Hierarchy | Tree visualization, waterfall views, bottleneck detection |
| 04 | Investigation | Sessions, history tracking, report generation |
| 05 | Patterns | Pattern detection, min_occurrences, anomaly finding |
| 06 | Flamegraph | Performance visualization, time distribution |
| 07 | Error Flow | Root cause analysis, error propagation chains |
| 08 | Comparison | Diff hierarchies, compare threads/time periods |
| 09 | Tracing Exports | Export to Jaeger and Zipkin formats |
| 10 | Sampling | Smart sampling strategies (diverse, errors-focused, etc.) |
| 11 | AI Insights | analyze_with_insights, explain, suggest_next_action |
| 12 | Multi-File | Load 5+ services, cross-service timeline, distributed tracing |
| 13 | Live Watching | Real-time tailing, anomaly detection, streaming |
| 14 | Performance | 10K+ entries, benchmarks, token efficiency comparison |

Each tour is self-contained with sample data - no external files needed.

## Learning Path

### Beginners
1. Start with `tour_01_fundamentals.py`
2. Work through tours 02-05 for core concepts
3. Try tour 11 for AI-powered insights

### Advanced Users
- Tours 12-14 showcase logler's full power
- Tour 12: Multi-service distributed tracing
- Tour 13: Real-time log streaming
- Tour 14: Performance at scale (10K+ entries)

## Documentation

- [LLM CLI Reference](../docs/LLM_CLI_REFERENCE.md) - CLI commands for AI agents
- [Python API Guide](../docs/LLM_README.md) - Library API
- [日本語ガイド](../README.ja.md) - Japanese documentation
