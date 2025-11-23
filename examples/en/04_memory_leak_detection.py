"""
Memory Leak Detection

This example demonstrates how to detect and analyze memory leaks using log data.

Scenario:
- Application starts with 150MB memory usage
- Memory steadily increases over 1.77 hours
- Garbage collection becomes less effective over time
- Eventually leads to OutOfMemoryError
- Application crashes at 598MB

Learning Objectives:
- Detect gradual memory increase patterns
- Analyze garbage collection effectiveness
- Identify memory leak symptoms
- Calculate memory growth rates
- Predict time to OOM (Out of Memory)
"""

import sys
sys.path.insert(0, '/home/user/logler')

import logler.investigate as investigate
from logler.investigate import Investigator
from datetime import datetime

LOG_FILE = "examples/logs/memory_leak.log"

print("=" * 80)
print("MEMORY LEAK DETECTION")
print("=" * 80)
print()

# Step 1: Overview
print("📊 STEP 1: Getting application overview...")
print("-" * 80)

metadata = investigate.get_metadata([LOG_FILE])
file_meta = metadata[0]

print(f"📝 Total log entries: {file_meta['lines']}")
print(f"⏰ Time range: {file_meta['time_range']['start']} to {file_meta['time_range']['end']}")
print()

# Parse timestamps to calculate duration
start_time = datetime.fromisoformat(file_meta['time_range']['start'].replace('Z', '+00:00'))
end_time = datetime.fromisoformat(file_meta['time_range']['end'].replace('Z', '+00:00'))
duration_hours = (end_time - start_time).total_seconds() / 3600

print(f"📅 Application ran for: {duration_hours:.2f} hours")
print()

# Step 2: Find memory-related logs
print("🔍 STEP 2: Searching for memory-related logs...")
print("-" * 80)

memory_logs = investigate.search(
    files=[LOG_FILE],
    query="memory",
    limit=100
)

print(f"Found {memory_logs['total_matches']} memory-related entries")
print()

# Step 3: Extract memory readings
print("📈 STEP 3: Analyzing memory growth...")
print("-" * 80)

# Get all memory reports
all_entries = investigate.follow_thread(
    files=[LOG_FILE],
    thread_id="monitor"
)

memory_readings = []
for entry in all_entries['entries']:
    if 'memory_mb' in entry.get('fields', {}):
        memory_readings.append({
            'timestamp': entry['timestamp'],
            'memory_mb': entry['fields']['memory_mb'],
            'heap_used_mb': entry['fields'].get('heap_used_mb', 0)
        })

if memory_readings:
    print(f"Collected {len(memory_readings)} memory readings")
    print()
    print("Memory growth timeline:")

    # Show every 3rd reading to keep output compact
    for i, reading in enumerate(memory_readings):
        if i % 3 == 0 or i == len(memory_readings) - 1:
            mem = reading['memory_mb']
            heap = reading['heap_used_mb']
            time = reading['timestamp'][11:19]  # Extract HH:MM:SS
            bar = "█" * int(mem / 20)
            print(f"  {time}  {mem:3d}MB heap={heap:3d}MB  {bar}")

    # Calculate growth rate
    if len(memory_readings) >= 2:
        first = memory_readings[0]
        last = memory_readings[-1]
        mem_increase = last['memory_mb'] - first['memory_mb']

        time_diff_hours = duration_hours
        growth_rate_per_hour = mem_increase / time_diff_hours if time_diff_hours > 0 else 0

        print()
        print(f"📊 Memory Statistics:")
        print(f"   Starting memory: {first['memory_mb']}MB")
        print(f"   Ending memory: {last['memory_mb']}MB")
        print(f"   Total increase: {mem_increase}MB")
        print(f"   Growth rate: {growth_rate_per_hour:.1f}MB/hour")

print()

# Step 4: Analyze garbage collection
print("🗑️  STEP 4: Analyzing garbage collection effectiveness...")
print("-" * 80)

gc_logs = investigate.search(
    files=[LOG_FILE],
    query="garbage collection",
    limit=100
)

print(f"Found {gc_logs['total_matches']} GC events")
print()

# Extract GC effectiveness
for result in gc_logs['results']:
    entry = result['entry']
    if 'completed' in entry['message'] or 'failed' in entry['message']:
        fields = entry.get('fields', {})
        reclaimed = fields.get('reclaimed_mb', 0)
        duration = fields.get('duration_ms', 0)
        memory_after = fields.get('memory_after_mb', 0)

        status = "✅" if reclaimed > 20 else "⚠️" if reclaimed > 10 else "❌"
        print(f"  {status} {entry['timestamp'][11:19]}: Reclaimed {reclaimed}MB in {duration}ms → {memory_after}MB")

