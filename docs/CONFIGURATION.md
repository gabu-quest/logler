# Configuration

logler reads two optional YAML files from a `.logler/` folder: one for log formats of your
own, one for rules that link entries across files. Without them every command works on the
formats logler detects itself.

## Custom formats: `.logler/formats.yaml`

A format is a regex with named groups and the file names it applies to.

```yaml
formats:
  my-app:
    regex: '(?P<timestamp>\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s+(?P<level>\w+)\s+\[(?P<thread_id>[\w-]+)\]\s+(?P<station>\w+)\s+(?P<message>.*)'
    file_patterns: ["my-app*.log"]
```

With that file, the line

```
2026-11-14T10:00:00.000Z ERROR [worker-7] press4 Hydraulic pressure low
```

in `my-app-1.log` is read as:

```json
{
  "line_number": 1,
  "timestamp": "2026-11-14T10:00:00Z",
  "level": "ERROR",
  "format": "Custom",
  "message": "Hydraulic pressure low",
  "thread_id": "worker-7",
  "fields": {"station": "press4"}
}
```

- **Which file applies.** For each log file, logler walks up from that file's own folder
  and uses the first `.logler/formats.yaml` it finds.
- **Which format applies.** The first format whose `file_patterns` match the file's name
  (shell wildcards such as `*.log`). A file no pattern matches is read with the built-in
  detection.
- **Where it applies.** In every command and every API call that reads the file.
- **Groups.** A group named after one of an entry's own fields (`timestamp`, `level`,
  `message`, `thread_id`, and the other ids) fills that field. Any other named group is
  kept under `fields`. The regex needs at least one named group.
- **`timestamp_format`** (optional) says how the `timestamp` group is written, in Python's
  `strptime` words (below). Without it, or when a group's text does not fit it, the group is
  read in the shapes logler knows (`docs/TIMESTAMPS.md`). An empty string is no format.

### `timestamp_format`

```yaml
formats:
  plc:
    regex: '^(?P<timestamp>\S+ \S+) (?P<level>\w+) (?P<message>.*)$'
    timestamp_format: "%d.%m.%Y %H:%M:%S"
    file_patterns: ["plc_*.log"]
```

reads `31.12.2024 23:59:58 INFO year end` as `2024-12-31T23:59:58Z`. The text is read as
Python's `datetime.strptime(text, timestamp_format)` reads it:

| Word | Reads |
|---|---|
| `%Y` | a year of four digits |
| `%y` | a year of two digits: `69` to `99` are 1969 to 1999, `00` to `68` are 2000 to 2068 |
| `%m` | a month, `1` to `12`, with or without a leading zero |
| `%b`, `%B` | a month name in English, short (`Oct`) or full (`October`), in any letter case |
| `%d` | a day, `1` to `31`, with or without a leading zero or a leading space |
| `%H`, `%M`, `%S` | hour (`0` to `23`), minute and second, with or without a leading zero |
| `%f` | one to six digits, read as a fraction of a second: `,123` is 123 ms |
| `%z` | an offset, `+0900` or `+09:00` (seconds may follow, `+09:00:30`), or `Z` for UTC |
| `%%` | a `%` |

- A format needs a date: a year, a month and a day. A time is optional (midnight).
- A time without `%z` is UTC, as everywhere in logler.
- The format must describe the whole group: text left over, a seventh digit of `%f`, or a
  date that does not exist (31 February) is no fit, and the group is read in the known
  shapes instead.
- White space in the format matches any run of white space; letters match in any case.
- Two things differ from Python, as for every timestamp logler reads: a second `60` is a
  leap second (`23:59:60`), and only ASCII digits are digits.
- Two more differ for `%z`: an offset writes its colons throughout or not at all
  (`+09:00:30` or `+090030`, not `+09:0030`), and it holds no fraction of a second. A
  timestamp with such an offset does not fit the format.

A word not in the table stops the formats file, with the format's name and the word:
`%Z` (a zone name means different offsets on different machines; write the offset and read
it with `%z`), the words read in the machine's language (`%a`, `%A`, `%c`, `%x`, `%X`, `%p`),
and every other word (`%I`, `%j`, ...). So does a format with no date, a part given by two
words (`%m` and `%b`), or a `%` at the end.

A formats file that cannot be used stops the command instead of being skipped: broken
YAML, an unknown key, a regex that does not compile or a `timestamp_format` that cannot be
read is exit code 2 with the file and the problem. From the Python API it is `FormatFileError`, a `ValueError`.

Commands for working on a format:

```bash
logler llm format list                                  # built-in formats and the ones in your file
logler llm format test -f my-app-1.log --name my-app    # which lines match, and the groups
logler llm format validate                              # check the formats file
```

These three look for the formats file from the current folder, or from `--config-dir`.

## Correlation rules: `.logler/correlations.yaml`

A group of rules that link entries from different files.

```yaml
correlations:
  batch-tracking:
    description: Follow one batch from the MES log into the PLC log
    rules:
      - type: field_match
        source: {file_pattern: "mes_*.log", field: batch_id}
        target: {file_pattern: "plc_*.log", field: batch_id}
      - type: temporal
        anchor: {level: ERROR}
        window: 5s
```

- **`field_match`** links entries whose `source` and `target` fields hold the same value.
- **`temporal`** collects the entries within `window` of an anchor event. The anchor is
  given by `level`, by `pattern` (a regex on the message), or by `field` with `condition`
  (for example `condition: "< 2.0"`). A window is written `500ms`, `5s`, `1m` or `2h`.

The file is found by walking up from the current folder, or from `--config-dir`.

```bash
logler llm correlation list                                   # the groups in your file
logler llm correlation run -f "mes_*.log" -f "plc_*.log" --rule batch-tracking
```
