# Logler Examples

This directory contains comprehensive examples demonstrating how to use Logler for log investigation, with a focus on LLM agent workflows.

## 📁 Directory Structure

```
examples/
├── en/                          # English examples
│   ├── 01_production_incident_investigation.py
│   └── 02_advanced_sql_analysis.py
├── ja/                          # Japanese examples (日本語の例)
│   └── 01_本番環境インシデント調査.py
├── logs/                        # Sample log files
│   └── production_incident.log
└── README.md                    # This file
```

## 🎯 Examples Overview

### 01: Production Incident Investigation

**Scenario**: Database connection pool exhaustion causing cascading failures

**Skills demonstrated**:
- Using `search()` to find error patterns
- Using `follow_thread()` to reconstruct request timelines
- Using `find_patterns()` to detect cascading failures
- Using SQL for time-series analysis
- Identifying root cause and measuring impact

**Run**:
```bash
python examples/en/01_production_incident_investigation.py
```

### 02: Advanced SQL Analysis

**Scenario**: Deep-dive analysis using custom SQL queries

**Skills demonstrated**:
- Statistical anomaly detection with Z-scores
- Error correlation matrix  
- Thread hotspot detection
- Cascading failure pattern recognition

**Run**:
```bash
python examples/en/02_advanced_sql_analysis.py
```

## 🚀 Quick Start

```bash
# Run English example
python examples/en/01_production_incident_investigation.py

# Run Japanese example
python examples/ja/01_本番環境インシデント調査.py
```

## 💡 For LLM Agents

These examples show how to investigate production incidents efficiently using logler's Rust-powered tools.

See [../docs/LLM_README.md](../docs/LLM_README.md) for complete documentation.
