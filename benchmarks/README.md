# Benchmarks

```bash
uv pip install "matplotlib>=3.8"                      # for the charts
uv run python -m benchmarks run --scale small         # Run all 19 scenarios
uv run python -m benchmarks list                      # List available scenarios
uv run python -m benchmarks plot -i results/latest.json  # Generate charts
uv run python -m benchmarks compare -b v1.json -c v2.json -o results/v2  # Before/after comparison
```

- 19 scenarios across 7 suites (search, hierarchy, correlation, output, sampling, memory, db_source)
- Scales: small (1K/10K/50K), medium (10K/50K/100K), large (50K/100K/500K)
- Memory scenarios use fixed scales (10K/50K/100K) ignoring config.scale for cross-run comparability
- Deterministic data generation (seeded RNG), precision timing (warmup + percentiles)
- Output goes to `benchmarks/results/` (git-ignored); the published report is `docs/benchmarks/REPORT.md`
- Comparison report generator produces scientific before/after analysis with confidence levels

## Memory Measurement Rules

**NEVER use `ru_maxrss` for memory benchmarks.** `resource.getrusage(RUSAGE_SELF).ru_maxrss` is the
peak RSS for the entire process lifetime — once the high-water mark is set (by pytest imports,
Rust bindings, etc.), subsequent operations that stay below it report 0 KB "allocated." This
produces meaningless results that look like proof but prove nothing.

**Use `tracemalloc` for Python allocations, VmRSS for total process memory.** Always report both
for operations involving native code (Rust/C).

`tracemalloc` tracks actual Python heap allocations during the measured call:
```python
import tracemalloc
tracemalloc.start()
# ... measured work ...
current, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()
```
This gives real numbers: "list version peaked at 45 MB, generator peaked at 2 MB."

VmRSS from `/proc/self/status` tracks total process resident memory including Rust/C:
```python
def _get_vmrss_kb() -> int:
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    return 0
```
Read VmRSS before and after the measured call; the delta shows total memory growth
including allocations invisible to tracemalloc (e.g., Rust `PyInvestigator` index).
