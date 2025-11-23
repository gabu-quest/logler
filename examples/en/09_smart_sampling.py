#!/usr/bin/env python3
"""
Example: Smart Sampling Strategies

Demonstrates how to get representative samples of large log files
using different intelligent sampling strategies.
"""

import logler.investigate as investigate

print("=" * 70)
print("Smart Sampling Demo")
print("=" * 70)

log_file = "examples/logs/production_incident.log"

print("\n📊 Scenario: Need to analyze a subset of logs efficiently")
print("-" * 70)

# Strategy 1: Representative sampling
print("\n🎯 Strategy 1: Representative sampling (balanced distribution)")
sample = investigate.smart_sample(
    files=[log_file],
    strategy="representative",
    sample_size=10
)

print(f"Total population: {sample['total_population']} entries")
print(f"Sample size: {sample['sample_size']} entries")
print(f"Strategy: {sample['strategy']}")
print(f"\nCoverage metrics:")
print(f"  Time coverage: {sample['coverage'].get('time_coverage', 0):.1%}")
print(f"  Level distribution: {sample['coverage']['level_distribution']}")
print(f"  Thread coverage: {sample['coverage'].get('thread_coverage_pct', 0):.1%}")

print("\n  Sample entries (first 3):")
for i, entry in enumerate(sample['samples'][:3], 1):
    print(f"  {i}. [{entry.get('level', 'INFO'):5s}] {entry.get('message', '')[:60]}")

# Strategy 2: Diverse sampling (maximum variety)
print("\n🌈 Strategy 2: Diverse sampling (maximum variety)")
sample = investigate.smart_sample(
    files=[log_file],
    strategy="diverse",
    sample_size=10
)

print(f"Sample size: {sample['sample_size']} entries")
print(f"Unique messages in sample: {sample['coverage']['level_distribution']}")
print("\n  Sample entries (showing variety):")
for i, entry in enumerate(sample['samples'][:3], 1):
    print(f"  {i}. [{entry.get('level', 'INFO'):5s}] {entry.get('message', '')[:60]}")

# Strategy 3: Errors-focused (70% errors, 30% context)
print("\n🚨 Strategy 3: Errors-focused (prioritizes errors with context)")
sample = investigate.smart_sample(
    files=[log_file],
    strategy="errors_focused",
    sample_size=10
)

print(f"Sample size: {sample['sample_size']} entries")
print(f"Level distribution: {sample['coverage']['level_distribution']}")
print("\n  Sample entries (errors + context):")
for i, entry in enumerate(sample['samples'][:5], 1):
    level = entry.get('level', 'INFO')
    marker = "🔴" if level in ['ERROR', 'FATAL'] else "  "
    print(f"  {marker} {i}. [{level:5s}] {entry.get('message', '')[:60]}")

# Strategy 4: Chronological (evenly spaced over time)
print("\n⏰ Strategy 4: Chronological (evenly spaced over time)")
sample = investigate.smart_sample(
    files=[log_file],
    strategy="chronological",
    sample_size=10
)

print(f"Sample size: {sample['sample_size']} entries")
print(f"Time coverage: {sample['coverage'].get('time_coverage', 0):.1%}")
print("\n  Sample entries (time-distributed):")
for i, entry in enumerate(sample['samples'][:3], 1):
    timestamp = entry.get('timestamp', 'No timestamp')
    print(f"  {i}. {timestamp} - {entry.get('message', '')[:50]}")

print("\n" + "=" * 70)
print("When to use each strategy:")
print("")
print("• Representative: When you need a balanced view of everything")
print("• Diverse: When you want maximum variety and unique messages")
print("• Errors-focused: When investigating incidents (errors + context)")
print("• Chronological: When analyzing time-based trends")
print("")
print("All strategies ensure good coverage while minimizing token usage!")
print("=" * 70)
