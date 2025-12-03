"""
Distributed Tracing Across Microservices

A richer walkthrough that turns one trace into a story: who failed first,
how the failure propagated, and how much time each service spent on the request.
"""

from datetime import datetime
import logler.investigate as investigate

LOG_FILE = "examples/logs/microservices_trace.log"
TRACE_ID = "trace-001"
CORRELATION_ID = "req-abc123"

print("=" * 80)
print("DISTRIBUTED TRACING INVESTIGATION")
print("=" * 80)

meta = investigate.get_metadata([LOG_FILE])[0]
print(f"File: {meta['path']}")
print(f"Lines: {meta['lines']}, Time window: {meta['time_range']['start']} → {meta['time_range']['end']}")
print(f"Correlation IDs: {meta['unique_correlation_ids']}")

timeline = investigate.follow_thread(files=[LOG_FILE], correlation_id=CORRELATION_ID, trace_id=TRACE_ID)
entries = timeline["entries"]

if not entries:
    raise SystemExit("No entries found for the requested trace/correlation.")

def as_dt(ts: str | None):
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def service_name(entry: dict) -> str:
    return (
        entry.get("service_name")
        or entry.get("service")
        or entry.get("fields", {}).get("service")
        or "unknown"
    )


start_ts = as_dt(entries[0].get("timestamp"))

def rel_ms(entry: dict) -> int | None:
    ts = as_dt(entry.get("timestamp"))
    if not ts or not start_ts:
        return None
    return int((ts - start_ts).total_seconds() * 1000)


print("\n📜 Waterfall")
print("-" * 80)
print(f"Duration: {timeline['duration_ms']} ms | Entries: {timeline['total_entries']} | Spans: {len(timeline['unique_spans'])}")
print(f"{'t+ms':>8}  {'service':<18} {'lvl':<6} message")
print("-" * 80)

for entry in entries:
    rel = rel_ms(entry)
    svc = service_name(entry)
    lvl = entry.get("level", "INFO")
    msg = (entry.get("message") or "")[:72]
    marker = { "ERROR": "❌", "FATAL": "💀", "WARN": "⚠️" }.get(lvl, "·")
    rel_display = f"{rel:>6}ms" if rel is not None else "  ?"
    print(f"{rel_display:>8}  {svc:<18} {lvl:<6} {marker} {msg}")


print("\n🏥 Service scorecard")
print("-" * 80)
scorecard = {}
for entry in entries:
    svc = service_name(entry)
    svc_stats = scorecard.setdefault(
        svc,
        {"errors": 0, "warns": 0, "infos": 0, "first": None, "last": None, "count": 0},
    )
    lvl = entry.get("level")
    if lvl in ("ERROR", "FATAL", "CRITICAL"):
        svc_stats["errors"] += 1
    elif lvl == "WARN":
        svc_stats["warns"] += 1
    else:
        svc_stats["infos"] += 1
    ts = as_dt(entry.get("timestamp"))
    svc_stats["first"] = svc_stats["first"] or ts
    svc_stats["last"] = ts or svc_stats["last"]
    svc_stats["count"] += 1

for svc, stats in sorted(scorecard.items(), key=lambda kv: (-kv[1]["errors"], -kv[1]["warns"])):
    span_ms = (
        int((stats["last"] - stats["first"]).total_seconds() * 1000)
        if stats["first"] and stats["last"]
        else 0
    )
    badge = "🔴" if stats["errors"] else "🟡" if stats["warns"] else "🟢"
    print(
        f"{badge} {svc:<18} {stats['count']:2d} logs | "
        f"errors={stats['errors']}, warn={stats['warns']}, span={span_ms}ms"
    )


print("\n🎯 Root cause & propagation")
print("-" * 80)
failures = [e for e in entries if e.get("level") in ("ERROR", "FATAL", "CRITICAL")]
if failures:
    first_fail = failures[0]
    print(f"First failure: {first_fail['timestamp']} in {service_name(first_fail)} → {first_fail['message']}")
    downstream = failures[1:]
    if downstream:
        print("Downstream ripples:")
        for entry in downstream:
            print(f"  → {service_name(entry)} at {entry['timestamp']}: {entry['message']}")
else:
    print("No ERROR/FATAL entries found.")


print("\n⚠️  Degraded response markers")
print("-" * 80)
degraded = [
    e for e in entries
    if "degraded" in (e.get("message", "").lower())
    or "partial" in (e.get("message", "").lower())
    or str(e.get("fields", {}).get("status_code", "")) == "206"
]
if degraded:
    for entry in degraded:
        print(f"  {service_name(entry)} → {entry['message']}")
else:
    print("No degraded markers in this trace.")


print("\n⏱️  Latency breakdown by service")
print("-" * 80)
total_ms = timeline["duration_ms"] or 0
for svc, stats in scorecard.items():
    if stats["first"] and stats["last"]:
        span_ms = int((stats["last"] - stats["first"]).total_seconds() * 1000)
        pct = (span_ms / total_ms * 100) if total_ms else 0
        bar = "█" * max(1, int(pct / 5)) if span_ms else ""
        print(f"  {svc:<18}: {span_ms:4d} ms ({pct:4.1f}%) {bar}")

print("\nStory complete: the request went degraded after inventory-service timed out,")
print("propagated as partial content through order-service → user-service → api-gateway.")

# Summary
print("=" * 80)
print("📋 DISTRIBUTED TRACE SUMMARY")
print("=" * 80)
print()
print("🔍 Trace Details:")
print(f"   Correlation ID: {CORRELATION_ID}")
print(f"   Trace ID: {TRACE_ID}")
print(f"   Total Duration: {timeline['duration_ms']}ms")
print(f"   Services Involved: {len(scorecard)}")
print()
print("🌐 Service Call Chain:")
print("   API Gateway → User Service → Order Service → Inventory Service")
print()
print("🔥 Root Cause:")
print("   Inventory Service database connection pool exhaustion")
print("   3 retry attempts failed over 50ms")
print()
print("📊 Impact:")
print("   - Request returned 206 Partial Content (degraded)")
print(f"   - {len(failures)} errors across services")
print("   - Inventory data unavailable for user")
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
