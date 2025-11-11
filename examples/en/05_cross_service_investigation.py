#!/usr/bin/env python3
"""
Example: Cross-Service Investigation

Demonstrates how to investigate issues across multiple microservices
using unified timelines and correlation tracking.
"""

import logler.investigate as investigate

print("=" * 70)
print("Cross-Service Investigation Demo")
print("=" * 70)

# For this demo, we'll use a single log with service field
# In production, you'd have separate log files per service
log_file = "examples/logs/microservices_trace.log"

print("\n📊 Step 1: Get overview of all services")
print("-" * 70)
metadata = investigate.get_metadata([log_file])
for meta in metadata:
    print(f"File: {meta['path']}")
    print(f"  Lines: {meta['lines']}")
    print(f"  Time range: {meta['time_range']['start']} → {meta['time_range']['end']}")
    print(f"  Log levels: {meta['log_levels']}")
    print(f"  Services: {meta.get('unique_threads', 'N/A')}")

print("\n🔍 Step 2: Create unified timeline across all services")
print("-" * 70)
timeline = investigate.cross_service_timeline(
    files={
        "microservices": [log_file]
    },
    trace_id="trace-001"
)

print(f"Total entries: {timeline['total_entries']}")
print(f"Duration: {timeline['duration_ms']}ms")
print(f"Services involved: {timeline['services']}")

print("\n📋 Step 3: View request flow across services")
print("-" * 70)
print(f"{'Service':<20} {'Time':>6} {'Level':<6} {'Message':<50}")
print("-" * 100)

for entry in timeline['timeline'][:15]:
    service_name = entry['entry'].get('service', 'unknown')
    rel_time = entry['relative_time_ms']
    level = entry['entry'].get('level', 'INFO')
    message = entry['entry'].get('message', '')

    print(f"{service_name:<20} +{rel_time:4d}ms {level:<6} {message[:50]}")

print("\n⚠️ Step 4: Find where things went wrong")
print("-" * 70)
# Search for errors in the timeline
errors = [e for e in timeline['timeline'] if e['entry'].get('level') in ['ERROR', 'FATAL', 'WARN']]

if errors:
    print(f"Found {len(errors)} warnings/errors:")
    for err in errors[:5]:
        service_name = err['entry'].get('service', 'unknown')
        rel_time = err['relative_time_ms']
        level = err['entry'].get('level')
        message = err['entry'].get('message', '')
        print(f"  [{level:5s}] +{rel_time:4d}ms [{service_name}]: {message}")

print("\n🔎 Step 5: Analyze service-by-service breakdown")
print("-" * 70)
# Group by service
service_entries = {}
for entry in timeline['timeline']:
    service_name = entry['entry'].get('service', 'unknown')
    if service_name not in service_entries:
        service_entries[service_name] = []
    service_entries[service_name].append(entry)

for service_name, entries in service_entries.items():
    error_count = sum(1 for e in entries if e['entry'].get('level') in ['ERROR', 'FATAL'])
    warn_count = sum(1 for e in entries if e['entry'].get('level') == 'WARN')

    # Calculate service time (first to last log)
    if len(entries) > 1:
        service_duration = entries[-1]['relative_time_ms'] - entries[0]['relative_time_ms']
    else:
        service_duration = 0

    print(f"\n{service_name}:")
    print(f"  Entries: {len(entries)}")
    print(f"  Time span: {service_duration}ms")
    print(f"  Errors: {error_count}, Warnings: {warn_count}")
    print(f"  First activity: +{entries[0]['relative_time_ms']}ms")
    print(f"  Last activity: +{entries[-1]['relative_time_ms']}ms")

print("\n💡 Step 6: Key insights")
print("-" * 70)
print("✓ Request flow visualization complete")
print("✓ Identified service with failures")
print("✓ Calculated per-service latency")
print("\nThis cross-service view makes it easy to:")
print("  • Track requests across microservices")
print("  • Identify which service introduced delays")
print("  • Find cascading failures")
print("  • Measure inter-service latency")

print("\n" + "=" * 70)
print("Use cross_service_timeline() for distributed system debugging!")
print("=" * 70)
