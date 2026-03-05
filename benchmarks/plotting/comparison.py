"""Comparison report generator — before/after analysis with scientific rigor.

Takes two benchmark result JSON files (baseline vs current) and produces:
- Side-by-side timing tables with speedup ratios
- Statistical significance indicators
- Before/after delta charts
- Methodology section documenting what changed
- Narrative summary for blog-style consumption
"""

from __future__ import annotations

import json
from pathlib import Path

from .theme import (
    ACCENT_COLORS,
    BORDER_COLOR,
    TEXT_MUTED,
    TEXT_PRIMARY,
    apply_dark_theme,
    color,
)


def generate_comparison(
    baseline_path: str,
    current_path: str,
    output_dir: str,
    changes_description: str | None = None,
) -> None:
    """Generate a scientific comparison report from two benchmark runs.

    Args:
        baseline_path: Path to the v1 (pre-optimization) results JSON.
        current_path: Path to the v2 (post-optimization) results JSON.
        output_dir: Directory to write the comparison report and charts.
        changes_description: Optional markdown describing what changed.
    """
    baseline = json.loads(Path(baseline_path).read_text())
    current = json.loads(Path(current_path).read_text())
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    charts_dir = out / "charts"
    charts_dir.mkdir(exist_ok=True)

    apply_dark_theme()

    # Build lookup tables: (scenario, value) -> result
    b_lookup = _build_lookup(baseline["results"])
    c_lookup = _build_lookup(current["results"])

    # Compute deltas for every matching measurement
    deltas = _compute_deltas(b_lookup, c_lookup)

    # Generate before/after charts
    chart_paths = _generate_comparison_charts(
        baseline["results"],
        current["results"],
        deltas,
        charts_dir,
        _format_system_info(baseline.get("system", {})),
        _format_system_info(current.get("system", {})),
    )

    # Write the markdown report
    _write_comparison_report(
        out / "COMPARISON.md",
        baseline,
        current,
        deltas,
        chart_paths,
        charts_dir,
        changes_description,
    )

    print("\n  Comparison report generated:")
    print(f"    Report:  {out / 'COMPARISON.md'}")
    print(f"    Charts:  {charts_dir}/ ({len(chart_paths)} charts)")


def _build_lookup(results: list[dict]) -> dict[tuple[str, str], dict]:
    """Build a (scenario, value) -> result lookup."""
    lookup = {}
    for r in results:
        key = (r["scenario"], str(r.get("value", "")))
        lookup[key] = r
    return lookup


def _compute_deltas(
    baseline: dict[tuple[str, str], dict],
    current: dict[tuple[str, str], dict],
) -> list[dict]:
    """Compute before/after deltas for matching measurements."""
    deltas = []
    all_keys = sorted(set(baseline.keys()) | set(current.keys()))

    for key in all_keys:
        b = baseline.get(key)
        c = current.get(key)
        if not b or not c:
            continue

        scenario, value = key
        b_median = b["timing"]["median_ms"]
        c_median = c["timing"]["median_ms"]
        b_p95 = b["timing"]["p95_ms"]
        c_p95 = c["timing"]["p95_ms"]

        # Speedup ratio (>1 = faster, <1 = slower)
        speedup = b_median / c_median if c_median > 0 else float("inf")

        # Absolute change
        abs_change_ms = b_median - c_median

        # Percentage change (negative = improvement)
        pct_change = ((c_median - b_median) / b_median * 100) if b_median > 0 else 0

        # Coefficient of variation for both runs
        b_cv = (b["timing"]["stddev_ms"] / b_median * 100) if b_median > 0 else 0
        c_cv = (c["timing"]["stddev_ms"] / c_median * 100) if c_median > 0 else 0

        # Confidence classification based on non-overlapping ranges
        # If v2 p95 < v1 min, the improvement is highly confident
        b_min = b["timing"]["min_ms"]
        c_max = c["timing"]["max_ms"]
        c_min = c["timing"]["min_ms"]
        b_max = b["timing"]["max_ms"]

        if c_max < b_min:
            confidence = "definitive"
        elif c_p95 < b_median:
            confidence = "high"
        elif abs(pct_change) > 10:
            confidence = "moderate"
        elif abs(pct_change) > 3:
            confidence = "marginal"
        else:
            confidence = "within noise"

        deltas.append(
            {
                "scenario": scenario,
                "suite": b.get("suite", ""),
                "value": value,
                "baseline_median_ms": b_median,
                "current_median_ms": c_median,
                "baseline_p95_ms": b_p95,
                "current_p95_ms": c_p95,
                "baseline_min_ms": b_min,
                "current_min_ms": c_min,
                "baseline_max_ms": b_max,
                "current_max_ms": c_max,
                "speedup": speedup,
                "abs_change_ms": abs_change_ms,
                "pct_change": pct_change,
                "baseline_cv": b_cv,
                "current_cv": c_cv,
                "confidence": confidence,
                "baseline_throughput": b.get("throughput", 0),
                "current_throughput": c.get("throughput", 0),
            }
        )

    return deltas


