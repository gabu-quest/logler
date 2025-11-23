#!/usr/bin/env python3
"""
Example: Comparison and Diff Features

Demonstrates how to compare successful vs failed requests, and
before/after time periods to find what changed.
"""

import logler.investigate as investigate

print("=" * 70)
print("Comparison and Diff Demo")
print("=" * 70)

log_file = "examples/logs/production_incident.log"

# Note: For this demo, we'll compare the same trace to show the feature
# In real usage, you'd compare different correlation_ids or time periods

print("\n🔀 Part 1: Compare Time Periods")
print("-" * 70)
print("Use case: What changed after deployment at 10:32?")

try:
    comparison = investigate.compare_time_periods(
        files=[log_file],
        period_a_start="2024-01-10T10:30:00Z",
        period_a_end="2024-01-10T10:32:00Z",
        period_b_start="2024-01-10T10:32:00Z",
        period_b_end="2024-01-10T10:34:00Z"
    )

    print("\n📊 Period A (before deployment):")
    print(f"   Total logs: {comparison['period_a']['total_logs']}")
    print(f"   Error count: {comparison['period_a']['error_count']}")
    print(f"   Error rate: {comparison['period_a']['error_rate']:.1%}")
    print(f"   Unique threads: {comparison['period_a']['unique_threads']}")

    print("\n📊 Period B (after deployment):")
    print(f"   Total logs: {comparison['period_b']['total_logs']}")
    print(f"   Error count: {comparison['period_b']['error_count']}")
    print(f"   Error rate: {comparison['period_b']['error_rate']:.1%}")
    print(f"   Unique threads: {comparison['period_b']['unique_threads']}")

    print("\n🔍 Changes detected:")
    print(f"   Log volume change: {comparison['changes']['log_volume_change_pct']:+.1f}%")
    print(f"   Error rate multiplier: {comparison['changes']['error_rate_multiplier']:.1f}x")
    print(f"   Error count change: {comparison['changes']['error_count_change']:+d}")

    if comparison['changes']['new_errors']:
        print(f"\n   ⚠️  New errors appeared:")
        for error in comparison['changes']['new_errors'][:3]:
            print(f"      • {error}")

    if comparison['changes']['resolved_errors']:
        print(f"\n   ✅ Errors resolved:")
        for error in comparison['changes']['resolved_errors'][:3]:
            print(f"      • {error}")

    print(f"\n💡 Summary: {comparison['summary']}")

except Exception as e:
    print(f"   (Skipped: {e})")

print("\n🔀 Part 2: Compare Threads/Requests")
print("-" * 70)
print("Use case: What's different between successful and failed requests?")

# For demo purposes, we'll show the API even though we need actual different threads
print("\nExample API usage:")
print("""
    diff = investigate.compare_threads(
        files=["app.log"],
        correlation_a="req-success-12345",
        correlation_b="req-failed-67890"
    )

    # Returns:
    {
        "thread_a": {
            "duration_ms": 234,
            "error_count": 0,
            "log_levels": {"INFO": 15}
        },
        "thread_b": {
            "duration_ms": 2575,
            "error_count": 5,
            "log_levels": {"INFO": 10, "ERROR": 5}
        },
        "differences": {
            "duration_diff_ms": 2341,
            "error_diff": 5,
            "only_in_b": ["cache miss", "timeout", "retry failed"]
        },
        "summary": "Thread B took 2341ms longer and had 5 more errors..."
    }
""")

print("\n💡 Real-world comparison scenarios:")
print("-" * 70)
print("\n1. Before/After Deployment:")
print("   compare_time_periods()")
print("   → Find new errors introduced by deployment")
print("   → Detect performance regressions")
print("   → Identify configuration issues")

print("\n2. Successful vs Failed Requests:")
print("   compare_threads(correlation_a='success', correlation_b='failed')")
print("   → See what went wrong in failed requests")
print("   → Identify missing cache hits, timeouts, etc.")
print("   → Understand root cause differences")

print("\n3. Load Testing Comparison:")
print("   compare_time_periods() for low load vs high load")
print("   → Find bottlenecks under load")
print("   → Identify resource exhaustion patterns")
print("   → Detect cascading failures")

print("\n" + "=" * 70)
print("Comparison features help answer:")
print("• What changed?")
print("• Why did this request fail when others succeeded?")
print("• What's different before and after the deployment?")
print("=" * 70)
