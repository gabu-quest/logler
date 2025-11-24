"""
Advanced SQL Analysis for LLM Agents

This example demonstrates how LLM agents can use SQL queries to perform
sophisticated log analysis that goes beyond the built-in investigation tools.

Topics covered:
- Statistical anomaly detection
- Correlation analysis between errors
- Performance regression detection
- Request flow analysis
- Time-series patterns

These are the kinds of queries an LLM would write after initial investigation
to dig deeper into specific issues.
"""

from logler.investigate import Investigator
import json

LOG_FILE = "examples/logs/production_incident.log"

print("=" * 80)
print("ADVANCED SQL ANALYSIS FOR LLM AGENTS")
print("=" * 80)
print()

# Initialize investigator
investigator = Investigator()
investigator.load_files([LOG_FILE])

# Query 1: Statistical Anomaly Detection
print("📊 QUERY 1: Statistical Anomaly Detection")
print("-" * 80)
print("Finding time windows where error rate deviates significantly from baseline")
print()

try:
    anomalies = investigator.sql_query("""
        WITH error_per_second AS (
            SELECT
                strftime('%H:%M:%S', timestamp) as second,
                COUNT(CASE WHEN level IN ('ERROR', 'FATAL') THEN 1 END) as errors,
                COUNT(*) as total
            FROM logs
            GROUP BY second
        ),
        stats AS (
            SELECT
                AVG(errors * 1.0 / total) as mean_error_rate,
                AVG((errors * 1.0 / total) * (errors * 1.0 / total)) -
                    (AVG(errors * 1.0 / total) * AVG(errors * 1.0 / total)) as variance
            FROM error_per_second
        )
        SELECT
            eps.second,
            eps.errors,
            eps.total,
            ROUND(eps.errors * 100.0 / eps.total, 2) as error_rate,
            ROUND(s.mean_error_rate * 100, 2) as baseline_rate,
            ROUND(
                (eps.errors * 1.0 / eps.total - s.mean_error_rate) /
                SQRT(s.variance),
                2
            ) as z_score
        FROM error_per_second eps, stats s
        WHERE ABS(
            (eps.errors * 1.0 / eps.total - s.mean_error_rate) / SQRT(s.variance)
        ) > 2.0
        ORDER BY z_score DESC
    """)

    print("Anomalies detected (Z-score > 2.0):")
    for row in anomalies:
        print(f"  ⚠️  {row['second']}: {row['error_rate']}% error rate "
              f"(baseline: {row['baseline_rate']}%, Z-score: {row['z_score']})")
    print()
except Exception as e:
    print(f"SQL feature not available: {e}\n")

# Query 2: Error Correlation Matrix
print("📊 QUERY 2: Error Correlation Matrix")
print("-" * 80)
print("Finding which types of errors tend to occur together")
print()

try:
    correlations = investigator.sql_query("""
        WITH error_types AS (
            SELECT DISTINCT
                CASE
                    WHEN message LIKE '%timeout%' THEN 'timeout'
                    WHEN message LIKE '%connection%' THEN 'connection'
                    WHEN message LIKE '%pool%' THEN 'pool'
                    WHEN message LIKE '%query%' THEN 'query'
                    ELSE 'other'
                END as error_type
            FROM logs
            WHERE level IN ('ERROR', 'FATAL')
        )
        SELECT
            e1.error_type as error_a,
            e2.error_type as error_b,
            COUNT(DISTINCT l1.correlation_id) as co_occurrences
        FROM logs l1
        JOIN logs l2 ON l1.correlation_id = l2.correlation_id
        CROSS JOIN error_types e1
        CROSS JOIN error_types e2
        WHERE
            l1.level IN ('ERROR', 'FATAL') AND
            l2.level IN ('ERROR', 'FATAL') AND
            l1.message LIKE '%' || e1.error_type || '%' AND
            l2.message LIKE '%' || e2.error_type || '%' AND
            e1.error_type < e2.error_type AND
            l1.correlation_id IS NOT NULL
        GROUP BY e1.error_type, e2.error_type
        HAVING co_occurrences > 0
        ORDER BY co_occurrences DESC
    """)

    print("Error type correlations:")
    for row in correlations:
        print(f"  {row['error_a']} + {row['error_b']}: {row['co_occurrences']} requests")
    print()