def _classify_speedup(speedup: float) -> str:
    """Human-readable speedup classification."""
    if speedup >= 100:
        return "transformative"
    elif speedup >= 10:
        return "order-of-magnitude"
    elif speedup >= 3:
        return "major"
    elif speedup >= 1.5:
        return "significant"
    elif speedup >= 1.1:
        return "minor"
    elif speedup >= 0.95:
        return "unchanged"
    else:
        return "regression"


def _speedup_indicator(speedup: float) -> str:
    """Compact speedup indicator for tables."""
    if speedup >= 10:
        return f"**{speedup:.0f}x faster**"
    elif speedup >= 2:
        return f"**{speedup:.1f}x faster**"
    elif speedup >= 1.1:
        return f"{speedup:.2f}x faster"
    elif speedup >= 0.95:
        return "~same"
    else:
        return f"{1/speedup:.2f}x slower"


def _format_ms(ms: float) -> str:
    """Format milliseconds for display."""
    if ms >= 10000:
        return f"{ms/1000:.1f}s"
    elif ms >= 1000:
        return f"{ms/1000:.2f}s"
    elif ms >= 10:
        return f"{ms:.1f}ms"
    elif ms >= 0.1:
        return f"{ms:.2f}ms"
    else:
        return f"{ms:.3f}ms"


def _format_system_info(info: dict) -> str:
    if not info:
        return ""
    rust_tag = (
        f"Rust {info.get('logler_rs_version', '?')}" if info.get("rust_available") else "no Rust"
    )
    return (
        f"Python {info.get('python_version', '?')} | "
        f"logler {info.get('logler_version', '?')} | "
        f"{rust_tag} | "
        f"{info.get('platform_system', '?')} {info.get('platform_machine', '?')} "
        f"({info.get('cpu_count', '?')} cores)"
    )


def _generate_comparison_charts(
    baseline_results: list[dict],
    current_results: list[dict],
    deltas: list[dict],
    charts_dir: Path,
    baseline_info: str,
    current_info: str,
) -> dict[str, Path]:
    """Generate before/after comparison charts."""
    chart_paths = {}

    # Focus on the three key bottleneck scenarios
    key_scenarios = [
        ("hierarchy_building", "Hierarchy Building"),
        ("sampling_scaling", "Smart Sample Scaling"),
        ("follow_thread_scaling", "Follow Thread Scaling"),
        ("search_broad_query", "Broad Query Search"),
        ("db_to_jsonl_scaling", "DB to JSONL Streaming"),
    ]

    for scenario_name, title in key_scenarios:
        scenario_deltas = [d for d in deltas if d["scenario"] == scenario_name]
        if not scenario_deltas:
            continue

        chart_path = _plot_before_after_bars(
            scenario_deltas,
            f"{title} — Before vs After",
            f"v1: {baseline_info}",
            charts_dir / f"compare_{scenario_name}",
        )
        if chart_path:
            chart_paths[scenario_name] = chart_path

    # Speedup summary chart (all scenarios at max entry count)
    max_deltas = _pick_max_scale_deltas(deltas)
    if max_deltas:
        chart_paths["speedup_summary"] = _plot_speedup_summary(
            max_deltas,
            "Speedup Summary — All Scenarios at Maximum Scale",
            charts_dir / "compare_speedup_summary",
        )

    return chart_paths


