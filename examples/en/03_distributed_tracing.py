"""
Distributed Tracing Across Microservices

This example demonstrates how to follow a request across multiple microservices
using correlation IDs and trace IDs.

Scenario:
- User requests their orders via API Gateway
- Request flows: API Gateway → User Service → Order Service → Inventory Service
- Inventory Service experiences database issues
- System operates in degraded mode, returns partial data
- Request completes with 206 Partial Content

Learning Objectives:
- Follow distributed traces across multiple services
- Understand service dependencies and call graphs
- Identify which service caused the failure
- Measure latency contributions from each service
- Detect degraded mode operations
"""

import logler.investigate as investigate
from logler.investigate import Investigator

LOG_FILE = "examples/logs/microservices_trace.log"

print("=" * 80)
print("DISTRIBUTED TRACING INVESTIGATION")
print("=" * 80)
print()

# Step 1: Overview
print("📊 STEP 1: Getting trace overview...")
print("-" * 80)

metadata = investigate.get_metadata([LOG_FILE])
file_meta = metadata[0]

print(f"📝 Total log entries: {file_meta['lines']}")
print(f"⏰ Time span: {file_meta['time_range']['start']} to {file_meta['time_range']['end']}")
print(f"🔗 Unique correlation IDs: {file_meta['unique_correlation_ids']}")
print()

# Step 2: Follow the trace
print("🔍 STEP 2: Following the distributed trace...")
print("-" * 80)

# Get the trace ID from metadata
trace_id = "trace-001"
correlation_id = "req-abc123"

print(f"📍 Tracing: correlation_id={correlation_id}, trace_id={trace_id}")
print()

timeline = investigate.follow_thread(
    files=[LOG_FILE],
    correlation_id=correlation_id
)

print(f"🕐 Total request duration: {timeline['duration_ms']}ms")
print(f"📝 Total log entries: {timeline['total_entries']}")
print(f"🔗 Unique spans: {len(timeline['unique_spans'])}")
print()

# Step 3: Visualize the call flow
print("🌳 STEP 3: Service call flow visualization...")
print("-" * 80)

# Group by service
services = {}
for entry in timeline['entries']:
    # Extract service from fields
    service = entry.get('fields', {}).get('service', 'unknown')
    if service not in services:
        services[service] = []
    services[service].append(entry)

print("Service call sequence:")
service_order = []
for entry in timeline['entries']:
    service = entry.get('fields', {}).get('service', 'unknown')
    if service not in service_order:
        service_order.append(service)