except Exception as e:
    print(f"SQL feature not available: {e}\n")

# Query 3: Request Latency Percentiles
print("📊 QUERY 3: Request Latency Analysis")
print("-" * 80)
print("Calculating request duration percentiles")
print()

try:
    latencies = investigator.sql_query("""
        WITH request_durations AS (
            SELECT
                correlation_id,
                (julianday(MAX(timestamp)) - julianday(MIN(timestamp))) * 86400000 as duration_ms,
                MAX(CASE WHEN level IN ('ERROR', 'FATAL') THEN 1 ELSE 0 END) as had_error
            FROM logs
            WHERE correlation_id IS NOT NULL
            GROUP BY correlation_id
        ),
        percentiles AS (
            SELECT
                had_error,
                COUNT(*) as count,
                MIN(duration_ms) as min_duration,
                MAX(duration_ms) as max_duration,
                AVG(duration_ms) as avg_duration
            FROM request_durations
            GROUP BY had_error
        )
        SELECT
            CASE WHEN had_error = 1 THEN 'Failed' ELSE 'Successful' END as status,
            count,
            ROUND(min_duration, 2) as min_ms,
            ROUND(avg_duration, 2) as avg_ms,
            ROUND(max_duration, 2) as max_ms
        FROM percentiles
    """)

    print("Request duration statistics:")
    for row in latencies:
        print(f"  {row['status']:12s}: {row['count']} requests, "
              f"avg={row['avg_ms']}ms, min={row['min_ms']}ms, max={row['max_ms']}ms")
    print()
except Exception as e:
    print(f"SQL feature not available: {e}\n")

# Query 4: Thread Hotspots
print("📊 QUERY 4: Thread Hotspot Analysis")
print("-" * 80)
print("Identifying threads that are bottlenecks or error-prone")
print()

try:
    hotspots = investigator.sql_query("""
        WITH thread_stats AS (
            SELECT
                thread_id,
                COUNT(*) as total_logs,
                COUNT(CASE WHEN level IN ('ERROR', 'FATAL') THEN 1 END) as errors,
                COUNT(DISTINCT correlation_id) as unique_requests,
                MIN(timestamp) as first_log,
                MAX(timestamp) as last_log
            FROM logs
            WHERE thread_id IS NOT NULL
              AND thread_id NOT LIKE '%health%'
              AND thread_id NOT LIKE '%ops%'
            GROUP BY thread_id
        ),
        avg_stats AS (
            SELECT AVG(errors * 1.0 / total_logs) as avg_error_rate
            FROM thread_stats
        )
        SELECT
            ts.thread_id,
            ts.total_logs,
            ts.errors,
            ts.unique_requests,
            ROUND(ts.errors * 100.0 / ts.total_logs, 1) as error_rate,
            ROUND((julianday(ts.last_log) - julianday(ts.first_log)) * 86400, 2) as active_seconds,
            CASE
                WHEN ts.errors * 1.0 / ts.total_logs > avg.avg_error_rate * 2 THEN 'HIGH'
                WHEN ts.errors * 1.0 / ts.total_logs > avg.avg_error_rate THEN 'MEDIUM'
                ELSE 'LOW'
            END as risk_level
        FROM thread_stats ts, avg_stats avg
        WHERE ts.errors > 0
        ORDER BY ts.errors DESC
    """)

    print("Thread hotspots:")
    for row in hotspots:
        risk_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(row['risk_level'], "⚪")
        print(f"  {risk_emoji} {row['thread_id']:12s}: {row['errors']} errors "
              f"({row['error_rate']}% rate), {row['unique_requests']} requests, "
              f"active {row['active_seconds']}s")
    print()
