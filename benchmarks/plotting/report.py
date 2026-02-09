"""Report generator — creates markdown report with charts from benchmark results."""

from __future__ import annotations

import json
from pathlib import Path

from .charts import (
    plot_comparison_bars,
    plot_scaling_lines,
)
from .theme import apply_dark_theme


def generate_report(input_path: str, output_dir: str) -> None:
    """Generate full benchmark report with charts and markdown."""
    data = json.loads(Path(input_path).read_text())
    results = data["results"]
    system_info = _format_system_info(data.get("system", {}))
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    charts_dir = out / "charts"
    charts_dir.mkdir(exist_ok=True)

    apply_dark_theme()

    chart_paths: dict[str, Path] = {}

    # Group results by scenario
    by_scenario: dict[str, list[dict]] = {}
    for r in results:
        scenario = r["scenario"]
        if scenario not in by_scenario:
            by_scenario[scenario] = []
        by_scenario[scenario].append(r)

    # --- Search Suite Charts ---
    if "search_scaling" in by_scenario:
        chart_paths["search_scaling"] = plot_scaling_lines(
            by_scenario["search_scaling"],
            "Search Scaling — Throughput by Entry Count",
            system_info,
            charts_dir / "01_search_scaling",
        )

    if "search_by_level" in by_scenario:
        chart_paths["search_by_level"] = plot_comparison_bars(
            by_scenario["search_by_level"],
            "Search by Level — ERROR / WARN / INFO Filter",
            system_info,
            charts_dir / "02_search_by_level",
            show_throughput=True,
        )

    if "search_output_formats" in by_scenario:
        chart_paths["search_output_formats"] = plot_comparison_bars(
            by_scenario["search_output_formats"],
            "Search Output Formats — Time + Response Size",
            system_info,
            charts_dir / "03_search_output_formats",
        )

    if "search_with_filters" in by_scenario:
        chart_paths["search_with_filters"] = plot_scaling_lines(
            by_scenario["search_with_filters"],
            "Combined Filters — Level + Query + Time Range",
            system_info,
            charts_dir / "04_search_with_filters",
        )

    # --- Hierarchy Suite Charts ---
    if "hierarchy_building" in by_scenario:
        chart_paths["hierarchy_building"] = plot_scaling_lines(
            by_scenario["hierarchy_building"],
            "Hierarchy Building — follow_thread_hierarchy()",
            system_info,
            charts_dir / "05_hierarchy_building",
        )

    if "error_flow_analysis" in by_scenario:
        chart_paths["error_flow_analysis"] = plot_comparison_bars(
            by_scenario["error_flow_analysis"],
            "Error Flow Analysis — analyze_error_flow()",
            system_info,
            charts_dir / "06_error_flow_analysis",
        )

    if "tree_formatting" in by_scenario:
        chart_paths["tree_formatting"] = plot_comparison_bars(
            by_scenario["tree_formatting"],
            "Tree Formatting — Summary + format_tree()",
            system_info,
            charts_dir / "07_tree_formatting",
        )

    # --- Correlation Suite Charts ---
    if "follow_thread_scaling" in by_scenario:
        chart_paths["follow_thread_scaling"] = plot_scaling_lines(
            by_scenario["follow_thread_scaling"],
            "Follow Thread Scaling — follow_thread()",
            system_info,
            charts_dir / "08_follow_thread_scaling",
        )

    if "cross_service_timeline" in by_scenario:
        chart_paths["cross_service_timeline"] = plot_comparison_bars(
            by_scenario["cross_service_timeline"],
            "Cross-Service Timeline — Service Count Impact",
            system_info,
            charts_dir / "09_cross_service_timeline",
        )

    if "compare_threads" in by_scenario:
        chart_paths["compare_threads"] = plot_scaling_lines(
            by_scenario["compare_threads"],
            "Compare Threads — compare_threads()",
            system_info,
            charts_dir / "10_compare_threads",
        )

    # --- Output Suite Charts ---
    if "output_format_comparison" in by_scenario:
        chart_paths["output_format_comparison"] = plot_comparison_bars(
            by_scenario["output_format_comparison"],
            "Output Format Comparison — Time + Token Savings",
            system_info,
            charts_dir / "11_output_format_comparison",
        )

    if "max_bytes_truncation" in by_scenario:
        chart_paths["max_bytes_truncation"] = plot_comparison_bars(
            by_scenario["max_bytes_truncation"],
            "Max-Bytes Budget Accuracy",
            system_info,
            charts_dir / "12_max_bytes_truncation",
        )

    # --- Sampling Suite Charts ---
    if "sampling_strategies" in by_scenario:
        chart_paths["sampling_strategies"] = plot_comparison_bars(
            by_scenario["sampling_strategies"],
            "Sampling Strategies — errors_focused / diverse / chronological",
            system_info,
            charts_dir / "13_sampling_strategies",
        )

    if "sampling_scaling" in by_scenario:
        chart_paths["sampling_scaling"] = plot_scaling_lines(
            by_scenario["sampling_scaling"],
            "Smart Sample Scaling — smart_sample()",
            system_info,
            charts_dir / "14_sampling_scaling",
        )

    # --- Generate Markdown Report ---
    _write_markdown_report(out / "REPORT.md", data, chart_paths, charts_dir)

    print("\n  Report generated:")
    print(f"    Markdown: {out / 'REPORT.md'}")
    print(f"    Charts:   {charts_dir}/ ({len(chart_paths)} charts)")


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


