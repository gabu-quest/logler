# How logler reads the time of a line

logler reads one time per log line, without configuration. This page says which spellings
it understands and how it decides the time zone.

## Where the time is taken from

| Line | The time is |
|---|---|
| JSON | The first of the keys `timestamp`, `time`, `@timestamp`, `ts`, `datetime` that holds a readable value: a string in the shape below, or a number (see "Numbers") |
| logfmt | The same keys; failing those, a timestamp at the start of the line |
| Plain text, syslog | The first timestamp in the shape below, anywhere in the line, inside `[...]` included |
| Apache common log format | The bracketed time, `[15/Jan/2024:10:00:00 +0000]` |

A line with no readable time has no timestamp. That includes a syslog line that writes its
time without a year (`Jan 15 10:00:00`).

## The shape

```
2024-01-15T10:00:00            a "T" or one space between date and time
2024-01-15 10:00:00.123        a fraction after "." or ","
2024-01-15 10:00:00,123456
2024-01-15T10:00:00Z           a zone (next section)
```

The date is always year, month, day with dashes. Up to nine digits of the fraction are kept.

## The time zone

| Written | Read as |
|---|---|
| No zone | UTC |
| `Z` right after the seconds | UTC |
| `+09:00` or `+0900` right after the seconds | That offset |
| `+0900` or `+09:00` one space after the seconds | That offset, when it is a real one (below) |

Not read as a zone: a short offset (`+09`, `+9:00`) and a zone name (`JST`, `EST`).

### An offset after a space

Some loggers put a space before the offset: `2024-01-15 10:00:00 +0900 INFO started`.
logler takes the number as the zone when all of these hold:

- exactly one space, then `+` or `-`, then four digits, with or without a colon;
- the hours are 00 to 14 and the minutes are 00, 15, 30 or 45;
- a space, a `]` or the end of the line follows.

| Line | Time read (UTC) |
|---|---|
| `2024-01-15 10:00:00 +0900 INFO started` | 01:00 |
| `[2024-01-15 10:00:00 +0900] warn started` | 01:00 |
| `2024-01-15 10:00:00 -1234 widgets left` | 10:00 (no zone has 34 minutes) |
| `2024-01-15 10:00:00 +9 retries` | 10:00 |
| `2024-01-15 10:00:00 -0500ms` | 10:00 |
| `2024-01-15 10:00:00 +0100 items` | 09:00 |

The last row is the cost of the rule: a message that begins with a signed four-digit number
that happens to be a real offset is read as a zone. The message text is the same either way.

## Numbers

A JSON number is a count since 1970-01-01 UTC. Its size says the unit:

| The number is below | Unit |
|---|---|
| 100,000,000,000 (1e11) | seconds |
| 1e14 | milliseconds |
| 1e17 | microseconds |
| anything larger | nanoseconds |

Only JSON lines are read this way. A number in a plain line is not taken as a time.
