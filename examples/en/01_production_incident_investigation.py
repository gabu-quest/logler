"""
Production Incident Investigation - Database Connection Pool Exhaustion

This example demonstrates a real-world scenario where a production service
experiences cascading failures due to database connection pool exhaustion.

Scenario:
- Service starts normal at 14:55:00
- Database connection pool begins to saturate (18/20 connections)
- At 14:55:02, timeouts begin cascading across multiple workers
- Error rate spikes to 85%
- Ops team detects the incident and scales the connection pool
- Slow queries are killed
- Service recovers by 14:55:08

Learning Objectives:
- Use search() to find error patterns
- Use follow_thread() to reconstruct request timelines
- Use find_patterns() to detect cascading failures
- Use SQL queries for time-series analysis
- Identify root cause and resolution timeline
"""

import logler.investigate as investigate
from logler.investigate import Investigator
import json

LOG_FILE = "examples/logs/production_incident.log"

print("=" * 80)
print("PRODUCTION INCIDENT INVESTIGATION")
print("=" * 80)
print()

# Step 1: Get overview of the incident
print("📊 STEP 1: Getting incident overview...")
print("-" * 80)

metadata = investigate.get_metadata([LOG_FILE])
file_meta = metadata[0]

print(f"📝 Log file: {file_meta['path']}")
print(f"📏 Total entries: {file_meta['lines']}")
print(f"⏰ Time range: {file_meta['time_range']['start']} to {file_meta['time_range']['end']}")
print(f"🧵 Unique threads: {file_meta['unique_threads']}")
print(f"🔗 Correlation IDs: {file_meta['unique_correlation_ids']}")
print()
print("Log levels:")
for level, count in sorted(file_meta['log_levels'].items(), key=lambda x: x[1], reverse=True):
    print(f"  {level:10s}: {count:3d} entries")
print()

# Step 2: Find all errors
print("🔍 STEP 2: Searching for errors...")
print("-" * 80)

errors = investigate.search(
    files=[LOG_FILE],
    level="ERROR",
    limit=100
)

print(f"⚠️  Found {errors['total_matches']} ERROR entries in {errors['search_time_ms']}ms")
print()

# Show first few errors
print("First 5 errors:")
for i, result in enumerate(errors['results'][:5], 1):
    entry = result['entry']
    print(f"  {i}. [{entry['timestamp']}] {entry['thread_id']}: {entry['message']}")
print()

# Step 3: Detect error patterns
print("🔎 STEP 3: Detecting error patterns...")
print("-" * 80)

patterns = investigate.find_patterns(
    files=[LOG_FILE],
    min_occurrences=2
)

print(f"📈 Found {len(patterns['patterns'])} error patterns:")
for i, pattern in enumerate(patterns['patterns'], 1):
    print(f"\n  Pattern {i}:")
    print(f"    Message: {pattern['pattern']}")
    print(f"    Occurrences: {pattern['occurrences']}")
    print(f"    First seen: {pattern['first_seen']}")
    print(f"    Last seen: {pattern['last_seen']}")
    print(f"    Affected threads: {', '.join(pattern['affected_threads'][:5])}")
    if len(pattern['affected_threads']) > 5:
        print(f"    ... and {len(pattern['affected_threads']) - 5} more threads")
print()

# Step 4: Investigate a failed request
print("🧵 STEP 4: Following a failed request timeline...")
print("-" * 80)

# Find a request that experienced errors
first_error = errors['results'][0]['entry']
correlation_id = first_error.get('correlation_id')

if correlation_id:
    print(f"📍 Following request: {correlation_id}")
    print()

    timeline = investigate.follow_thread(
        files=[LOG_FILE],
        correlation_id=correlation_id
    )

    print(f"🕐 Request duration: {timeline['duration_ms']}ms")
    print(f"📝 Log entries: {timeline['total_entries']}")
    print(f"🔗 Spans: {len(timeline['unique_spans'])}")
    print()
    print("Timeline:")
    for entry in timeline['entries']:
        level_emoji = {
            "INFO": "ℹ️",
            "WARN": "⚠️",
            "ERROR": "❌",
            "FATAL": "💀"
        }.get(entry['level'], "📝")
        print(f"  {level_emoji} [{entry['timestamp']}] {entry['message'][:70]}")
