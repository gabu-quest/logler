#!/usr/bin/env python3
"""
Example: Cross-Service Investigation

One-file demo that treats the microservices trace as if each service wrote to
its own log. The unified timeline shows where the request stumbled and how
long each hop took.
"""

import logler.investigate as investigate

LOG_FILE = "examples/logs/microservices_trace.log"
TRACE_ID = "trace-001"
CORRELATION_ID = "req-abc123"

print("=" * 70)
print("Cross-Service Investigation Demo")
print("=" * 70)

meta = investigate.get_metadata([LOG_FILE])[0]
print(f"Lines: {meta['lines']} | Window: {meta['time_range']['start']} → {meta['time_range']['end']}")

timeline = investigate.cross_service_timeline(
    files={"stack": [LOG_FILE]},
    correlation_id=CORRELATION_ID,
    trace_id=TRACE_ID,
)

events = timeline["timeline"]
if not events:
    raise SystemExit("No timeline events available.")

print(f"\nTotal entries: {timeline['total_entries']}  Duration: {timeline['duration_ms']} ms")

print("\n🧭 Flow (first 15 events)")
print("-" * 70)
print(f"{'service':<18} {'t+ms':>6} {'lvl':<6} message")
for evt in events[:15]:
    svc = evt["service"]
    rel = evt["relative_time_ms"]
    entry = evt["entry"]
    lvl = entry.get("level", "INFO")
    msg = (entry.get("message") or "")[:60]
    marker = { "ERROR": "❌", "FATAL": "💀", "WARN": "⚠️" }.get(lvl, "·")
    print(f"{svc:<18} {rel:>6} {lvl:<6} {marker} {msg}")

print("\n🚨 Hotspots")
print("-" * 70)
hot = [e for e in events if e["entry"].get("level") in ("ERROR", "FATAL", "WARN")]
for evt in hot:
    svc = evt["service"]
    rel = evt["relative_time_ms"]
    lvl = evt["entry"].get("level")
    print(f"  [{lvl:5s}] +{rel:4d}ms {svc}: {evt['entry'].get('message')}")

print("\n📊 Service rollup")
print("-" * 70)
by_service = {}
for evt in events:
    svc = evt["service"]
    by_service.setdefault(svc, []).append(evt)

for svc, svc_events in by_service.items():
    errors = sum(1 for e in svc_events if e["entry"].get("level") in ("ERROR", "FATAL"))
    warns = sum(1 for e in svc_events if e["entry"].get("level") == "WARN")
    span = (svc_events[-1]["relative_time_ms"] - svc_events[0]["relative_time_ms"]) if len(svc_events) > 1 else 0
    badge = "🔴" if errors else "🟡" if warns else "🟢"
    print(f"{badge} {svc:<18} {len(svc_events):2d} events | errors={errors}, warn={warns}, span={span}ms")

print("\nTakeaways:")
print("  • The inventory-service timeout is the first fault, everything downstream degrades.")
print("  • order-service shields the user with partial data, which propagates to api-gateway as 206.")
print("  • cross_service_timeline keeps the call tree coherent even from a single merged log file.")
