#!/usr/bin/env python3
"""
Example: Token-Efficient Investigation

Demonstrates how to investigate logs while minimizing token usage -
critical for LLMs with limited context windows.
"""

import logler.investigate as investigate

print("=" * 70)
print("Token-Efficient Investigation Demo")
print("=" * 70)

log_file = "examples/logs/production_incident.log"

print("\n📊 Scenario: Need to investigate errors but have limited tokens")
print("-" * 70)

# BAD: Full output uses lots of tokens
print("\n❌ BAD: Full output (uses ~10KB tokens)")
full_results = investigate.search([log_file], level="ERROR", output_format="full")
print(f"   Returned {len(str(full_results))} characters")
print(f"   Contains {len(full_results.get('results', []))} full log entries with all fields")

# GOOD: Summary output - 44x smaller!
print("\n✅ GOOD: Summary output (uses ~230 bytes - 44x smaller!)")
summary_results = investigate.search([log_file], level="ERROR", output_format="summary")
print(f"   Returned {len(str(summary_results))} characters")
print(f"   Total errors: {summary_results['total_matches']}")
print(f"   Unique messages: {summary_results['unique_messages']}")
print(f"   Log levels: {summary_results['log_levels']}")

print("\n   Top error messages:")
for msg in summary_results['top_messages'][:3]:
    print(f"   • {msg['message'][:60]}... (occurred {msg['count']} times)")

# EVEN BETTER: Count mode - just statistics
print("\n✅ EVEN BETTER: Count mode (just statistics)")
count_results = investigate.search([log_file], level="ERROR", output_format="count")
print(f"   Returned {len(str(count_results))} characters")
print(f"   Total matches: {count_results['total_matches']}")
print(f"   By level: {count_results['by_level']}")
print(f"   Time range: {count_results['time_range']['start']} → {count_results['time_range']['end']}")

# Compact mode - essential fields only
print("\n✅ Compact mode (essential fields only)")
compact_results = investigate.search([log_file], level="ERROR", limit=3, output_format="compact")
print(f"   Returned {len(str(compact_results))} characters")
print(f"\n   First 3 errors in compact format:")
for match in compact_results['matches']:
    print(f"   • [{match['level']}] {match['time']} - {match['msg'][:50]}...")

print("\n💡 Strategy: Start with count/summary, drill down with full only when needed")
print("\n" + "=" * 70)
print("Token savings: summary is 44x smaller than full output!")
print("=" * 70)
