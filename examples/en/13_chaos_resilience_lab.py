"""
Chaos Resilience Lab - multi-service meltdown vs. happy path vs. flaky retry

This example stress-tests Logler's cross-cutting investigation tools on a
diabolical payment incident with circuit breakers, fallback heuristics, and
mixed outcomes.
"""

import logler.investigate as investigate
from logler.investigate import Investigator

FILES = ["examples/logs/chaos_fest.log"]
BAD = "req-chaos-001"
GOOD = "req-happy-777"
FLAKY = "req-flaky-009"

print("=" * 80)
print("CHAOS RESILIENCE LAB")
print("=" * 80)
print()

# Step 1: Metadata + shape of the data
meta = investigate.get_metadata(FILES)[0]
print("📦 Data shape")
print("-" * 80)
print(f"File: {meta['path']}")
print(f"Lines: {meta['lines']}")
print(f"Levels: {meta['log_levels']}")
print(f"Threads: {meta['unique_threads']}, Correlations: {meta['unique_correlation_ids']}")
print()

# Step 2: Radar for severe events
errors = investigate.search(FILES, level="ERROR", limit=20)
print("🚨 Error radar")
print("-" * 80)
print(f"Total ERROR/FATAL: {errors['total_matches']}")
for hit in errors["results"][:5]:
    entry = hit["entry"]
    svc = entry.get("service_name") or entry["fields"].get("service") or "unknown"
    print(f"[{entry['timestamp']}] {svc}: {entry['message']}")
print()

# Step 3: Pattern mining (what's repeating)
patterns = investigate.find_patterns(FILES, min_occurrences=2)
print("🧭 Repeating patterns")
print("-" * 80)
for i, pattern in enumerate(patterns.get("patterns", []), 1):
    print(f"{i}. {pattern['pattern']} x{pattern['occurrences']} (first {pattern['first_seen']})")
print()

# Step 4: Head-to-head: failed vs. happy request
diff = investigate.compare_threads(
    FILES,
    correlation_a=BAD,
    correlation_b=GOOD,
)
print("⚔️  Failed vs. happy comparison")
print("-" * 80)
print(diff["summary"])
print("Levels delta:", diff["differences"]["level_changes"])
print("Only in failure:", diff["differences"]["only_in_b"][:3])
print()

# Step 5: Flaky vs. failed (did retries help?)
flaky = investigate.compare_threads(
    FILES,
    correlation_a=BAD,
    correlation_b=FLAKY,
)
print("🔁 Flaky retry vs. meltdown")
print("-" * 80)
print(flaky["summary"])
print("Only in flaky:", flaky["differences"]["only_in_b"][:3])
print()

# Step 6: Timeline of the meltdown with per-service impact
timeline = investigate.follow_thread(FILES, correlation_id=BAD)
service_counts = {}
for e in timeline["entries"]:
    svc = e.get("service_name") or e["fields"].get("service") or "unknown"
    service_counts[svc] = service_counts.get(svc, 0) + 1

print("🕐 Meltdown timeline")
print("-" * 80)
print(f"Duration: {timeline['duration_ms']}ms, entries: {timeline['total_entries']}")
print("Service hit count:", service_counts)
for e in timeline["entries"]:
    svc = e.get("service_name") or e["fields"].get("service") or "unknown"
    print(f"  [{e['timestamp']}] {svc:17s} {e['level']:5s} {e['message']}")
print()

# Step 7: SQL resilience dashboard
inv = Investigator()
inv.load_files(FILES)
print("📊 SQL resilience dashboard")
print("-" * 80)
durations = inv.sql_query(
    """
    SELECT
        correlation_id,
        COUNT(*) as total_logs,
        COUNT(CASE WHEN level IN ('ERROR','FATAL') THEN 1 END) as errors,
        DATEDIFF('millisecond', MIN(timestamp), MAX(timestamp)) as duration_ms
    FROM logs
    GROUP BY correlation_id
    ORDER BY errors DESC
    """
)
for row in durations:
    print(f"{row['correlation_id']}: {row['errors']} errors / {row['total_logs']} logs, {row['duration_ms']}ms window")
print()

circuits = inv.sql_query(
    """
    SELECT
        correlation_id,
        message
    FROM logs
    WHERE message LIKE '%circuit%'
    """
)
if circuits:
    print("Circuit events:")
    for row in circuits:
        print(f"  {row['correlation_id']}: {row['message']}")
print()

print("=" * 80)
print("Chaos lab complete. Use this to harden retries, gateways, and circuit breakers.")
print("=" * 80)
