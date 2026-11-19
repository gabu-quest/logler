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
- **`timestamp_format`** is accepted as a key and is not applied: a timestamp is read in the
  shapes the parser knows.

A formats file that cannot be used stops the command instead of being skipped: broken
YAML, an unknown key or a regex that does not compile is exit code 2 with the file and
the problem. From the Python API it is `FormatFileError`, a `ValueError`.

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
