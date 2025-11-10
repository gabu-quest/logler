# Example log files for testing

## JSON logs
Create a file `sample-json.log`:
```json
{"timestamp": "2024-01-15T10:00:00Z", "level": "INFO", "message": "Application started", "thread_id": "main", "service": "api"}
{"timestamp": "2024-01-15T10:00:01Z", "level": "DEBUG", "message": "Database connection established", "thread_id": "worker-1", "correlation_id": "req-001"}
{"timestamp": "2024-01-15T10:00:02Z", "level": "INFO", "message": "Handling request", "thread_id": "worker-1", "correlation_id": "req-001", "trace_id": "abc123", "span_id": "span-001"}
{"timestamp": "2024-01-15T10:00:03Z", "level": "ERROR", "message": "Database query timeout", "thread_id": "worker-1", "correlation_id": "req-001", "trace_id": "abc123", "span_id": "span-002"}
{"timestamp": "2024-01-15T10:00:04Z", "level": "WARN", "message": "Retrying connection", "thread_id": "worker-2"}
```

## Plain text logs
Create a file `sample-plain.log`:
```
2024-01-15 10:00:00 INFO [main] Application started
2024-01-15 10:00:01 DEBUG [worker-1] [req-001] Processing request
2024-01-15 10:00:02 ERROR [worker-1] [req-001] Connection failed
2024-01-15 10:00:03 WARN [worker-2] Retry attempt 1/3
```

## Using the samples
```bash
# CLI
logler view examples/sample-json.log
logler view examples/sample-plain.log --level ERROR

# Web UI
1. Start logler: ./start.sh
2. Open http://localhost:8000
3. Enter path: /path/to/sample-json.log
4. Click "Open File"
```
