# Logler Examples

Comprehensive examples demonstrating logler's LLM-optimized investigation capabilities.

## 📂 Structure

```
examples/
├── en/              # English examples
│   ├── 01_production_incident_investigation.py
│   ├── 02_advanced_sql_analysis.py
│   ├── 03_distributed_tracing.py
│   ├── 04_memory_leak_detection.py
│   ├── 05_cross_service_investigation.py
│   ├── 06_token_efficient_investigation.py      # NEW!
│   ├── 07_auto_insights_analysis.py             # NEW!
│   ├── 08_investigation_sessions.py             # NEW!
│   ├── 09_smart_sampling.py                     # NEW!
│   ├── 10_comparison_and_diff.py                # NEW!
│   ├── 11_explain_errors.py                     # NEW!
│   └── 12_complete_workflow.py                  # NEW!
├── en/live_log_stream.py      # NEW! Live log generator for frontend tailing
├── frontend_walkthrough.md    # NEW! Browser-based UI tour (no code to run)
├── frontend_live_walkthrough.md # NEW! Live follow/tail UI tour (no code to run)
├── ja/              # Japanese examples (日本語)
│   └── 01_本番環境インシデント調査.py
└── logs/            # Sample log files
    ├── production_incident.log
    ├── microservices_trace.log
    └── memory_leak.log
```

## 🚀 Quick Start - Run This First!

```bash
# Complete workflow combining all features
python examples/en/12_complete_workflow.py
```

## 🎯 Examples by Category

### 💡 LLM-Optimized Features (NEW!)

**Start here if you're an LLM agent!**

- **06_token_efficient_investigation.py** - Minimize token usage (44x savings!)
  - Full vs summary vs count vs compact output modes
  - Progressive investigation strategy
  - Essential for limited context windows

- **07_auto_insights_analysis.py** - One-line auto investigation
  - `analyze_with_insights()` does the thinking for you
  - Automatic pattern detection and suggestions
  - Severity-rated insights with evidence

- **08_investigation_sessions.py** - Track and manage investigations
  - History tracking with undo/redo
  - Save and resume investigations
  - Auto-generate professional reports (Markdown/Text/JSON)

- **09_smart_sampling.py** - Intelligent sampling strategies
  - Representative, diverse, errors-focused, chronological
  - Coverage metrics and validation
  - Perfect for huge log files

- **10_comparison_and_diff.py** - Compare and find differences
  - Successful vs failed requests
  - Before/after deployment analysis
  - Automatic difference detection with summaries

- **11_explain_errors.py** - Plain English error explanations
  - Covers 6+ common error types
  - Common causes and actionable next steps
  - Production vs development context

- **12_complete_workflow.py** - Complete investigation workflow
  - Combines all LLM features in one example
  - Token-efficient from start to finish
  - Best practices for LLM agents

### 🔍 Core Investigation

- **01_production_incident_investigation.py** - Complete incident workflow
  - Overview and metadata
  - Error detection and pattern finding
  - Thread following and root cause analysis
  - 8-step systematic investigation

### 📊 Advanced Analysis

- **02_advanced_sql_analysis.py** - Deep analysis using SQL
  - Anomaly detection with z-scores
  - Error correlation matrices
  - Performance hotspot detection
  - Cascading failure patterns

### 🌐 Distributed Systems

- **03_distributed_tracing.py** - Microservices investigation
  - Request flow visualization
  - Service latency breakdown
  - Error isolation across services

- **05_cross_service_investigation.py** - Cross-service timeline
  - Unified timeline across multiple services
  - Service-by-service breakdown
  - Distributed debugging

### 🧠 Performance & Memory

- **04_memory_leak_detection.py** - Memory leak analysis
  - Memory growth visualization
  - GC effectiveness analysis
  - OOM prediction and recommendations

## 📚 Learning Path

### For Beginners
1. Start with `12_complete_workflow.py` to see all features
2. Try `06_token_efficient_investigation.py` for optimization
3. Explore `07_auto_insights_analysis.py` for automatic analysis

### For Incident Investigation
1. `01_production_incident_investigation.py` - Systematic approach
2. `11_explain_errors.py` - Understand cryptic errors
3. `08_investigation_sessions.py` - Track your work
4. Generate report and share findings

### For Advanced Analysis
1. `09_smart_sampling.py` - Work with large datasets
2. `10_comparison_and_diff.py` - Find root causes
3. `02_advanced_sql_analysis.py` - Statistical analysis
4. `03_distributed_tracing.py` - Microservices debugging

## 🎮 Running Examples

```bash
# All examples can be run directly
python examples/en/06_token_efficient_investigation.py
python examples/en/07_auto_insights_analysis.py
python examples/en/08_investigation_sessions.py
# ... etc

# Japanese examples
python examples/ja/01_本番環境インシデント調査.py

# Browser walkthrough (no Python execution)
# Open the UI and click through the steps:
#   see examples/frontend_walkthrough.md
#   see examples/frontend_live_walkthrough.md

# Live tail demo (generates logs you can follow in the UI)
uv run python examples/en/live_log_stream.py
uv run logler serve --auto-port examples/logs/live_follow_demo.log
```

## 💾 Sample Log Files

All examples use realistic production log files:

- **production_incident.log** (42 lines)
  - Database connection pool exhaustion
  - Cascading failures
  - Error patterns and recovery

- **microservices_trace.log** (150 lines)
  - Distributed trace across 4 services
  - Request flow: API Gateway → User → Order → Inventory
  - Service failure and degraded mode

- **memory_leak.log** (32 lines)
  - Gradual memory leak over 1.77 hours
  - Memory growth from 150MB to 598MB
  - GC degradation and OOM crash

## 🤖 For LLM Agents

These examples are specifically designed for AI agents with:

- **Token efficiency** - Minimize context usage at every step
- **Automatic insights** - Let logler do the analysis
- **Progressive investigation** - Start broad, drill down as needed
- **Session management** - Track and resume investigations
- **Professional reports** - Auto-generate documentation

### Key Features Demonstrated

1. **44x Token Savings** - Use summary/count modes instead of full output
2. **Auto Analysis** - `analyze_with_insights()` does the thinking
3. **Smart Sampling** - Representative samples of huge files
4. **Comparisons** - Find differences between requests/periods
5. **Explanations** - Plain English for cryptic errors
6. **Sessions** - Track multi-step investigations with undo/redo
7. **Reports** - Auto-generate professional investigation reports

## 📖 Additional Documentation

- [LLM Investigation API](../docs/LLM_INVESTIGATION_API.md) - Complete API reference
- [LLM README](../docs/LLM_README.md) - Quick start guide
- [Performance Guide](../docs/PERFORMANCE.md) - Optimization strategies
- [Japanese README](../README.ja.md) - 日本語ドキュメント

## 🆘 Need Help?

Each example includes:
- Clear scenario description
- Step-by-step walkthrough
- Expected output
- Key takeaways

Start with `12_complete_workflow.py` to see everything in action!