except Exception as e:
    print(f"SQL feature not available: {e}\n")

# Query 5: Cascading Failure Detection
print("📊 QUERY 5: Cascading Failure Pattern Detection")
print("-" * 80)
print("Finding sequences of errors that propagate across threads")
print()

try:
    cascades = investigator.sql_query("""
        WITH error_sequence AS (
            SELECT
                timestamp,
                thread_id,
                message,
                LAG(timestamp) OVER (ORDER BY timestamp) as prev_timestamp,
                LAG(thread_id) OVER (ORDER BY timestamp) as prev_thread
            FROM logs
            WHERE level IN ('ERROR', 'FATAL')
        ),
        cascades AS (
            SELECT
                prev_thread,
                thread_id,
                COUNT(*) as cascade_count,
                MIN(timestamp) as first_cascade,
                (julianday(MAX(timestamp)) - julianday(MIN(prev_timestamp))) * 1000 as spread_time_ms
            FROM error_sequence
            WHERE prev_thread IS NOT NULL
              AND thread_id != prev_thread
              AND (julianday(timestamp) - julianday(prev_timestamp)) * 1000 < 1000
            GROUP BY prev_thread, thread_id
            HAVING cascade_count > 1
        )
        SELECT *
        FROM cascades
        ORDER BY cascade_count DESC
    """)

    print("Cascading failure patterns:")
    for row in cascades:
        print(f"  ⛓️  {row['prev_thread']} → {row['thread_id']}: "
              f"{row['cascade_count']} cascades in {row['spread_time_ms']:.0f}ms")
    print()
except Exception as e:
    print(f"SQL feature not available: {e}\n")

# Query 6: Recovery Time Analysis
print("📊 QUERY 6: Recovery Time Analysis")
print("-" * 80)
print("Measuring how long it took the system to recover")
print()

try:
    recovery = investigator.sql_query("""
        WITH incident_bounds AS (
            SELECT
                MIN(timestamp) as incident_start,
                MAX(CASE WHEN level IN ('ERROR', 'FATAL') THEN timestamp END) as last_error,
                MAX(timestamp) as logs_end
            FROM logs
        ),
        recovery_logs AS (
            SELECT
                timestamp,
                message,
                level
            FROM logs
            WHERE message LIKE '%recover%' OR message LIKE '%resolved%' OR message LIKE '%health%'
            ORDER BY timestamp
        )
        SELECT
            (julianday(ib.last_error) - julianday(ib.incident_start)) * 86400 as incident_duration_s,
            rl.timestamp as recovery_timestamp,
            (julianday(rl.timestamp) - julianday(ib.last_error)) * 1000 as recovery_time_ms,
            rl.message as recovery_action
        FROM incident_bounds ib, recovery_logs rl
        WHERE rl.timestamp > ib.last_error
        ORDER BY rl.timestamp
        LIMIT 5
    """)

    print("Recovery timeline:")
    for row in recovery:
        print(f"  ✅ +{row['recovery_time_ms']:.0f}ms: {row['recovery_action'][:60]}")
    print()
    print(f"Total incident duration: {recovery[0]['incident_duration_s']:.1f} seconds")
    print()
except Exception as e:
    print(f"SQL feature not available: {e}\n")

# Summary
print("=" * 80)
print("📋 ADVANCED ANALYSIS SUMMARY")
print("=" * 80)
print()
print("These SQL queries demonstrate how LLM agents can:")
print("  1. Detect statistical anomalies using Z-scores")
print("  2. Find correlations between different error types")
print("  3. Analyze request latency distributions")
print("  4. Identify thread hotspots and bottlenecks")
print("  5. Detect cascading failure patterns")
print("  6. Measure recovery times")
print()
print("💡 This level of analysis would be difficult with just grep/awk!")
print("   SQL + Rust speed = powerful investigation for LLMs")
print()
print("=" * 80)
