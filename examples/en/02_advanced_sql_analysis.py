"""
Advanced SQL Analysis for LLM Agents

A sharper, story-driven SQL playbook for the production incident log.
Each query answers a specific investigation question an LLM would ask
after the first triage pass.
"""

from logler.investigate import Investigator

LOG_FILE = "examples/logs/production_incident.log"

print("=" * 80)
print("ADVANCED SQL ANALYSIS PLAYBOOK")
print("=" * 80)

investigator = Investigator()
investigator.load_files([LOG_FILE])


def section(title: str):
    print("\n" + title)
    print("-" * len(title))


def run_sql(title: str, query: str, render=None):
    section(title)
    try:
        rows = investigator.sql_query(query)
    except Exception as exc:  # pragma: no cover - demo only
        print(f"SQL feature not available: {exc}\n")
        return

    if not rows:
        print("No rows returned\n")
        return

    if render:
        render(rows)
    else:
        for row in rows:
            print(row)
    print()


meta = investigator.get_metadata()[0]
section("📡 Context")
print(f"File: {meta['path']}")
print(f"Lines: {meta['lines']}")
print(f"Levels: {meta['log_levels']}")
print(f"Window: {meta['time_range']['start']} → {meta['time_range']['end']}")


def render_spike(rows):
    for r in rows:
        print(f"  ⚠️  {r['second']}: {r['error_rate_pct']}% errors (z={r['z_score']})")


run_sql(
    "📈 Where did the spike happen? (z-score over seconds)",
    """
    WITH per_second AS (
        SELECT
            strftime('%H:%M:%S', timestamp) AS second,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE level IN ('ERROR','FATAL','CRITICAL')) AS errors
        FROM logs
        GROUP BY 1
    )
    SELECT
        second,
        total,
        errors,
        ROUND(errors * 100.0 / NULLIF(total, 0), 2) AS error_rate_pct,
        ROUND(
            (errors * 1.0 / NULLIF(total, 1) - AVG(errors * 1.0 / NULLIF(total, 1)) OVER ()) /
            NULLIF(stddev_pop(errors * 1.0 / NULLIF(total, 1)) OVER (), 0),
            2
        ) AS z_score
    FROM per_second
    ORDER BY error_rate_pct DESC
    LIMIT 5;
    """,
    render=render_spike,
)


def render_signatures(rows):
    for r in rows:
        print(
            f"  {r['signature']:<18} {r['occurrences']:2d} hits ({r['first_seen']} → {r['last_seen']})"
        )


run_sql(
    "🧭 What signatures dominate the outage?",
    """
    SELECT
        CASE
            WHEN message ILIKE '%connection timeout%' THEN 'connection timeout'
            WHEN message ILIKE '%pool%' THEN 'pool saturation'
            WHEN message ILIKE '%slow query%' THEN 'slow queries'
            WHEN message ILIKE '%rollback%' THEN 'rollbacks'
            ELSE 'other'
        END AS signature,
        COUNT(*) AS occurrences,
        MIN(timestamp) AS first_seen,
        MAX(timestamp) AS last_seen
    FROM logs
    WHERE level IN ('ERROR','FATAL','CRITICAL','WARN')
    GROUP BY 1
    ORDER BY occurrences DESC;
    """,
    render=render_signatures,
)


def render_requests(rows):
    for r in rows:
        print(
            f"  {r['correlation_id']}: {r['errors']} errors over {r['duration_ms']}ms ({r['total']} log lines)"
        )


run_sql(
    "⏱️  Which requests suffered the most?",
    """
    WITH per_request AS (
        SELECT
            correlation_id,
            MIN(timestamp) AS start_ts,
            MAX(timestamp) AS end_ts,
            DATEDIFF('millisecond', MIN(timestamp), MAX(timestamp)) AS duration_ms,
            SUM(CASE WHEN level IN ('ERROR','FATAL','CRITICAL') THEN 1 ELSE 0 END) AS errors,
            COUNT(*) AS total
        FROM logs
        WHERE correlation_id IS NOT NULL
        GROUP BY correlation_id
    )
    SELECT
        correlation_id,
        errors,
        total,
        duration_ms
    FROM per_request
    WHERE errors > 0
    ORDER BY errors DESC, duration_ms DESC
    LIMIT 5;
    """,
    render=render_requests,
)


def render_retries(rows):
    for r in rows:
        print(
            f"  {r['thread_id']}: {r['retry_logs']} retries ({r['first_retry']} → {r['last_retry']})"
        )


run_sql(
    "🔄 Who was thrashing retries?",
    """
    SELECT
        thread_id,
        COUNT(*) AS retry_logs,
        MIN(timestamp) AS first_retry,
        MAX(timestamp) AS last_retry
    FROM logs
    WHERE message ILIKE 'Retrying database connection%'
    GROUP BY thread_id
    ORDER BY retry_logs DESC;
    """,
    render=render_retries,
)


def render_ops(rows):
    for r in rows:
        print(f"  {r['ts']} | {r['message']}")
    print(f"\n  ⏳ Full incident length: {rows[0]['resolution_ms']} ms")


run_sql(
    "🛠️  Did the ops response close the incident fast enough?",
    """
    WITH bounds AS (
        SELECT
            MIN(CASE WHEN message ILIKE '%Incident detected%' THEN timestamp END) AS detected_at,
            MAX(CASE WHEN message ILIKE '%Incident resolved%' THEN timestamp END) AS resolved_at
        FROM logs
    ),
    actions AS (
        SELECT
            message,
            strftime('%H:%M:%S.%f', timestamp) AS ts
        FROM logs
        WHERE message ILIKE '%Incident%' OR message ILIKE 'Scaling database connection pool%'
           OR message ILIKE 'Restarting slow query killer%' OR message ILIKE 'Killing slow queries%'
        ORDER BY timestamp
    )
    SELECT
        message,
        ts,
        (SELECT DATEDIFF('millisecond', detected_at, resolved_at) FROM bounds) AS resolution_ms
    FROM actions;
    """,
    render=render_ops,
)

print("Done. Use these query shapes as building blocks for your own LLM prompts.")
print("=" * 80)
