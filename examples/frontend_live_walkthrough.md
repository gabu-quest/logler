# Frontend Live Follow Walkthrough

This walkthrough pairs a live log generator with the web UI’s auto-scroll/tail. No Python knowledge required beyond running the helper script.

## 0) Start the live log writer

In one terminal:

```bash
uv run python examples/en/live_log_stream.py
```

This continuously appends JSON log lines to `examples/logs/live_follow_demo.log` (rotating metrics, services, correlation IDs). Leave it running.

## 1) Launch the UI on the live file

In a second terminal:

```bash
uv run logler serve --auto-port examples/logs/live_follow_demo.log
```

Open the printed URL (defaults near port 7607).

## 2) Follow in the browser

1. Verify the table shows new rows every ~150ms.
2. Enable follow/tail/auto-scroll so the viewport sticks to the newest entries.
3. Filter by `level = ERROR` to watch intermittent timeouts.
4. Filter by `correlation_id = live-0000` to see one request’s evolving timeline.

## 3) Stress it a bit

- Keep the writer running, apply multiple filters (level + service + correlation) and confirm updates keep flowing.
- Clear filters; the table should continue auto-updating without a reload.
- Check that `service_name` and `correlation_id` columns stay populated.

## 4) Clean up

Ctrl+C the writer and the server. Remove the demo log if you want:

```bash
rm examples/logs/live_follow_demo.log
```