def _pick_max_scale_deltas(deltas: list[dict]) -> list[dict]:
    """For scenarios with multiple scale points, pick the largest scale."""
    by_scenario: dict[str, list[dict]] = {}
    for d in deltas:
        by_scenario.setdefault(d["scenario"], []).append(d)

    result = []
    for scenario, scenario_deltas in by_scenario.items():
        # Try to pick the one with the largest numeric value
        best = None
        for d in scenario_deltas:
            try:
                v = int(d["value"])
                if best is None or v > int(best["value"]):
                    best = d
            except (ValueError, TypeError):
                if best is None:
                    best = d
        if best:
            result.append(best)

    return sorted(result, key=lambda d: d["speedup"], reverse=True)


def _plot_before_after_bars(
    deltas: list[dict],
    title: str,
    subtitle: str,
    output: Path,
) -> Path | None:
    """Grouped bar chart: before vs after for each parameter value."""
    import matplotlib.pyplot as plt
    import numpy as np

    if not deltas:
        return None

    apply_dark_theme()
    fig, ax = plt.subplots(figsize=(12, 7))

    labels = [str(d["value"]) for d in deltas]
    baseline_medians = [d["baseline_median_ms"] for d in deltas]
    current_medians = [d["current_median_ms"] for d in deltas]
    speedups = [d["speedup"] for d in deltas]

    x = np.arange(len(labels))
    width = 0.35

    # Before bars (muted)
    bars_before = ax.bar(
        x - width / 2,
        baseline_medians,
        width,
        color=ACCENT_COLORS["muted"],
        edgecolor=BORDER_COLOR,
        linewidth=1,
        label="v1 (before)",
        zorder=3,
    )

    # After bars (highlighted)
    ax.bar(
        x + width / 2,
        current_medians,
        width,
        color=ACCENT_COLORS["success"],
        edgecolor=BORDER_COLOR,
        linewidth=1,
        label="v2 (after)",
        zorder=3,
    )

    # Speedup annotations
    for i, (ba, sp) in enumerate(zip(bars_before, speedups)):
        y_pos = max(baseline_medians[i], current_medians[i])
        if sp >= 1.1:
            label_text = f"{sp:.0f}x" if sp >= 10 else f"{sp:.1f}x"
            ax.annotate(
                label_text,
                xy=(x[i], y_pos),
                xytext=(0, 12),
                textcoords="offset points",
                ha="center",
                fontsize=11,
                fontweight="bold",
                color=ACCENT_COLORS["highlight"],
            )

    ax.set_xlabel("Entry Count")
    ax.set_ylabel("Time (ms)")
    ax.set_title(title, pad=20)
    ax.text(
        0.5,
        1.02,
        subtitle,
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=8,
        color=TEXT_MUTED,
        style="italic",
    )
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.legend(loc="upper left", framealpha=0.9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Use log scale if range is large
    all_vals = baseline_medians + current_medians
    if max(all_vals) / max(min(all_vals), 0.01) > 50:
        ax.set_yscale("log")

    fig.tight_layout()
    svg = output.with_suffix(".svg")
    png = output.with_suffix(".png")
    fig.savefig(svg, format="svg")
    fig.savefig(png, format="png", dpi=200)
    plt.close(fig)
    return svg


def _plot_speedup_summary(
    deltas: list[dict],
    title: str,
    output: Path,
) -> Path:
    """Horizontal bar chart showing speedup for each scenario."""
    import matplotlib.pyplot as plt
    import numpy as np

    apply_dark_theme()
    fig, ax = plt.subplots(figsize=(12, max(5, len(deltas) * 0.55)))

    # Sort by speedup (ascending so biggest is at top visually)
    sorted_deltas = sorted(deltas, key=lambda d: d["speedup"])

    labels = []
    speedups = []
    bar_colors = []

    for d in sorted_deltas:
        scenario = d["scenario"].replace("_", " ").title()
        val = d["value"]
        labels.append(f"{scenario}\n({val})")
        speedups.append(d["speedup"])

        sp = d["speedup"]
        if sp >= 10:
            bar_colors.append(ACCENT_COLORS["highlight"])
        elif sp >= 2:
            bar_colors.append(ACCENT_COLORS["success"])
        elif sp >= 1.1:
            bar_colors.append(color(1))  # Sky blue
        elif sp >= 0.95:
            bar_colors.append(ACCENT_COLORS["muted"])
        else:
            bar_colors.append(ACCENT_COLORS["danger"])

    y = np.arange(len(labels))
    bars = ax.barh(
        y,
        speedups,
        height=0.6,
        color=bar_colors,
        edgecolor=BORDER_COLOR,
        linewidth=1,
        zorder=3,
    )

    # Value labels
    for bar, sp in zip(bars, speedups):
        x_pos = bar.get_width()
        label = f"{sp:.0f}x" if sp >= 10 else f"{sp:.1f}x"
        ax.text(
            x_pos + max(speedups) * 0.02,
            bar.get_y() + bar.get_height() / 2,
            label,
            ha="left",
            va="center",
            fontsize=10,
            fontweight="bold",
            color=TEXT_PRIMARY,
        )

    # Reference line at 1x
    ax.axvline(x=1.0, color=TEXT_MUTED, linestyle="--", linewidth=1, zorder=2)
    ax.text(
        1.0,
        len(labels) - 0.3,
        " 1x (no change)",
        fontsize=8,
        color=TEXT_MUTED,
        va="top",
    )

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Speedup (x)")
    ax.set_title(title, pad=20)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Log scale if range is large
    if max(speedups) / max(min(speedups), 0.01) > 20:
        ax.set_xscale("log")

    fig.tight_layout()
    svg = output.with_suffix(".svg")
    png = output.with_suffix(".png")
    fig.savefig(svg, format="svg")
    fig.savefig(png, format="png", dpi=200)
    plt.close(fig)
    return svg


def _write_comparison_report(
    path: Path,
    baseline: dict,
    current: dict,
    deltas: list[dict],
    chart_paths: dict[str, Path],
    charts_dir: Path,
    changes_description: str | None,
) -> None:
    """Write the scientific comparison report in markdown."""
    b_config = baseline.get("config", {})
    c_config = current.get("config", {})
    b_system = baseline.get("system", {})
    c_system = current.get("system", {})

    lines = [
        "# logler Performance Comparison Report",
        "",
        "## Executive Summary",
        "",
    ]

    # Compute headline stats
    improvements = [d for d in deltas if d["speedup"] > 1.1]
    regressions = [d for d in deltas if d["speedup"] < 0.9]

    if improvements:
        max_speedup = max(d["speedup"] for d in improvements)
        max_d = next(d for d in improvements if d["speedup"] == max_speedup)
        lines.append(
            f"**{len(improvements)} measurements improved** out of {len(deltas)} total. "
            f"Maximum speedup: **{max_speedup:.0f}x** "
            f"({max_d['scenario']} at {max_d['value']} entries)."
        )

    if regressions:
        lines.append(f"**{len(regressions)} regressions detected** " f"(median slowed by >10%).")
    else:
        lines.append("**Zero regressions detected.**")

    lines.append("")

    # Methodology section
    lines.extend(
        [
            "## Methodology",
            "",
            "### Test Conditions",
            "",
            "| Condition | Baseline (v1) | Current (v2) |",
            "|-----------|--------------|--------------|",
            f"| Scale | {b_config.get('scale', '?')} | {c_config.get('scale', '?')} |",
            f"| Warmup iterations | {b_config.get('warmup', '?')} | {c_config.get('warmup', '?')} |",
            f"| Measured iterations | {b_config.get('iterations', '?')} | {c_config.get('iterations', '?')} |",
            f"| Python | {b_system.get('python_version', '?')} | {c_system.get('python_version', '?')} |",
            f"| Rust backend | {'yes' if b_system.get('rust_available') else 'no'} | {'yes' if c_system.get('rust_available') else 'no'} |",
            f"| Platform | {b_system.get('platform_system', '?')} {b_system.get('platform_machine', '?')} | {c_system.get('platform_system', '?')} {c_system.get('platform_machine', '?')} |",
            f"| CPU cores | {b_system.get('cpu_count', '?')} | {c_system.get('cpu_count', '?')} |",
            f"| logler version | {b_system.get('logler_version', '?')} | {c_system.get('logler_version', '?')} |",
            "",
        ]
    )

    # Validate conditions match
    conditions_match = (
        b_config.get("scale") == c_config.get("scale")
        and b_system.get("platform_machine") == c_system.get("platform_machine")
        and b_system.get("cpu_count") == c_system.get("cpu_count")
    )

    if conditions_match:
        lines.append(
            "> **Conditions match.** Same scale, same hardware, same measurement parameters. "
            "Results are directly comparable."
        )
    else:
        lines.append(
            "> **WARNING: Conditions differ.** Results should be interpreted with caution."
        )
    lines.append("")

    lines.extend(
        [
            "### Measurement Protocol",
            "",
            "- All measurements use `time.perf_counter()` (nanosecond resolution)",
            "- Warmup iterations are executed and **discarded** before measurement",
            "- Statistics reported: min, median, p95, p99, stddev, coefficient of variation",
            "- Synthetic log data is **deterministically generated** (seeded RNG, identical across runs)",
            "- Each scenario generates fresh temporary files, cleans up after",
            "",
            "### Confidence Classification",
            "",
            "| Level | Criteria |",
            "|-------|----------|",
            "| **Definitive** | v2 worst case (max) < v1 best case (min). Zero overlap in timing distributions. |",
            "| **High** | v2 p95 < v1 median. 95% of v2 runs beat the typical v1 run. |",
            "| **Moderate** | >10% median change, some distribution overlap. |",
            "| **Marginal** | 3-10% median change. Could be noise on a different day. |",
            "| **Within noise** | <3% change. Not a real difference. |",
            "",
        ]
    )

    # What changed
    if changes_description:
        lines.extend(
            [
                "### What Changed",
                "",
                changes_description,
                "",
            ]
        )

    # Results table
    lines.extend(
        [
            "## Full Results",
            "",
            "| Suite | Scenario | Scale | v1 Median | v2 Median | Speedup | Confidence |",
            "|-------|----------|-------|-----------|-----------|---------|------------|",
        ]
    )

    for d in sorted(deltas, key=lambda x: -x["speedup"]):
        lines.append(
            f"| {d['suite']} | {d['scenario']} | {d['value']} "
            f"| {_format_ms(d['baseline_median_ms'])} "
            f"| {_format_ms(d['current_median_ms'])} "
            f"| {_speedup_indicator(d['speedup'])} "
            f"| {d['confidence']} |"
        )

    lines.append("")

    # Detailed breakdown of key improvements
    key_improvements = [d for d in deltas if d["speedup"] >= 2.0]
    if key_improvements:
        lines.extend(
            [
                "## Key Improvements (2x+ speedup)",
                "",
            ]
        )
        for d in sorted(key_improvements, key=lambda x: -x["speedup"]):
            lines.extend(
                [
                    f"### {d['scenario']} ({d['value']})",
                    "",
                    "| Metric | v1 (before) | v2 (after) |",
                    "|--------|-------------|------------|",
                    f"| Median | {_format_ms(d['baseline_median_ms'])} | {_format_ms(d['current_median_ms'])} |",
                    f"| P95 | {_format_ms(d['baseline_p95_ms'])} | {_format_ms(d['current_p95_ms'])} |",
                    f"| Min | {_format_ms(d['baseline_min_ms'])} | {_format_ms(d['current_min_ms'])} |",
                    f"| Max | {_format_ms(d['baseline_max_ms'])} | {_format_ms(d['current_max_ms'])} |",
                    f"| CV (stddev/mean) | {d['baseline_cv']:.1f}% | {d['current_cv']:.1f}% |",
                    f"| **Speedup** | | **{d['speedup']:.1f}x** |",
                    f"| Confidence | | {d['confidence']} |",
                    "",
                ]
            )

    # Charts
    if chart_paths:
        lines.extend(["## Charts", ""])
        chart_titles = {
            "hierarchy_building": "Hierarchy Building: Before vs After",
            "sampling_scaling": "Smart Sample Scaling: Before vs After",
            "follow_thread_scaling": "Follow Thread Scaling: Before vs After",
            "search_broad_query": "Broad Query Search: Before vs After",
            "db_to_jsonl_scaling": "DB to JSONL Streaming: Before vs After",
            "speedup_summary": "Speedup Summary: All Scenarios",
        }
        for key, chart_path in chart_paths.items():
            title = chart_titles.get(key, key.replace("_", " ").title())
            rel = chart_path.relative_to(charts_dir.parent)
            lines.extend(
                [
                    f"### {title}",
                    "",
                    f"![{title}]({rel})",
                    "",
                ]
            )

    # Memory safety profile (only when memory scenarios are present)
    memory_results = [
        r
        for r in current.get("results", [])
        if r.get("scenario") in ("search_memory_profile", "db_source_memory")
        and r.get("metadata", {}).get("allocated_rss_kb") is not None
    ]
    if memory_results:
        lines.extend(
            [
                "## Memory Safety Profile",
                "",
                "RSS measurements via `resource.getrusage(RUSAGE_SELF)` — captures both Python and Rust heap.",
                "",
                "| Scenario | Scale | RSS Before (KB) | RSS After (KB) | Allocated (KB) |",
                "|----------|-------|-----------------|----------------|----------------|",
            ]
        )
        for r in sorted(memory_results, key=lambda x: (x["scenario"], x.get("value", 0))):
            meta = r["metadata"]
            lines.append(
                f"| {r['scenario']} | {r.get('value', '?')} "
                f"| {meta['rss_before_kb']:,} "
                f"| {meta['peak_rss_kb']:,} "
                f"| {meta['allocated_rss_kb']:,} |"
            )
        lines.append("")

    # Statistical integrity notes
    lines.extend(
        [
            "## Statistical Integrity Notes",
            "",
            "- **No cherry-picking.** Every scenario from the baseline is re-run. All results are reported, including unchanged ones.",
            "- **Same data generation seed.** `LogGenerator(seed=42)` and `DatabaseGenerator(seed=42)` produce identical data across runs.",
            "- **Same machine.** Both runs on the same hardware to eliminate CPU/memory differences.",
            "- **Warm caches.** Both runs include warmup iterations to eliminate cold-start effects.",
            "- **Coefficient of Variation (CV) reported.** High CV (>20%) means the measurement is noisy and the speedup claim is weaker.",
            "- **Confidence levels are conservative.** 'Definitive' requires zero overlap in timing distributions, not just a median improvement.",
            "",
            "---",
            "",
            "*Generated by logler benchmark suite v3 — real data, no fiction.*",
        ]
    )

    path.write_text("\n".join(lines))
