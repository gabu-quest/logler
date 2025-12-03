# Frontend Walkthrough (No Code to Run)

An opinionated click-through tour of the legacy FastAPI/Logler web UI. Use this when you want to visually inspect logs, verify service_name propagation, and exercise the backend without writing any Python.

## 1) Start the server

```bash
uv run logler serve --auto-port examples/logs/huge/massive_incident.log
```

- The server prints the chosen port (defaults around 7607). Open `http://localhost:<port>/`.
- You can also start with no files and pick them in the UI: `uv run logler serve --auto-port`.

## 2) Load the 10k incident log

1. In the UI, use the file picker to select `examples/logs/huge/massive_incident.log`.
2. Confirm the table shows 10,000 rows and a `service_name` column populated (api/search/ledger/auth/etc.).
3. Scroll or filter by `level = ERROR` to see database timeouts.

## 3) Follow a real correlation

1. Use the search/filter box to find `correlation_id = req-0001`.
2. Click one of the results and use the thread/follow view.
3. Verify the timeline shows entries from multiple services and a non-zero duration.

## 4) Pattern signals

1. Toggle the pattern/anomalies panel (if enabled) and run on the loaded file.
2. Expect repeated error patterns (connection timeouts, retry exhaustion) with examples that include `service_name`.

## 5) Glob/tail sanity check

1. Load multiple day-based logs via `/api/files/open_many` by pasting these paths into the multi-select:
   - `examples/logs/2025-11-01.log`
   - `examples/logs/2025-11-02.log`
   - `examples/logs/2025-11-03.log`
2. Verify the interleaved view shows the correct last lines:
   - Day 1 ends with `log line 199 on day 1` (service: api)
   - Day 2 ends with `log line 199 on day 2` (service: worker)
   - Day 3 ends with `log line 199 on day 3` (service: api)
3. Confirm the `service_name` column remains populated in the combined view.

## 6) Search latency gut check

1. Run a search for `Database timeout` with level `ERROR` on `massive_incident.log`.
2. Observe the UI response time; it should be well under a couple seconds on a dev laptop.

## 7) API endpoints (optional)

Hit these directly to inspect JSON shapes:

```bash
curl -s "http://localhost:<port>/api/files/open" \
  -H "Content-Type: application/json" \
  -d '{"path": "examples/logs/huge/massive_incident.log"}' | head

curl -s "http://localhost:<port>/api/files/open_many" \
  -H "Content-Type: application/json" \
  -d '{"paths": ["examples/logs/2025-11-01.log","examples/logs/2025-11-02.log","examples/logs/2025-11-03.log"]}' | head
```

Both responses should include `service_name` fields and interleaved entries when loading multiple files.

## Quick checklist

- [ ] Server starts and UI loads.
- [ ] 10k log shows 10,000 rows with `service_name`.
- [ ] `req-0001` timeline has entries, spans, and duration.
- [ ] Pattern detection returns results with example entries.
- [ ] Multi-file open shows correct last lines per day and keeps `service_name`.
- [ ] Search for “Database timeout” is fast and returns ERROR results. 