print()

# Step 5: Identify warnings and errors
print("⚠️  STEP 5: Identifying memory warnings...")
print("-" * 80)

warnings = investigate.search(
    files=[LOG_FILE],
    level="WARN",
    limit=100
)

errors = investigate.search(
    files=[LOG_FILE],
    level="ERROR",
    limit=100
)

fatals = investigate.search(
    files=[LOG_FILE],
    level="FATAL",
    limit=100
)

print(f"⚠️  Warnings: {warnings['total_matches']}")
print(f"❌ Errors: {errors['total_matches']}")
print(f"💀 Fatal: {fatals['total_matches']}")
print()

print("Warning progression:")
for result in warnings['results']:
    entry = result['entry']
    time = entry['timestamp'][11:19]
    print(f"  ⚠️  {time}: {entry['message'][:60]}")

print()

# Step 6: Find leak indicators
print("🔬 STEP 6: Looking for memory leak indicators...")
print("-" * 80)

leak_logs = investigate.search(
    files=[LOG_FILE],
    query="leak",
    limit=100
)

if leak_logs['total_matches'] > 0:
    print(f"Found {leak_logs['total_matches']} leak-related entries:")
    for result in leak_logs['results']:
        entry = result['entry']
        print(f"  🔍 {entry['timestamp'][11:19]}: {entry['message']}")

        # Show suspected objects if available
        fields = entry.get('fields', {})
        if 'leak_suspected_objects' in fields:
            print(f"     Suspected objects: {fields['leak_suspected_objects']}")
else:
    print("No explicit leak indicators found (checking patterns...)")

print()

# Step 7: Detect OOM errors
print("💀 STEP 7: OutOfMemoryError detection...")
print("-" * 80)

oom_logs = investigate.search(
    files=[LOG_FILE],
    query="OutOfMemory",
    limit=100
)

if oom_logs['total_matches'] > 0:
    print(f"❌ Found {oom_logs['total_matches']} OutOfMemoryError events!")
    print()
    for result in oom_logs['results']:
        entry = result['entry']
        time = entry['timestamp'][11:19]
        thread = entry.get('thread_id', 'unknown')
        print(f"  💀 {time} [{thread}]: {entry['message']}")
else:
    print("✅ No OutOfMemoryErrors detected")

print()

# Step 8: Summary and recommendations
print("=" * 80)
print("📋 MEMORY LEAK ANALYSIS SUMMARY")
print("=" * 80)
print()

if memory_readings:
    first = memory_readings[0]
    last = memory_readings[-1]
    mem_increase = last['memory_mb'] - first['memory_mb']
    growth_rate_per_hour = mem_increase / duration_hours if duration_hours > 0 else 0

print("🔍 Findings:")
print(f"   - Memory grew from {first['memory_mb']}MB to {last['memory_mb']}MB")
print(f"   - Growth rate: {growth_rate_per_hour:.1f}MB/hour ({mem_increase}MB over {duration_hours:.2f}h)")
print(f"   - Garbage collection became progressively less effective")
print(f"   - Multiple GC cycles reclaimed <5% of memory (memory leak indicator)")
print()

if leak_logs['total_matches'] > 0:
    print("🐛 Root Cause:")
    print("   - Memory leak detected in: EventListener, CacheEntry objects")
    print("   - Objects not being properly released after use")
    print("   - Accumulating in heap over time")
    print()

if oom_logs['total_matches'] > 0:
    print("💥 Impact:")
    print(f"   - Application crashed after {duration_hours:.2f} hours")
    print(f"   - {oom_logs['total_matches']} requests failed with OOM")
    print("   - Service marked unhealthy")
    print()

print("💡 Recommendations:")
print("   1. Profile the application to identify leaking objects")
print("   2. Review EventListener and CacheEntry lifecycle management")
print("   3. Ensure proper cleanup of event handlers")
print("   4. Implement cache eviction policy with TTL")
print("   5. Add memory monitoring and auto-restart when threshold reached")
print("   6. Consider using WeakReference for cache entries")
print("   7. Add heap dump on OOM for post-mortem analysis")
print()

print("🔧 Immediate Actions:")
print("   - Restart application to restore service")
print("   - Enable heap dump on OOM: -XX:+HeapDumpOnOutOfMemoryError")
print("   - Add memory alert at 50% utilization")
print("   - Investigate EventListener registration patterns")
print()

print("=" * 80)
print("Analysis complete! ✨")
print("=" * 80)