for i, service in enumerate(service_order, 1):
    indent = "  " * (i - 1)
    logs = services[service]
    first_log = logs[0]
    last_log = logs[-1]

    # Calculate duration for this service
    if first_log.get('timestamp') and last_log.get('timestamp'):
        from datetime import datetime
        start = datetime.fromisoformat(first_log['timestamp'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(last_log['timestamp'].replace('Z', '+00:00'))
        duration_ms = (end - start).total_seconds() * 1000
    else:
        duration_ms = 0

    print(f"{indent}{'└─' if i > 1 else ''}→ {service}: {len(logs)} logs, {duration_ms:.1f}ms")

print()

# Step 4: Identify failures
print("🔥 STEP 4: Identifying failures in the trace...")
print("-" * 80)

errors = investigate.search(
    files=[LOG_FILE],
    correlation_id=correlation_id,
    level="ERROR",
    limit=100
)

fatals = investigate.search(
    files=[LOG_FILE],
    correlation_id=correlation_id,
    level="FATAL",
    limit=100
)

print(f"⚠️  Found {errors['total_matches']} ERROR entries")
print(f"💀 Found {fatals['total_matches']} FATAL entries")
print()

# Show error progression
print("Error timeline:")
all_errors = errors['results'] + fatals['results']
all_errors.sort(key=lambda x: x['entry']['timestamp'])

for result in all_errors:
    entry = result['entry']
    service = entry.get('fields', {}).get('service', 'unknown')
    level_emoji = {"ERROR": "❌", "FATAL": "💀"}.get(entry['level'], "⚠️")
    print(f"  {level_emoji} [{entry['timestamp']}] {service:20s}: {entry['message'][:60]}")

print()

# Step 5: Analyze service health
print("📊 STEP 5: Service health analysis...")
print("-" * 80)

for service_name, logs in services.items():
    error_count = sum(1 for log in logs if log.get('level') in ['ERROR', 'FATAL'])
    warn_count = sum(1 for log in logs if log.get('level') == 'WARN')
    info_count = sum(1 for log in logs if log.get('level') == 'INFO')

    health_emoji = "🔴" if error_count > 0 else "🟡" if warn_count > 0 else "🟢"

    print(f"{health_emoji} {service_name:20s}: {info_count} info, {warn_count} warn, {error_count} errors")

print()

# Step 6: Root cause analysis
print("🔬 STEP 6: Root cause analysis...")
print("-" * 80)

print("Analyzing error propagation...")
print()

# Find the first error
first_error = all_errors[0]['entry'] if all_errors else None
if first_error:
    failing_service = first_error.get('fields', {}).get('service', 'unknown')
    print(f"🎯 Root cause service: {failing_service}")
    print(f"   Error: {first_error['message']}")
    print(f"   Timestamp: {first_error['timestamp']}")
    print()

    # Find downstream impacts
    print("📉 Downstream impact:")
    downstream_errors = [e for e in all_errors[1:] if
                         e['entry'].get('fields', {}).get('service') != failing_service]

    for result in downstream_errors:
        entry = result['entry']
        service = entry.get('fields', {}).get('service', 'unknown')
        print(f"   → {service}: {entry['message'][:60]}")

print()

# Step 7: Latency breakdown
print("⏱️  STEP 7: Latency breakdown by service...")
print("-" * 80)

print("Time spent in each service:")
for service_name in service_order:
    logs = services[service_name]
    service_logs = [log for log in timeline['entries'] if
                   log.get('fields', {}).get('service') == service_name]

    if len(service_logs) >= 2:
        from datetime import datetime
        first = datetime.fromisoformat(service_logs[0]['timestamp'].replace('Z', '+00:00'))
        last = datetime.fromisoformat(service_logs[-1]['timestamp'].replace('Z', '+00:00'))
        duration_ms = (last - first).total_seconds() * 1000
        percentage = (duration_ms / timeline['duration_ms']) * 100 if timeline['duration_ms'] > 0 else 0

        bar = "█" * int(percentage / 5)
        print(f"  {service_name:20s}: {duration_ms:6.1f}ms ({percentage:5.1f}%) {bar}")

print()

# Step 8: Response degradation
print("⚠️  STEP 8: Degraded mode detection...")
print("-" * 80)

degraded_logs = [log for log in timeline['entries'] if
                'degraded' in log['message'].lower() or
                'partial' in log['message'].lower()]

if degraded_logs:
    print(f"Found {len(degraded_logs)} logs indicating degraded mode:")
    for log in degraded_logs:
        service = log.get('fields', {}).get('service', 'unknown')
        print(f"  ⚠️  {service}: {log['message']}")
else:
    print("No degraded mode detected")

print()

# Summary
print("=" * 80)
print("📋 DISTRIBUTED TRACE SUMMARY")
print("=" * 80)
print()
print("🔍 Trace Details:")
print(f"   Correlation ID: {correlation_id}")
print(f"   Trace ID: {trace_id}")
print(f"   Total Duration: {timeline['duration_ms']}ms")
print(f"   Services Involved: {len(services)}")
print()
print("🌐 Service Call Chain:")
print("   API Gateway → User Service → Order Service → Inventory Service")
print()
print("🔥 Root Cause:")
print("   Inventory Service database connection pool exhaustion")
print("   3 retry attempts failed over 50ms")
print()
print("📊 Impact:")
print(f"   - Request returned 206 Partial Content (degraded)")
print(f"   - {errors['total_matches']} errors across services")
print(f"   - Inventory data unavailable for user")
print()
print("💡 Recommendations:")
print("   - Increase Inventory Service database connection pool")
print("   - Implement circuit breaker for graceful degradation")
print("   - Add caching layer for inventory data")
print("   - Set up alerts for connection pool saturation")
print("   - Consider timeouts and fallbacks for resilience")
print()

print("=" * 80)
print("Investigation complete! ✨")
print("=" * 80)
