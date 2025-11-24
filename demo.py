#!/usr/bin/env python3
"""
Quick 30-Second Demo of Logler's LLM Investigation Features

This demonstrates what an LLM agent can do with logler in under a minute.
"""

import logler.investigate as investigate

LOG_FILE = "examples/logs/production_incident.log"

print("🔍 Logler - LLM Investigation Engine Demo")
print("=" * 60)
print()

# 1. Quick Overview (5 seconds)
print("📊 Quick Overview:")
metadata = investigate.get_metadata([LOG_FILE])
print(f"   {metadata[0]['lines']} log entries")
print(f"   {metadata[0]['unique_threads']} threads")
print(f"   {metadata[0]['log_levels']['ERROR']} errors")
print()

# 2. Find Error Patterns (5 seconds)
print("🔍 Finding Error Patterns...")
patterns = investigate.find_patterns([LOG_FILE], min_occurrences=2)
if patterns['patterns']:
    p = patterns['patterns'][0]
    print(f"   Top issue: '{p['pattern'][:50]}...'")
    print(f"   Occurred {p['occurrences']} times")
print()

# 3. Search for Specific Errors (5 seconds)
print("⚠️  Searching for Database Errors...")
results = investigate.search(
    files=[LOG_FILE],
    query="database",
    level="ERROR",
    limit=3
)
print(f"   Found {results['total_matches']} errors in {results['search_time_ms']}ms")
for i, result in enumerate(results['results'][:2], 1):
    entry = result['entry']
    print(f"   {i}. Line {entry['line_number']}: {entry['message'][:45]}...")
print()

# 4. Follow a Failed Request (10 seconds)
print("🧵 Following Failed Request Timeline...")
first_error = results['results'][0]['entry']
if first_error.get('correlation_id'):
    timeline = investigate.follow_thread(
        files=[LOG_FILE],
        correlation_id=first_error['correlation_id']
    )
    print(f"   Request took {timeline['duration_ms']}ms")
    print(f"   {timeline['total_entries']} log entries")
    print()
    print("   Timeline:")
    for entry in timeline['entries'][:3]:
        level_emoji = {"INFO": "ℹ️", "ERROR": "❌", "FATAL": "💀", "WARN": "⚠️"}.get(entry['level'], "📝")
        print(f"   {level_emoji} {entry['message'][:50]}")
    if timeline['total_entries'] > 3:
        print(f"   ... and {timeline['total_entries'] - 3} more entries")
print()

# 5. Summary (5 seconds)
print("=" * 60)
print("✨ Investigation Complete!")
print()
print("💡 This took ~30 seconds to:")
print("   ✓ Parse and index the log file")
print("   ✓ Find repeated error patterns")
print("   ✓ Search for specific issues")
print("   ✓ Reconstruct request timelines")
print()
print("📚 For more examples:")
print("   python examples/en/01_production_incident_investigation.py")
print("   python examples/en/03_distributed_tracing.py")
print()
print("🚀 Built with Rust for speed, designed for AI agents!")
