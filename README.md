# logler

Cool local log viewing tool with syntax highlighting, filtering, and real-time following.

## Features

- **Smart Format Detection**: Automatically detects and parses multiple log formats:
  - Plain text logs with timestamps and levels
  - JSON structured logs
  - Syslog format
  - Apache Common Log Format

- **Syntax Highlighting**: Color-coded output for better readability:
  - Timestamps in cyan
  - Log levels with appropriate colors (INFO=green, WARN=yellow, ERROR=red, etc.)
  - JSON fields highlighted

- **Powerful Filtering**:
  - Search by text pattern (case-sensitive or insensitive)
  - Filter by log level (DEBUG, INFO, WARN, ERROR, CRITICAL)
  - Regex pattern matching

- **Real-time Following**: Like `tail -f` for watching logs in real-time

- **Efficient**: Handles large log files efficiently with chunked reading and reverse iteration

- **Flexible Display**:
  - Show last N lines
  - Show first N lines
  - Reverse order
  - Line-numbered output for search results

## Installation

### From source

```bash
git clone https://github.com/yourusername/logler.git
cd logler
pip install -e .
```

### With pip (after publishing)

```bash
pip install logler
```

## Usage

### Basic Usage

View a log file:
```bash
logler app.log
```

### Display Options

Show last 100 lines:
```bash
logler app.log -n 100
```

Show first 50 lines:
```bash
logler app.log --head 50
```

Follow log in real-time (like `tail -f`):
```bash
logler app.log -f
```

Show in reverse order:
```bash
logler app.log --reverse
```

Disable colored output:
```bash
logler app.log --no-color
```

Force specific format parsing:
```bash
logler app.log --format json
```

### Filtering and Searching

Search for a pattern (case-insensitive):
```bash
logler app.log -s "exception"
logler app.log --grep "error occurred"
```

Case-sensitive search:
```bash
logler app.log -s "Exception" -i
```

Regex search:
```bash
logler app.log -s "error|exception|failed" -r
```

Filter by log level:
```bash
logler app.log --level ERROR
logler app.log --level WARN
```

Combine filters:
```bash
logler app.log --level ERROR --grep "database"
```

### File Information

Show file metadata:
```bash
logler app.log --info
```

Count total lines:
```bash
logler app.log --count
```

### Advanced Examples

Follow logs, showing only ERROR level with last 20 lines:
```bash
logler app.log -f -n 20 --level ERROR
```

Search for pattern in last 1000 lines:
```bash
logler app.log -n 1000 -s "timeout"
```

## Log Format Support

### Plain Text Logs

Automatically highlights timestamps and log levels:
```
2024-01-01 12:00:00 INFO Application started
2024-01-01 12:00:01 DEBUG Loading configuration
2024-01-01 12:00:02 ERROR Database connection failed
```

### JSON Logs

Parses and formats JSON logs nicely:
```json
{"timestamp": "2024-01-01T12:00:00Z", "level": "INFO", "message": "User logged in", "user_id": 123}
```

### Syslog

Handles syslog format:
```
<134>Jan 1 12:00:00 hostname app: This is a syslog message
```

### Apache Common Log

Parses Apache/Nginx access logs:
```
192.168.1.1 - - [01/Jan/2024:12:00:00 +0000] "GET /index.html HTTP/1.1" 200 1234
```

## Development

### Setup Development Environment

```bash
git clone https://github.com/yourusername/logler.git
cd logler
pip install -e ".[dev]"
```

### Run Tests

```bash
pytest
```

Run tests with coverage:
```bash
pytest --cov=logler --cov-report=html
```

### Project Structure

```
logler/
├── src/
│   └── logler/
│       ├── __init__.py
│       ├── cli.py           # Command-line interface
│       ├── log_parser.py    # Log parsing and formatting
│       └── log_reader.py    # File reading and streaming
├── tests/
│   ├── test_log_parser.py
│   └── test_log_reader.py
├── pyproject.toml
├── README.md
└── LICENSE
```

## Requirements

- Python 3.8 or higher
- No external dependencies for core functionality
- pytest for running tests (development only)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

See LICENSE file for details.

## Examples Gallery

### Viewing application logs
```bash
$ logler app.log -n 20
2024-01-01 10:00:00 INFO Server started on port 8080
2024-01-01 10:00:01 INFO Database connection established
2024-01-01 10:00:05 DEBUG Incoming request: GET /api/users
2024-01-01 10:00:06 ERROR Failed to authenticate user: token expired
2024-01-01 10:00:07 WARN Retry attempt 1/3
```

### Following logs in real-time
```bash
$ logler app.log -f --level ERROR
2024-01-01 10:15:23 ERROR Database query timeout
2024-01-01 10:15:45 ERROR Connection pool exhausted
# ... continues to show new ERROR entries as they appear
```

### Searching for specific issues
```bash
$ logler app.log -s "timeout" -r
125: 2024-01-01 08:30:15 ERROR Connection timeout after 30s
342: 2024-01-01 09:45:22 WARN Request timeout, retrying...
891: 2024-01-01 10:15:23 ERROR Database query timeout
```

## Tips

1. **Performance**: For very large files, use `-n` or `--head` to limit output
2. **Piping**: Can be combined with other tools: `logler app.log -n 100 | grep -v DEBUG`
3. **Multiple files**: Use shell wildcards: `for f in logs/*.log; do logler "$f" --level ERROR; done`
4. **Colors in pipes**: Colors are auto-disabled when piping, or use `--no-color` explicitly
