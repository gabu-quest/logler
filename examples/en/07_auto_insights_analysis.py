#!/usr/bin/env python3
"""
Example: Automatic Insights and Analysis

Demonstrates the analyze_with_insights() function that automatically
detects patterns, errors, and suggests next steps - the "smart mode"
for LLM investigation.
"""

import logler.investigate as investigate

print("=" * 70)
print("Automatic Insights Demo - Let logler do the thinking!")
print("=" * 70)

log_file = "examples/logs/production_incident.log"

print("\n🎯 One-line auto investigation")
print("-" * 70)

# One function call does everything!
result = investigate.analyze_with_insights(
    files=[log_file],
    auto_investigate=True  # Automatically runs pattern detection
)

print("\n📊 OVERVIEW")
print(f"Total logs analyzed: {result['overview']['total_logs']}")
print(f"Error count: {result['overview']['error_count']}")
print(f"Error rate: {result['overview']['error_rate']:.1%}")
print(f"Log level distribution: {result['overview']['log_levels']}")

print("\n💡 AUTOMATIC INSIGHTS")
print("-" * 70)
if result['insights']:
    for i, insight in enumerate(result['insights'], 1):
        severity_icon = {
            'high': '🔴',
            'medium': '🟡',
            'low': '🟢'
        }.get(insight['severity'], '⚪')

        print(f"\n{severity_icon} Insight #{i}: {insight['type']}")
        print(f"   Severity: {insight['severity'].upper()}")
        print(f"   Description: {insight['description']}")
        print(f"   Suggestion: {insight['suggestion']}")

        if insight.get('evidence') and isinstance(insight['evidence'], dict):
            print(f"   Evidence: {insight['evidence']}")
else:
    print("No critical insights - logs look healthy!")

print("\n📝 SUGGESTIONS")
print("-" * 70)
for i, suggestion in enumerate(result['suggestions'], 1):
    print(f"{i}. {suggestion}")

print("\n🚀 NEXT STEPS")
print("-" * 70)
if result['next_steps']:
    for i, step in enumerate(result['next_steps'], 1):
        print(f"{i}. {step}")
else:
    print("Investigation complete!")

print("\n" + "=" * 70)
print("Summary of detected insights:")
if result['insights']:
    for i, insight in enumerate(result['insights'], 1):
        print(f"{i}. {insight['type']} (severity: {insight['severity']})")
else:
    print("No notable insights detected.")
print("\nAll with actionable suggestions when present.")
print("=" * 70)