print()

# Step 5: SQL Analysis - Time series of errors
print("📊 STEP 5: Time-series analysis using SQL...")
print("-" * 80)

investigator = Investigator()
investigator.load_files([LOG_FILE])

# Get error rate over time (per second)
print("Analyzing error rate per second...")
try:
    time_series = investigator.sql_query("""
        SELECT
            strftime('%H:%M:%S', timestamp) as second,
            level,
            COUNT(*) as count
        FROM logs
        WHERE level IN ('ERROR', 'FATAL', 'CRITICAL')
        GROUP BY second, level
        ORDER BY second
    """)

    print("\n⏱️  Error timeline (per second):")
    for row in time_series:
        bar = "█" * min(row['count'], 50)
        print(f"  {row['second']} [{row['level']:8s}] {bar} {row['count']}")
    print()
except Exception as e:
    print(f"⚠️  SQL feature not available: {e}")
    print("  (Build with --features sql to enable)")
    print()

# Step 6: SQL Analysis - Most affected threads
print("🧵 STEP 6: Finding most affected threads...")
print("-" * 80)

try:
    affected_threads = investigator.sql_query("""
        SELECT
            thread_id,
            COUNT(CASE WHEN level IN ('ERROR', 'FATAL') THEN 1 END) as errors,
            COUNT(*) as total_logs,
            COUNT(CASE WHEN level IN ('ERROR', 'FATAL') THEN 1 END) * 100.0 /
                COUNT(*) as error_rate
        FROM logs
        WHERE thread_id IS NOT NULL AND thread_id NOT LIKE '%health%' AND thread_id NOT LIKE '%ops%'
        GROUP BY thread_id
        HAVING errors > 0
        ORDER BY errors DESC
        LIMIT 10
    """)

    print("Top 10 threads by error count:")
    for i, row in enumerate(affected_threads, 1):
        print(f"  {i:2d}. {row['thread_id']:12s}: {int(row['errors']):2d} errors / {int(row['total_logs']):2d} total ({row['error_rate']:.0f}% error rate)")
    print()
except Exception as e:
    print(f"⚠️  SQL feature not available: {e}")
    print()

# Step 7: Find the resolution
print("✅ STEP 7: Finding incident resolution...")
print("-" * 80)

resolution = investigate.search(
    files=[LOG_FILE],
    query="resolved",
    limit=10
)

if resolution['results']:
    for result in resolution['results']:
        entry = result['entry']
        print(f"🎯 Resolution found at {entry['timestamp']}:")
        print(f"   Thread: {entry['thread_id']}")
        print(f"   Message: {entry['message']}")
        print()

# Step 8: Identify root cause
print("🔬 STEP 8: Root cause analysis...")
print("-" * 80)

print("Looking for connection pool warnings...")
pool_warnings = investigate.search(
    files=[LOG_FILE],
    query="connection pool",
    limit=10
)

for result in pool_warnings['results']:
    entry = result['entry']
    if entry['level'] == 'WARN':
        print(f"⚠️  [{entry['timestamp']}] {entry['message']}")

print()

# Summary
print("=" * 80)
print("📋 INVESTIGATION SUMMARY")
print("=" * 80)
print()
print("🔍 Root Cause:")
print("   Database connection pool exhaustion (18/20 connections in use)")
print("   Slow queries were blocking connections, causing a cascade of timeouts")
print()
print("📈 Impact:")
print(f"   - {errors['total_matches']} failed requests")
print(f"   - Error rate peaked at 85%")
print(f"   - {len(set(e['entry']['thread_id'] for e in errors['results']))} worker threads affected")
print()
print("✅ Resolution:")
print("   1. Scaled connection pool from 20 to 50 connections")
print("   2. Killed 3 slow-running queries")
print("   3. Service recovered in ~2.2 seconds")
print()
print("💡 Recommendations:")
print("   - Monitor connection pool usage proactively")
print("   - Set stricter query timeout limits")
print("   - Implement automatic slow query killing")
print("   - Add alerting for connection pool saturation > 80%")
print()

print("=" * 80)
print("Investigation complete! ✨")
print("=" * 80)
