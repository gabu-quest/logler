"""
Hierarchy Visualization - Tree, Waterfall, Flamegraph, and Error Flow

Demonstrates logler's multi-level thread hierarchy detection and visualization:
- Tree view with parent-child relationships
- Waterfall timeline showing parallel operations
- Flamegraph for performance bottleneck analysis
- Error flow analysis for root cause identification

This example uses OpenTelemetry-style logs with explicit parent_span_id fields
for 100% accurate hierarchy detection.
"""

import tempfile
import os
import logler.investigate as investigate
from logler.tree_formatter import format_tree, format_waterfall, format_flamegraph

# Create a sample log file with hierarchical spans
SAMPLE_LOGS = """
{"timestamp": "2024-01-15T10:00:00.000Z", "level": "INFO", "message": "Request received", "thread_id": "api-gateway", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-000", "service": "api-gateway"}
{"timestamp": "2024-01-15T10:00:00.010Z", "level": "INFO", "message": "Authenticating user", "thread_id": "auth-service", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-001", "parent_span_id": "span-000", "service": "auth-service"}
{"timestamp": "2024-01-15T10:00:00.015Z", "level": "DEBUG", "message": "JWT validation", "thread_id": "auth-service", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-001a", "parent_span_id": "span-001", "service": "auth-service"}
{"timestamp": "2024-01-15T10:00:00.020Z", "level": "INFO", "message": "User lookup", "thread_id": "auth-service", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-001b", "parent_span_id": "span-001", "service": "auth-service"}
{"timestamp": "2024-01-15T10:00:00.045Z", "level": "INFO", "message": "Auth complete", "thread_id": "auth-service", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-001", "parent_span_id": "span-000", "service": "auth-service"}
{"timestamp": "2024-01-15T10:00:00.050Z", "level": "INFO", "message": "Fetching product data", "thread_id": "product-service", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-002", "parent_span_id": "span-000", "service": "product-service"}
{"timestamp": "2024-01-15T10:00:00.060Z", "level": "INFO", "message": "Checking inventory", "thread_id": "inventory-service", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-002a", "parent_span_id": "span-002", "service": "inventory-service"}
{"timestamp": "2024-01-15T10:00:00.100Z", "level": "INFO", "message": "Database query", "thread_id": "inventory-service", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-002a1", "parent_span_id": "span-002a", "service": "inventory-service"}
{"timestamp": "2024-01-15T10:00:00.350Z", "level": "WARN", "message": "Slow query detected", "thread_id": "inventory-service", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-002a1", "parent_span_id": "span-002a", "service": "inventory-service"}
{"timestamp": "2024-01-15T10:00:00.400Z", "level": "INFO", "message": "Inventory check complete", "thread_id": "inventory-service", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-002a", "parent_span_id": "span-002", "service": "inventory-service"}
{"timestamp": "2024-01-15T10:00:00.410Z", "level": "INFO", "message": "Updating cache", "thread_id": "cache-service", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-002b", "parent_span_id": "span-002", "service": "cache-service"}
{"timestamp": "2024-01-15T10:00:00.450Z", "level": "ERROR", "message": "Redis connection failed", "thread_id": "cache-service", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-002b1", "parent_span_id": "span-002b", "service": "cache-service"}
{"timestamp": "2024-01-15T10:00:00.455Z", "level": "ERROR", "message": "Cache update failed", "thread_id": "cache-service", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-002b", "parent_span_id": "span-002", "service": "cache-service"}
{"timestamp": "2024-01-15T10:00:00.460Z", "level": "WARN", "message": "Proceeding without cache", "thread_id": "product-service", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-002", "parent_span_id": "span-000", "service": "product-service"}
{"timestamp": "2024-01-15T10:00:00.500Z", "level": "INFO", "message": "Product data fetched", "thread_id": "product-service", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-002", "parent_span_id": "span-000", "service": "product-service"}
{"timestamp": "2024-01-15T10:00:00.510Z", "level": "INFO", "message": "Assembling response", "thread_id": "api-gateway", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-003", "parent_span_id": "span-000", "service": "api-gateway"}
{"timestamp": "2024-01-15T10:00:00.520Z", "level": "INFO", "message": "Request completed (degraded)", "thread_id": "api-gateway", "correlation_id": "req-001", "trace_id": "trace-abc", "span_id": "span-000", "service": "api-gateway"}
""".strip()