def _write_markdown_report(
    path: Path, data: dict, chart_paths: dict[str, Path], charts_dir: Path
) -> None:
    """Write the final markdown report."""
    system = data.get("system", {})
    config = data.get("config", {})
    summary = data.get("summary", {})
    results = data.get("results", [])

    lines = [
        "# logler Benchmark Report",
        "",
        f"**Scale**: {config.get('scale', 'unknown')} | "
        f"**Scenarios**: {summary.get('total_scenarios', '?')} | "
        f"**Measurements**: {summary.get('total_measurements', '?')}",
        "",
        f"> {_format_system_info(system)}",
        "",
    ]

    # Summary table
    lines.extend(
        [
            "## Summary",
            "",
            "| Suite | Scenario | Parameter | Median (ms) | P95 (ms) | Throughput |",
            "|-------|----------|-----------|-------------|----------|------------|",
        ]
    )

    for r in results:
        tp = f"{r.get('throughput', 0):,.0f}/s" if r.get("throughput", 0) > 0 else "\u2014"
        lines.append(
            f"| {r['suite']} | {r['scenario']} | "
            f"{r.get('value', '')} | "
            f"{r['timing']['median_ms']:.2f} | "
            f"{r['timing']['p95_ms']:.2f} | "
            f"{tp} |"
        )

    lines.append("")

    # Reading the charts
    lines.extend(
        [
            "## Reading the Charts",
            "",
            "Every benchmark runs multiple iterations. The numbers you see are:",
            "",
            "- **Median** \u2014 the middle value across all iterations. "
            "Half the runs were faster, half were slower. "
            "More stable than the mean because a single slow run doesn't skew it.",
            "- **P95 (95th percentile)** \u2014 95% of runs finished at or below this time. "
            "This is your realistic worst-case.",
            "- **Shaded bands** (on scaling line charts) \u2014 the area between median and p95. "
            "A narrow band means the operation is predictable. "
            "A wide band means variance is high.",
            "- **Error caps** (on bar charts) \u2014 the vertical whisker above each bar extends to p95.",
            "",
        ]
    )

    # Charts section
    lines.extend(["## Charts", ""])

    chart_titles = {
        "search_scaling": "Search Scaling",
        "search_by_level": "Search by Level",
        "search_output_formats": "Search Output Formats",
        "search_with_filters": "Combined Filters",
        "hierarchy_building": "Hierarchy Building",
        "error_flow_analysis": "Error Flow Analysis",
        "tree_formatting": "Tree Formatting",
        "follow_thread_scaling": "Follow Thread Scaling",
        "cross_service_timeline": "Cross-Service Timeline",
        "compare_threads": "Compare Threads",
        "output_format_comparison": "Output Format Comparison",
        "max_bytes_truncation": "Max-Bytes Budget",
        "sampling_strategies": "Sampling Strategies",
        "sampling_scaling": "Smart Sample Scaling",
    }

    for key, chart_path in chart_paths.items():
        title = chart_titles.get(key, key)
        rel_path = chart_path.relative_to(charts_dir.parent) if chart_path else ""
        lines.extend(
            [
                f"### {title}",
                "",
                f"![{title}]({rel_path})",
                "",
            ]
        )

    # Token savings highlight (if output_format_comparison exists)
    output_results = [r for r in results if r["scenario"] == "output_format_comparison"]
    if output_results:
        full_bytes = None
        count_bytes = None
        for r in output_results:
            meta = r.get("metadata", {})
            if "full" in str(r.get("value", "")):
                full_bytes = meta.get("response_bytes", 0)
            if "count" in str(r.get("value", "")):
                count_bytes = meta.get("response_bytes", 0)
        if full_bytes and count_bytes and count_bytes > 0:
            ratio = full_bytes / count_bytes
            lines.extend(
                [
                    "## Token Savings",
                    "",
                    "Output format comparison at fixed query size:",
                    f"- **full**: {full_bytes:,} bytes",
                    f"- **count**: {count_bytes:,} bytes",
                    f"- **Savings ratio**: **{ratio:.0f}x**",
                    "",
                ]
            )

    # Future work
    lines.extend(
        [
            "## Known Gaps / Future Work",
            "",
            "1. **Large file benchmarks** \u2014 1GB+ file indexing and search not yet benchmarked",
            "2. **Rust vs Python comparison** \u2014 direct comparison of Rust-backed vs pure-Python paths",
            "3. **Memory profiling** \u2014 peak memory usage per operation not yet measured",
            "4. **Concurrent access** \u2014 multi-threaded investigation session performance",
            "5. **Real-world log formats** \u2014 syslog, logfmt, and mixed-format benchmarks",
            "",
            "---",
            "",
            "*Generated by logler benchmark suite \u2014 real data, no fiction.*",
        ]
    )

    path.write_text("\n".join(lines))