def main():
    # Create temporary log file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
        f.write(SAMPLE_LOGS)
        log_file = f.name

    try:
        print("=" * 80)
        print("HIERARCHY VISUALIZATION DEMO")
        print("=" * 80)
        print()
        print("This demo shows logler's hierarchy detection and visualization capabilities.")
        print("We're analyzing a microservice request with nested spans and an error cascade.")
        print()

        # 1. Build hierarchy
        print("=" * 80)
        print("1. BUILDING HIERARCHY")
        print("=" * 80)

        hierarchy = investigate.follow_thread_hierarchy(
            files=[log_file],
            root_identifier="req-001",  # Can use correlation_id, trace_id, or span_id
            use_naming_patterns=True,
            use_temporal_inference=True,
            min_confidence=0.0
        )

        print(f"Total nodes: {hierarchy.get('total_nodes', 0)}")
        print(f"Max depth: {hierarchy.get('max_depth', 0)}")
        print(f"Detection method: {hierarchy.get('detection_method', 'Unknown')}")
        print(f"Total duration: {hierarchy.get('total_duration_ms', 0)}ms")

        if hierarchy.get('bottleneck'):
            bn = hierarchy['bottleneck']
            print(f"Bottleneck: {bn.get('node_id')} ({bn.get('duration_ms')}ms, {bn.get('percentage_of_total', 0):.1f}%)")

        if hierarchy.get('error_nodes'):
            print(f"Error nodes: {', '.join(hierarchy['error_nodes'])}")

        print()

        # 2. Tree View
        print("=" * 80)
        print("2. TREE VIEW (Compact Mode)")
        print("=" * 80)
        print()
        tree_str = format_tree(hierarchy, mode="compact", show_duration=True, show_errors=True)
        print(tree_str)
        print()

        # 3. Tree View (Detailed Mode)
        print("=" * 80)
        print("3. TREE VIEW (Detailed Mode)")
        print("=" * 80)
        print()
        tree_detailed = format_tree(hierarchy, mode="detailed", show_duration=True, show_errors=True, show_confidence=True)
        print(tree_detailed)
        print()

        # 4. Waterfall View
        print("=" * 80)
        print("4. WATERFALL TIMELINE")
        print("=" * 80)
        print()
        print("Shows temporal relationships and parallel operations:")
        print()
        waterfall_str = format_waterfall(hierarchy, width=80, show_labels=True, show_errors=True)
        print(waterfall_str)
        print()

        # 5. Flamegraph View
        print("=" * 80)
        print("5. FLAMEGRAPH VIEW")
        print("=" * 80)
        print()
        print("Shows time distribution across the call stack:")
        print()
        flamegraph_str = format_flamegraph(hierarchy, width=80, use_colors=False)
        print(flamegraph_str)
        print()

        # 6. Error Flow Analysis
        print("=" * 80)
        print("6. ERROR FLOW ANALYSIS")
        print("=" * 80)
        print()

        error_analysis = investigate.analyze_error_flow(hierarchy)

        print("Root Causes:")
        for i, cause in enumerate(error_analysis.get('root_causes', [])[:3], 1):
            print(f"  {i}. {cause.get('node_id')} (confidence: {cause.get('confidence', 0)*100:.0f}%)")
            if cause.get('path'):
                print(f"     Path: {' -> '.join(cause['path'])}")

        print()
        print("Propagation Chains:")
        for i, chain in enumerate(error_analysis.get('propagation_chains', [])[:3], 1):
            print(f"  Chain {i}: {chain.get('root_cause')} -> {chain.get('total_affected')} affected nodes")

        print()
        impact = error_analysis.get('impact_summary', {})
        print("Impact Summary:")
        print(f"  Total affected nodes: {impact.get('total_affected_nodes', 0)}")
        print(f"  Affected percentage: {impact.get('affected_percentage', 0):.1f}%")
        print(f"  Max propagation depth: {impact.get('max_propagation_depth', 0)}")

        print()
        print("Recommendations:")
        for rec in error_analysis.get('recommendations', [])[:5]:
            print(f"  - {rec}")

        print()

        # 7. Hierarchy Summary
        print("=" * 80)
        print("7. HIERARCHY SUMMARY")
        print("=" * 80)
        print()
        summary = investigate.get_hierarchy_summary(hierarchy)
        print(summary)
        print()

        # 8. Performance Analysis
        print("=" * 80)
        print("8. PERFORMANCE ANALYSIS")
        print("=" * 80)
        print()

        perf_analysis = investigate.analyze_hierarchy_performance(hierarchy)

        print("Critical Path:")
        for node in perf_analysis.get('critical_path', [])[:5]:
            print(f"  - {node.get('id')}: {node.get('duration_ms')}ms ({node.get('percentage', 0):.1f}%)")

        print()
        print("Parallelization Opportunities:")
        for opp in perf_analysis.get('parallelization_opportunities', [])[:3]:
            print(f"  - Depth {opp.get('depth')}: {', '.join(opp.get('nodes', []))}")
            print(f"    Potential savings: {opp.get('potential_savings_ms', 0):.0f}ms")

        print()
        print("Optimization Suggestions:")
        for sug in perf_analysis.get('optimization_suggestions', [])[:5]:
            print(f"  - {sug}")

        print()
        print("=" * 80)
        print("DEMO COMPLETE!")
        print("=" * 80)
        print()
        print("Key takeaways:")
        print("  1. Use parent_span_id for 100% accurate hierarchy detection")
        print("  2. Tree view shows structure, waterfall shows timing")
        print("  3. Error flow analysis identifies root causes automatically")
        print("  4. Performance analysis finds optimization opportunities")
        print()
        print("CLI equivalents:")
        print("  logler investigate app.log --correlation req-001 --hierarchy")
        print("  logler investigate app.log --correlation req-001 --hierarchy --waterfall")
        print("  logler investigate app.log --correlation req-001 --hierarchy --flamegraph")
        print("  logler investigate app.log --hierarchy --show-error-flow")
        print()

    finally:
        # Cleanup
        os.unlink(log_file)


if __name__ == "__main__":
    main()
