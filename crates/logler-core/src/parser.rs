use crate::types::{LogEntry, LogFormat, LogLevel};
use chrono::{DateTime, FixedOffset, NaiveDate, NaiveDateTime, TimeZone, Utc};
use regex::Regex;
use serde_json::{Map, Value};
use std::cell::Cell;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::OnceLock;
use uuid::Uuid;

/// Entry ids come from a counter, not from random bytes. An id is a version 4 shaped UUID: a
/// 60 bit count in bytes 0 to 7 (around the version mark) and the run's 62 random bits in bytes
/// 8 to 15 (after the variant mark). A thread takes a block of counts from `NEXT_BLOCK`, which
/// hands out each block once, and counts inside its own block with no shared write: no two
/// entries of one process share an id, whichever parser or thread made them.
///
/// A process made by fork starts with a copy of these counters, so it must call
/// `start_new_id_run` before it makes an id: its ids then differ from its parent's and from
/// those of every other child. The Python module does so in every child `os.fork` makes.
const ID_BLOCK: u64 = 4096;
const ID_COUNT_MASK: u64 = (1 << 60) - 1;
static NEXT_BLOCK: AtomicU64 = AtomicU64::new(0);
/// Bytes 8 to 15 of every id of this run. 0 means not drawn yet: the variant mark makes a drawn
/// value non-zero.
static RUN_BITS: AtomicU64 = AtomicU64::new(0);

thread_local! {
    /// The next count this thread uses and the end of its block.
    static ID_BLOCK_RANGE: Cell<(u64, u64)> = const { Cell::new((0, 0)) };
}

/// Forget the run's random bits, so the next id draws new ones.
pub fn start_new_id_run() {
    RUN_BITS.store(0, Ordering::Relaxed);
}

fn run_bits() -> u64 {
    match RUN_BITS.load(Ordering::Relaxed) {
        0 => draw_run_bits(),
        bits => bits,
    }
}

#[cold]
fn draw_run_bits() -> u64 {
    let random = Uuid::new_v4();
    let mut tail = [0u8; 8];
    tail.copy_from_slice(&random.as_bytes()[8..16]);
    let drawn = u64::from_be_bytes(tail);
    match RUN_BITS.compare_exchange(0, drawn, Ordering::Relaxed, Ordering::Relaxed) {
        Ok(_) => drawn,
        Err(first) => first,
    }
}

fn next_entry_id() -> Uuid {
    let count = ID_BLOCK_RANGE.with(|range| {
        let (mut next, mut end) = range.get();
        if next == end {
            next = NEXT_BLOCK.fetch_add(ID_BLOCK, Ordering::Relaxed);
            end = next + ID_BLOCK;
        }
        range.set((next + 1, end));
        next & ID_COUNT_MASK
    });
    let mut bytes = [0u8; 16];
    bytes[0..6].copy_from_slice(&(count >> 12).to_be_bytes()[2..8]);
    bytes[6] = 0x40 | ((count >> 8) & 0x0F) as u8;
    bytes[7] = (count & 0xFF) as u8;
    bytes[8..16].copy_from_slice(&run_bits().to_be_bytes());
    Uuid::from_bytes(bytes)
}

static TIMESTAMP_RE: OnceLock<Regex> = OnceLock::new();
static LOG_LEVEL_RE: OnceLock<Regex> = OnceLock::new();
static THREAD_ID_RE: OnceLock<Regex> = OnceLock::new();
static CORRELATION_ID_RE: OnceLock<Regex> = OnceLock::new();
static TRACE_ID_RE: OnceLock<Regex> = OnceLock::new();
static SPAN_ID_RE: OnceLock<Regex> = OnceLock::new();
static SYSLOG_PRIORITY_RE: OnceLock<Regex> = OnceLock::new();
static COMMON_LOG_RE: OnceLock<Regex> = OnceLock::new();
static LOGFMT_PAIR_RE: OnceLock<Regex> = OnceLock::new();
static BSD_SYSLOG_RE: OnceLock<Regex> = OnceLock::new();

/// A timestamp inside a line: date, `T` or space, time, an optional `.` or `,` fraction and an
/// optional zone. `read_timestamp` reads what this finds.
const TIMESTAMP_PATTERN: &str =
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?";

// One list of keys per field, read by the JSON and the logfmt branch; the first key present wins.
/// Public so that a caller names the same keys the parser reads (a custom format's group too).
pub const TIMESTAMP_KEYS: &[&str] = &["timestamp", "time", "@timestamp", "ts", "datetime"];
const LEVEL_KEYS: &[&str] = &["level", "severity", "log_level", "loglevel", "lvl"];
const MESSAGE_KEYS: &[&str] = &["message", "msg", "text", "content"];
const THREAD_KEYS: &[&str] = &[
    "thread",
    "thread_id",
    "tid",
    "threadId",
    "thread_name",
    "threadName",
];
const CORRELATION_KEYS: &[&str] = &[
    "correlation_id",
    "correlationId",
    "request_id",
    "requestId",
    "req_id",
];
const TRACE_KEYS: &[&str] = &["trace_id", "traceId"];
const SPAN_KEYS: &[&str] = &["span_id", "spanId"];
const PARENT_SPAN_KEYS: &[&str] = &["parent_span_id", "parentSpanId"];
const SERVICE_KEYS: &[&str] = &["service", "service_name", "serviceName"];

/// Whether a line is empty or holds only white space, and so is no entry. White space is what
/// Python's `str.strip()` removes: Unicode white space and the four separators U+001C to
/// U+001F, which `char::is_whitespace` leaves out.
pub fn is_blank_line(line: &str) -> bool {
    line.chars()
        .all(|c| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
}

/// The object a line holds when, trimmed, it is one JSON object and nothing else.
fn json_object(line: &str) -> Option<Map<String, Value>> {
    let trimmed = line.trim();
    if !trimmed.starts_with('{') {
        return None;
    }
    match serde_json::from_str(trimmed).ok()? {
        Value::Object(object) => Some(object),
        _ => None,
    }
}

/// Whether a line starts with a month's three letters, as a BSD syslog line does.
fn starts_with_month(text: &str) -> bool {
    matches!(
        text.as_bytes().get(..3),
        Some(
            b"Jan"
                | b"Feb"
                | b"Mar"
                | b"Apr"
                | b"May"
                | b"Jun"
                | b"Jul"
                | b"Aug"
                | b"Sep"
                | b"Oct"
                | b"Nov"
                | b"Dec"
        )
    )
}

/// The first key of `keys` for which `read` gives a value.
fn first_by<T>(keys: &[&str], read: impl Fn(&str) -> Option<T>) -> Option<T> {
    keys.iter().find_map(|key| read(key))
}

/// An all-zero id of 16 or 32 characters is the id OpenTelemetry writes for a line made outside
/// a span; W3C trace context and B3 call it invalid. It names nothing, so an entry has no id
/// there. Any other id, zeros or not, is kept as written.
fn is_no_id(id: &str) -> bool {
    matches!(id.len(), 16 | 32) && id.bytes().all(|byte| byte == b'0')
}

/// Like `first_by`, and the key that gave the value is noted in `taken`.
fn take_first<'k, T>(
    keys: &[&'k str],
    taken: &mut Vec<&'k str>,
    read: impl Fn(&str) -> Option<T>,
) -> Option<T> {
    keys.iter().find_map(|key| {
        let value = read(key)?;
        taken.push(key);
        Some(value)
    })
}

/// A Unix time given as a JSON number. Its size tells the unit: seconds stay below 1e11
/// (the year 5138), then milliseconds, microseconds and nanoseconds, each a thousand times
/// larger. A number with a fraction is kept to the microsecond.
fn epoch_timestamp(number: &serde_json::Number) -> Option<DateTime<Utc>> {
    let per_second = |size: f64| match size {
        s if s < 1e11 => 1_i64,
        s if s < 1e14 => 1_000,
        s if s < 1e17 => 1_000_000,
        _ => 1_000_000_000,
    };
    if let Some(whole) = number.as_i64() {
        let units = per_second(whole.unsigned_abs() as f64);
        let nanos = whole.rem_euclid(units) * (1_000_000_000 / units);
        return DateTime::from_timestamp(whole.div_euclid(units), nanos as u32);
    }
    let value = number.as_f64()?;
    let micros = (value / per_second(value.abs()) as f64 * 1e6).round();
    // `as` saturates, and chrono refuses what lies past its last year.
    DateTime::from_timestamp_micros(micros as i64)
}

/// A run of ASCII digits as a number; `None` when any byte is something else.
fn number(digits: &[u8]) -> Option<u32> {
    digits.iter().try_fold(0u32, |sum, byte| {
        byte.is_ascii_digit()
            .then(|| sum * 10 + u32::from(byte - b'0'))
    })
}

/// The one reader of a timestamp string: `YYYY-MM-DD`, `T` or a space, `HH:MM:SS`, an optional
/// fraction after `.` or `,`, and an optional zone (`Z`, `+09:00`, `+0900`). No zone is read
/// as UTC. The shape is fixed, so it is read by position, in one pass and without a format
/// string; anything left over after the zone makes it no timestamp.
fn read_timestamp(text: &str) -> Option<DateTime<Utc>> {
    let (head, mut rest) = text.trim().as_bytes().split_at_checked(19)?;
    let marks = (head[4], head[7], head[10], head[13], head[16]);
    if !matches!(marks, (b'-', b'-', b'T' | b't' | b' ', b':', b':')) {
        return None;
    }
    let part = |from: usize, to: usize| number(&head[from..to]);
    let date = NaiveDate::from_ymd_opt(part(0, 4)? as i32, part(5, 7)?, part(8, 10)?)?;
    let (hour, minute, second) = (part(11, 13)?, part(14, 16)?, part(17, 19)?);

    let mut nanos = 0;
    if let [b'.' | b',', fraction @ ..] = rest {
        let count = fraction.iter().take_while(|b| b.is_ascii_digit()).count();
        // Nine digits make a nanosecond; digits past the ninth are dropped.
        let kept = &fraction[..count.min(9)];
        if kept.is_empty() {
            return None;
        }
        nanos = number(kept)? * 10u32.pow(9 - kept.len() as u32);
        rest = &fraction[count..];
    }
    // chrono keeps a leap second (`:60`) as second 59 with one more second of nanoseconds.
    let (second, nanos) = match second {
        60 => (59, nanos + 1_000_000_000),
        _ => (second, nanos),
    };
    let local = date.and_hms_nano_opt(hour, minute, second, nanos)?;

    let east = match rest.trim_ascii_start() {
        [] | [b'Z' | b'z'] => 0,
        [sign @ (b'+' | b'-'), h1, h2, b':', m1, m2] | [sign @ (b'+' | b'-'), h1, h2, m1, m2] => {
            let (hours, minutes) = (number(&[*h1, *h2])?, number(&[*m1, *m2])?);
            if minutes > 59 {
                return None;
            }
            let seconds = (hours * 3600 + minutes * 60) as i32;
            if *sign == b'-' {
                -seconds
            } else {
                seconds
            }
        }
        _ => return None,
    };
    let zone = FixedOffset::east_opt(east)?;
    Some(
        zone.from_local_datetime(&local)
            .single()?
            .with_timezone(&Utc),
    )
}

/// The part of a time a strptime word fills.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum TimePart {
    Year,
    Month,
    Day,
    Hour,
    Minute,
    Second,
    Fraction,
    Zone,
}

impl TimePart {
    fn name(self) -> &'static str {
        match self {
            TimePart::Year => "year",
            TimePart::Month => "month",
            TimePart::Day => "day",
            TimePart::Hour => "hour",
            TimePart::Minute => "minute",
            TimePart::Second => "second",
            TimePart::Fraction => "fraction of a second",
            TimePart::Zone => "zone",
        }
    }
}

const MONTHS: [&str; 12] = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
];

/// What a strptime word reads: the part it fills and the pattern Python's `_strptime` gives it,
/// with ASCII digits where Python takes any digit. Month names are English, in any letter case.
fn strptime_word(word: char) -> Result<(TimePart, &'static str), String> {
    Ok(match word {
        'Y' => (TimePart::Year, "[0-9]{4}"),
        'y' => (TimePart::Year, "[0-9]{2}"),
        'm' => (TimePart::Month, "1[0-2]|0[1-9]|[1-9]"),
        'b' => (
            TimePart::Month,
            "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec",
        ),
        'B' => (
            TimePart::Month,
            "september|february|november|december|january|october|august|april|march|july|june|may",
        ),
        'd' => (TimePart::Day, "3[01]|[12][0-9]|0[1-9]|[1-9]| [1-9]"),
        'H' => (TimePart::Hour, "2[0-3]|[01][0-9]|[0-9]"),
        'M' => (TimePart::Minute, "[0-5][0-9]|[0-9]"),
        'S' => (TimePart::Second, "6[01]|[0-5][0-9]|[0-9]"),
        'f' => (TimePart::Fraction, "[0-9]{1,6}"),
        // Python's `%z`, but a colon is used throughout or not at all, and an offset holds
        // no fraction of a second.
        'z' => (
            TimePart::Zone,
            "[+-][0-9]{2}(?::[0-5][0-9](?::[0-5][0-9])?|[0-5][0-9](?:[0-5][0-9])?)|(?-i:Z)",
        ),
        'Z' => {
            return Err(
                "%Z is not supported: a zone name is read differently from machine to \
                        machine; write the zone as an offset and read it with %z"
                    .to_string(),
            )
        }
        'a' | 'A' | 'c' | 'x' | 'X' | 'p' => {
            return Err(format!(
                "%{word} is read in the machine's language, which differs from machine to machine"
            ))
        }
        _ => {
            return Err(format!(
                "%{word} is not supported; the words read are %Y %y %m %b %B %d %H %M %S %f %z \
                 and %%"
            ))
        }
    })
}

/// A format's `timestamp_format`: Python's `strptime` words, compiled once per load and read
/// as `datetime.strptime` reads them. The text must be the whole of what the format describes
/// (no text left over), white space in the format stands for any run of white space, and
/// letters match in any case. A time without `%z` is UTC; a second 60 is a leap second, as
/// in `read_timestamp`.
#[derive(Debug, Clone)]
pub struct TimestampFormat {
    pattern: Regex,
}

impl TimestampFormat {
    /// The format compiled, or why it cannot be: a word that is not read (the message names
    /// it), a part given by two words, a lone `%` at the end, or no full date.
    pub fn compile(format: &str) -> Result<Self, String> {
        let mut pattern = String::from("(?i)^(?:");
        let mut seen: Vec<(TimePart, char)> = Vec::new();
        let mut chars = format.chars().peekable();
        while let Some(c) = chars.next() {
            if c == '%' {
                let Some(word) = chars.next() else {
                    return Err("the format ends in a lone %; write a literal % as %%".to_string());
                };
                if word == '%' {
                    pattern.push('%');
                    continue;
                }
                let (part, word_pattern) = strptime_word(word)?;
                if let Some((_, first)) = seen.iter().find(|(p, _)| *p == part) {
                    return Err(format!(
                        "the {} is given by two words, %{first} and %{word}",
                        part.name()
                    ));
                }
                seen.push((part, word));
                pattern.push_str(&format!("(?P<{word}>{word_pattern})"));
            } else if c.is_whitespace() {
                while chars.next_if(|next| next.is_whitespace()).is_some() {}
                pattern.push_str(r"\s+");
            } else {
                pattern.push_str(&regex::escape(c.encode_utf8(&mut [0; 4])));
            }
        }
        pattern.push_str(")$");

        let missing: Vec<&str> = [
            (TimePart::Year, "year (%Y or %y)"),
            (TimePart::Month, "month (%m, %b or %B)"),
            (TimePart::Day, "day (%d)"),
        ]
        .iter()
        .filter(|(part, _)| !seen.iter().any(|(p, _)| p == part))
        .map(|(_, name)| *name)
        .collect();
        if let Some((last, rest)) = missing.split_last() {
            let list = if rest.is_empty() {
                format!("no {last}")
            } else {
                format!("no {} and no {last}", rest.join(", no "))
            };
            return Err(format!("a timestamp needs a date: the format has {list}"));
        }

        let pattern = Regex::new(&pattern).map_err(|e| e.to_string())?;
        Ok(Self { pattern })
    }

    /// The instant `text` names, or `None` when the format does not fit all of it or the
    /// date or time does not exist (31 February, hour 24).
    pub fn read(&self, text: &str) -> Option<DateTime<Utc>> {
        let caps = self.pattern.captures(text)?;
        let digits = |name: &str| caps.name(name).map(|m| m.as_str().trim_start().as_bytes());
        let field = |name: &str| digits(name).map_or(Some(0), number);

        let year = match (digits("Y"), digits("y")) {
            (Some(full), _) => number(full)? as i32,
            // Python's pivot: 69 to 99 are the 1900s, 00 to 68 the 2000s.
            (_, Some(short)) => match number(short)? as i32 {
                short @ 0..=68 => 2000 + short,
                short => 1900 + short,
            },
            _ => return None,
        };
        let month = match caps.name("b").or_else(|| caps.name("B")) {
            Some(name) => {
                let name = name.as_str().to_ascii_lowercase();
                MONTHS.iter().position(|month| month.starts_with(&name))? as u32 + 1
            }
            None => field("m")?,
        };
        let date = NaiveDate::from_ymd_opt(year, month, field("d")?)?;

        let nanos = match digits("f") {
            Some(fraction) => number(fraction)? * 10u32.pow(9 - fraction.len() as u32),
            None => 0,
        };
        // chrono keeps a leap second (`:60`) as second 59 with one more second of nanoseconds.
        let (second, nanos) = match field("S")? {
            60 => (59, nanos + 1_000_000_000),
            second => (second, nanos),
        };
        let local = date.and_hms_nano_opt(field("H")?, field("M")?, second, nanos)?;

        let east = match caps.name("z").map(|m| m.as_str().as_bytes()) {
            None | Some(b"Z") => 0,
            Some([sign, offset @ ..]) => {
                let offset: Vec<u8> = offset.iter().copied().filter(|b| *b != b':').collect();
                let (hours, rest) = offset.split_at(2);
                let (minutes, seconds) = rest.split_at(2);
                let seconds = if seconds.is_empty() {
                    0
                } else {
                    number(seconds)?
                };
                let east = (number(hours)? * 3600 + number(minutes)? * 60 + seconds) as i32;
                if *sign == b'-' {
                    -east
                } else {
                    east
                }
            }
            Some([]) => return None,
        };
        Some(
            FixedOffset::east_opt(east)?
                .from_local_datetime(&local)
                .single()?
                .with_timezone(&Utc),
        )
    }
}

/// The letters a line starts with, when a word ends there (no digit or `_` runs on).
fn leading_word(text: &str) -> Option<&str> {
    let end = text
        .find(|c: char| !c.is_ascii_alphabetic())
        .unwrap_or(text.len());
    let runs_on = text[end..]
        .chars()
        .next()
        .is_some_and(|c| c.is_alphanumeric() || c == '_');
    (end > 0 && !runs_on).then(|| &text[..end])
}

/// A level word at the head of a line, in any letter case: the first word after a timestamp
/// that starts the line, bare or in square brackets (`2024-01-15 10:00:00 warn ...`,
/// `[2024-01-15 10:00:00] warn ...`; spaces, `-`, `|` or `:` may stand between), or the
/// first word of the line when a colon follows it (`error: disk full`).
/// `timestamp` is the first timestamp of `text`, as `find_timestamp` gives it.
fn head_level(text: &str, timestamp: Option<&Found>) -> Option<LogLevel> {
    let lead = text.len() - text.trim_start().len();
    let leads = |found: &&Found| {
        let rest = &text[lead..found.start()];
        rest.is_empty() || (rest == "[" && text[found.end()..].starts_with(']'))
    };
    if let Some(timestamp) = timestamp.filter(leads) {
        let rest = &text[timestamp.end()..];
        let word = rest.trim_start_matches(|c: char| c.is_whitespace() || "]-|:".contains(c));
        if word.len() == rest.len() {
            return None;
        }
        return LogLevel::from_word(leading_word(word)?);
    }
    let text = &text[lead..];
    let word = leading_word(text)?;
    text[word.len()..]
        .starts_with(':')
        .then(|| LogLevel::from_word(word))?
}

/// The first level word that stands alone in square brackets, in any letter case: `[info]`.
/// Only the few bytes after each `[` are read, so a line of many brackets costs one pass.
fn bracket_level(text: &str) -> Option<LogLevel> {
    text.match_indices('[').find_map(|(open, _)| {
        let inner = &text.as_bytes()[open + 1..];
        let close = inner
            .iter()
            .take(LogLevel::LONGEST_WORD + 1)
            .position(|b| !b.is_ascii_alphabetic())?;
        (inner[close] == b']').then(|| LogLevel::from_word(&text[open + 1..open + 1 + close]))?
    })
}

/// Where a timestamp stands in a text: the bytes `start..end` of `text`.
#[derive(Debug, Clone, Copy)]
struct Found<'t> {
    text: &'t str,
    start: usize,
    end: usize,
}

impl<'t> Found<'t> {
    fn start(&self) -> usize {
        self.start
    }

    fn end(&self) -> usize {
        self.end
    }

    fn as_str(&self) -> &'t str {
        &self.text[self.start..self.end]
    }
}

/// The end of a numeric offset that stands after one space at `from` (` +0900`, ` -05:30`):
/// the hours are 00 to 14, the minutes 00, 15, 30 or 45, and a space, a `]` or the end of the
/// text follows. Anything else (`-1234 widgets`, `+9 retries`, `-0500ms`) is no zone.
fn zone_after_space(text: &str, from: usize) -> Option<usize> {
    let rest = text.as_bytes().get(from..)?;
    let [b' ', b'+' | b'-', zone @ ..] = rest else {
        return None;
    };
    let (h1, h2, m1, m2, after) = match zone {
        [h1, h2, b':', m1, m2, after @ ..] | [h1, h2, m1, m2, after @ ..] => {
            (*h1, *h2, *m1, *m2, after)
        }
        _ => return None,
    };
    if !matches!(after.first(), None | Some(b' ' | b']')) {
        return None;
    }
    let (hours, minutes) = (number(&[h1, h2])?, number(&[m1, m2])?);
    let real = hours <= 14 && matches!(minutes, 0 | 15 | 30 | 45);
    real.then(|| text.len() - after.len())
}

/// The first timestamp in a text. One search serves both the timestamp and the level. The
/// pattern stops at the seconds or at a zone written with no space; a numeric offset after
/// one space is the zone too (`zone_after_space`), unless a zone was already read.
fn find_timestamp(text: &str) -> Option<Found<'_>> {
    let found = TIMESTAMP_RE.get()?.find(text)?;
    // Read as bytes: the pattern's `\d` takes any Unicode digit, so byte 19 of what it found
    // can fall inside a letter. Such a text is no timestamp to `read_timestamp` either way.
    let has_zone = found.as_str().as_bytes()[19..]
        .iter()
        .any(|b| matches!(b, b'Z' | b'+' | b'-'));
    let end = if has_zone {
        found.end()
    } else {
        zone_after_space(text, found.end()).unwrap_or(found.end())
    };
    Some(Found {
        text,
        start: found.start(),
        end,
    })
}

fn init_regexes() {
    TIMESTAMP_RE.get_or_init(|| Regex::new(TIMESTAMP_PATTERN).unwrap());
    // A level word in capitals, anywhere in the line; the words come from the one table in
    // `types.rs`. The places where a word counts in any letter case are in `extract_level`.
    // This function runs for every line, so the pattern is built inside the closure.
    LOG_LEVEL_RE
        .get_or_init(|| Regex::new(&format!(r"\b(?:{})\b", LogLevel::words_pattern())).unwrap());
    THREAD_ID_RE.get_or_init(|| {
        Regex::new(concat!(
            r"(?:",
            // thread_id=xxx, thread=xxx, tid=xxx formats
            r"(?:thread[_-]?(?:id)?|tid)[=:\s]+([a-zA-Z0-9_.-]+)",
            r"|",
            // [thread-name] bracketed format (with optional -thread-N suffix)
            r"\[([a-zA-Z0-9_.-]+(?:-thread-\d+)?)\]",
            r"|",
            // Java thread pool patterns: pool-1-thread-1
            r"\b(pool-\d+-thread-\d+)\b",
            r"|",
            // Python ThreadPoolExecutor patterns: ThreadPoolExecutor-0_0
            r"\b(ThreadPoolExecutor-\d+_\d+)\b",
            r"|",
            // Common thread name patterns: MainThread, WorkerThread-1
            r"\b((?:Main|Worker)Thread(?:-\d+)?)\b",
            r")"
        ))
        .unwrap()
    });
    CORRELATION_ID_RE.get_or_init(|| {
        Regex::new(r"(?:correlation[_-]?id|request[_-]?id|req[_-]?id)[=:\s]+([a-zA-Z0-9_-]+)")
            .unwrap()
    });
    TRACE_ID_RE.get_or_init(|| {
        Regex::new(r"(?:trace[_-]?id|traceId)[=:\s]+([a-fA-F0-9]{16,32})").unwrap()
    });
    SPAN_ID_RE
        .get_or_init(|| Regex::new(r"(?:span[_-]?id|spanId)[=:\s]+([a-zA-Z0-9_-]+)").unwrap());
    SYSLOG_PRIORITY_RE.get_or_init(|| Regex::new(r"^<(\d+)>").unwrap());
    COMMON_LOG_RE.get_or_init(|| {
        Regex::new(r#"^(\S+) \S+ \S+ \[([^\]]+)\] "([^"]+)" (\d+) (\S+)"#).unwrap()
    });
    LOGFMT_PAIR_RE.get_or_init(|| Regex::new(r#"(\w+)=(?:"([^"]*)"|([^\s]+))"#).unwrap());
    BSD_SYSLOG_RE.get_or_init(|| {
        Regex::new(r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+\S+(?:\[\d+\])?:")
            .unwrap()
    });
}

#[derive(Debug, Clone, Default)]
pub struct ParserConfig {
    pub force_format: Option<LogFormat>,
    pub custom_regex: Option<Regex>,
    /// How the custom regex's timestamp group is written; tried before the known shapes.
    pub timestamp_format: Option<TimestampFormat>,
}

impl ParserConfig {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_force_format(mut self, format: LogFormat) -> Self {
        self.force_format = Some(format);
        self
    }

    pub fn with_custom_regex(mut self, regex: Regex) -> Self {
        self.custom_regex = Some(regex);
        self.force_format = Some(LogFormat::Custom);
        self
    }

    pub fn with_timestamp_format(mut self, format: TimestampFormat) -> Self {
        self.timestamp_format = Some(format);
        self
    }

    pub fn build_for_file<S: Into<String>>(&self, file_name: S) -> LogParser {
        LogParser::from_config(file_name, self.clone())
    }
}

#[derive(Debug, Clone)]
pub struct LogParser {
    file_name: String,
    config: ParserConfig,
}

impl LogParser {
    pub fn new<S: Into<String>>(file_name: S) -> Self {
        Self::from_config(file_name, ParserConfig::default())
    }

    pub fn with_force_format<S: Into<String>>(file_name: S, format: LogFormat) -> Self {
        Self::from_config(
            file_name,
            ParserConfig {
                force_format: Some(format),
                custom_regex: None,
                timestamp_format: None,
            },
        )
    }

    pub fn with_custom_regex<S: Into<String>>(file_name: S, regex: Regex) -> Self {
        Self::from_config(
            file_name,
            ParserConfig {
                force_format: Some(LogFormat::Custom),
                custom_regex: Some(regex),
                timestamp_format: None,
            },
        )
    }

    pub fn from_config<S: Into<String>>(file_name: S, config: ParserConfig) -> Self {
        init_regexes();
        Self {
            file_name: file_name.into(),
            config,
        }
    }

    pub fn set_custom_regex(mut self, regex: Regex) -> Self {
        self.config.custom_regex = Some(regex);
        self.config.force_format = Some(LogFormat::Custom);
        self
    }

    pub fn parse_line(&self, line_number: usize, raw: &str) -> anyhow::Result<LogEntry> {
        // A JSON line is parsed once: detection keeps the object it parsed for the reader.
        let (format, json) = match self.config.force_format {
            Some(format) => (format, None),
            None => match json_object(raw) {
                Some(object) => (LogFormat::Json, Some(object)),
                None => (Self::detect_text(raw.trim()), None),
            },
        };
        let parsed = match format {
            LogFormat::Json => match json {
                Some(object) => Some(self.json_entry(line_number, raw, object)),
                None => self.try_parse_json(line_number, raw),
            },
            LogFormat::Syslog => self.parse_syslog(line_number, raw),
            LogFormat::CommonLog => self.parse_common_log(line_number, raw),
            LogFormat::Logfmt => self.parse_logfmt(line_number, raw),
            LogFormat::PlainText | LogFormat::Unknown => Some(self.parse_plain(line_number, raw)),
            LogFormat::Custom => self
                .config
                .custom_regex
                .as_ref()
                .and_then(|regex| self.try_parse_custom(line_number, raw, regex)),
        };

        let mut entry = parsed.unwrap_or_else(|| self.parse_plain(line_number, raw));

        // If a custom regex was provided but not matched earlier, try again on the parsed line.
        if entry.format == LogFormat::PlainText {
            if let Some(regex) = &self.config.custom_regex {
                if let Some(custom_entry) = self.try_parse_custom(line_number, raw, regex) {
                    entry = custom_entry;
                }
            }
        }

        // Fallback: if syslog priority is present but detection missed, still parse as syslog.
        // The pattern is anchored on `<`, so a line that does not start with one is not run.
        if entry.format == LogFormat::PlainText && raw.starts_with('<') {
            if let Some(syslog_re) = SYSLOG_PRIORITY_RE.get() {
                if syslog_re.is_match(raw) {
                    if let Some(syslog_entry) = self.parse_syslog(line_number, raw) {
                        entry = syslog_entry;
                    }
                }
            }
        }

        entry.trace_id = entry.trace_id.filter(|id| !is_no_id(id));
        entry.span_id = entry.span_id.filter(|id| !is_no_id(id));
        entry.parent_span_id = entry.parent_span_id.filter(|id| !is_no_id(id));

        Ok(entry)
    }

    pub fn detect_format(line: &str) -> LogFormat {
        init_regexes();
        if json_object(line).is_some() {
            return LogFormat::Json;
        }
        Self::detect_text(line.trim())
    }

    /// The format of a trimmed line that is not a JSON object. Each pattern is tried only on a
    /// line that holds the bytes it cannot match without, so a bare plain line costs a few
    /// byte tests, not four regex runs.
    fn detect_text(trimmed: &str) -> LogFormat {
        if trimmed.starts_with('<') && SYSLOG_PRIORITY_RE.get().unwrap().is_match(trimmed) {
            return LogFormat::Syslog;
        }
        // `Jan`..`Dec` open a BSD syslog line; `[` and `"` are in a common log line's pattern.
        if starts_with_month(trimmed) && BSD_SYSLOG_RE.get().unwrap().is_match(trimmed) {
            return LogFormat::Syslog;
        }
        if trimmed.contains('[')
            && trimmed.contains('"')
            && COMMON_LOG_RE.get().unwrap().is_match(trimmed)
        {
            return LogFormat::CommonLog;
        }
        // A logfmt pair has an `=`.
        if trimmed.contains('=')
            && LOGFMT_PAIR_RE
                .get()
                .unwrap()
                .find_iter(trimmed)
                .take(2)
                .count()
                >= 2
        {
            return LogFormat::Logfmt;
        }
        LogFormat::PlainText
    }

    fn base_entry(&self, line_number: usize, raw: &str, format: LogFormat) -> LogEntry {
        LogEntry {
            id: next_entry_id(),
            file: self.file_name.clone(),
            line_number,
            raw: raw.to_string(),
            timestamp: None,
            level: None,
            format,
            message: raw.to_string(),
            thread_id: None,
            correlation_id: None,
            trace_id: None,
            span_id: None,
            parent_span_id: None,
            service_name: None,
            fields: HashMap::new(),
        }
    }

    fn try_parse_json(&self, line_number: usize, raw: &str) -> Option<LogEntry> {
        let object = json_object(raw)?;
        Some(self.json_entry(line_number, raw, object))
    }

    /// The entry of a JSON object read from `raw`.
    fn json_entry(&self, line_number: usize, raw: &str, obj: Map<String, Value>) -> LogEntry {
        let mut entry = self.base_entry(line_number, raw, LogFormat::Json);

        // The keys read into an entry field. Every other key stays in `fields`, a listed key
        // whose value could not be read (`"level": 30`, a second message key) among them.
        let mut taken: Vec<&str> = Vec::new();
        entry.timestamp = take_first(TIMESTAMP_KEYS, &mut taken, |key| match obj.get(key)? {
            Value::String(text) => read_timestamp(text),
            Value::Number(number) => epoch_timestamp(number),
            _ => None,
        });
        // A word beats a number, whichever key holds it: a word names its level, while a number
        // is read from `LEVEL_NUMBERS` and its writer may have meant another scale. Among words
        // the first key wins, and among numbers the first that is in the table. A number that
        // was not read is left in `fields`.
        let mut numbered = None;
        for key in LEVEL_KEYS {
            match obj.get(*key) {
                Some(Value::String(word)) => {
                    if let Some(level) = LogLevel::parse(word) {
                        entry.level = Some(level);
                        taken.push(key);
                        break;
                    }
                }
                Some(Value::Number(number)) if numbered.is_none() => {
                    numbered = number
                        .as_u64()
                        .and_then(LogLevel::from_number)
                        .map(|level| (*key, level));
                }
                _ => {}
            }
        }
        if entry.level.is_none() {
            if let Some((key, level)) = numbered {
                entry.level = Some(level);
                taken.push(key);
            }
        }
        entry.message = take_first(MESSAGE_KEYS, &mut taken, |key| {
            obj.get(key)?.as_str().map(String::from)
        })
        .unwrap_or_else(|| serde_json::to_string(&obj).unwrap_or_default());
        let mut id = |keys: &[&'static str]| {
            take_first(keys, &mut taken, |key| match obj.get(key)? {
                Value::String(text) => Some(text.clone()),
                Value::Number(number) => Some(number.to_string()),
                _ => None,
            })
        };
        entry.thread_id = id(THREAD_KEYS);
        entry.correlation_id = id(CORRELATION_KEYS);
        entry.trace_id = id(TRACE_KEYS);
        entry.span_id = id(SPAN_KEYS);
        entry.parent_span_id = id(PARENT_SPAN_KEYS);
        entry.service_name = id(SERVICE_KEYS);

        for (key, value) in obj {
            if !taken.contains(&key.as_str()) {
                entry.fields.insert(key, value);
            }
        }

        entry
    }

    fn parse_plain(&self, line_number: usize, raw: &str) -> LogEntry {
        let mut entry = self.base_entry(line_number, raw, LogFormat::PlainText);

        let timestamp = find_timestamp(raw);
        entry.timestamp = timestamp.and_then(|found| read_timestamp(found.as_str()));
        entry.level = self.extract_level(raw, timestamp.as_ref());
        entry.thread_id = self.extract_thread_id(raw);
        entry.correlation_id = self.extract_correlation_id(raw);
        entry.trace_id = self.extract_trace_id(raw);
        entry.span_id = self.extract_span_id(raw);

        entry
    }

    fn parse_syslog(&self, line_number: usize, raw: &str) -> Option<LogEntry> {
        let mut entry = self.base_entry(line_number, raw, LogFormat::Syslog);
        let mut remaining = raw;

        if let Some(cap) = SYSLOG_PRIORITY_RE.get()?.captures(raw) {
            let priority: u32 = cap[1].parse().unwrap_or(0);
            let severity = priority & 0x07;
            entry.level =
                Some(LogLevel::from_number(u64::from(severity)).unwrap_or(LogLevel::Unknown));
            remaining = &raw[cap.get(0)?.end()..];
        }

        let timestamp = find_timestamp(remaining);
        // Keyword fallback for syslog without priority prefix
        if entry.level.is_none() {
            entry.level = self.extract_level(remaining, timestamp.as_ref());
        }
        // Pattern-based inference for common syslog messages
        if entry.level.is_none() {
            entry.level = Self::infer_syslog_level(remaining);
        }

        entry.timestamp = timestamp.and_then(|found| read_timestamp(found.as_str()));
        entry.message = remaining.trim().to_string();
        Some(entry)
    }

    fn infer_syslog_level(text: &str) -> Option<LogLevel> {
        let lower = text.to_lowercase();

        // Fatal patterns
        if lower.contains("out of memory")
            || lower.contains("kill process")
            || lower.contains("segfault")
            || lower.contains("kernel panic")
            || lower.contains("oom-killer")
        {
            return Some(LogLevel::Fatal);
        }

        // Error patterns
        if lower.contains("failed password")
            || lower.contains("authentication failure")
            || lower.contains("invalid user")
            || lower.contains("connection refused")
            || lower.contains("permission denied")
            || lower.contains("not allowed")
            || lower.contains("fatal:")
            || lower.contains("error:")
            || lower.contains("failed to")
            || lower.contains("unable to")
            || lower.contains("timed out")
            || lower.contains("timeout")
        {
            return Some(LogLevel::Error);
        }

        // Warn patterns
        if lower.contains("warning:")
            || lower.contains("rate limit")
            || lower.contains("stopping")
            || lower.contains("deprecated")
            || lower.contains("retry")
        {
            return Some(LogLevel::Warn);
        }

        // Info patterns (common success/operational messages)
        if lower.contains("accepted")
            || lower.contains("session opened")
            || lower.contains("session closed")
            || lower.contains("started")
            || lower.contains("mounted")
            || lower.contains("received signal")
            || lower.contains("listening on")
            || lower.contains(") cmd")
        {
            return Some(LogLevel::Info);
        }

        None
    }

    fn parse_common_log(&self, line_number: usize, raw: &str) -> Option<LogEntry> {
        let mut entry = self.base_entry(line_number, raw, LogFormat::CommonLog);
        let caps = COMMON_LOG_RE.get()?.captures(raw)?;

        let timestamp_str = caps.get(2)?.as_str();
        if let Ok(dt) = DateTime::parse_from_str(timestamp_str, "%d/%b/%Y:%H:%M:%S %z") {
            entry.timestamp = Some(dt.with_timezone(&Utc));
        }

        let status: u16 = caps.get(4)?.as_str().parse().unwrap_or(0);
        entry.level = Some(if status >= 500 {
            LogLevel::Error
        } else if status >= 400 {
            LogLevel::Warn
        } else {
            LogLevel::Info
        });

        entry.message = format!("{} {} {}", &caps[1], &caps[3], &caps[4]);
        entry
            .fields
            .insert("remote_addr".into(), Value::String(caps[1].to_string()));
        entry
            .fields
            .insert("request".into(), Value::String(caps[3].to_string()));
        entry
            .fields
            .insert("status".into(), Value::Number(status.into()));
        entry
            .fields
            .insert("size".into(), Value::String(caps[5].to_string()));

        Some(entry)
    }

    fn parse_logfmt(&self, line_number: usize, raw: &str) -> Option<LogEntry> {
        let mut entry = self.base_entry(line_number, raw, LogFormat::Logfmt);
        let mut fields = HashMap::new();
        // Each value as written in the line: an id is that text, not the number it parses to.
        let mut texts: Vec<(&str, &str)> = Vec::new();

        for cap in LOGFMT_PAIR_RE.get()?.captures_iter(raw) {
            let key = cap.get(1)?.as_str();
            let value = cap
                .get(2)
                .or_else(|| cap.get(3))
                .map(|m| m.as_str())
                .unwrap_or("");

            let json_value = if let Ok(num) = value.parse::<i64>() {
                Value::Number(num.into())
            } else if let Some(num) = value
                .parse::<f64>()
                .ok()
                .and_then(serde_json::Number::from_f64)
            {
                // from_f64 is None for NaN and the infinities ("nan", "inf", "1e999"): JSON
                // has no such number, so those values fall through and stay text.
                Value::Number(num)
            } else if value.eq_ignore_ascii_case("true") || value.eq_ignore_ascii_case("false") {
                Value::Bool(value.eq_ignore_ascii_case("true"))
            } else {
                Value::String(value.to_string())
            };

            texts.push((key, value));
            fields.insert(key.to_string(), json_value);
        }

        // Many logfmt lines lead with a bare timestamp and level before the pairs
        // ("2024-01-15T15:00:00Z INFO service=api ..."). Those leading words are read when
        // no key names the value; a word inside a pair's value never is.
        let prefix = LOGFMT_PAIR_RE
            .get()?
            .find(raw)
            .map_or("", |first_pair| &raw[..first_pair.start()]);

        // A key written twice keeps its last value, as `fields` does.
        let written = |key: &str| {
            texts
                .iter()
                .rev()
                .find(|(name, _)| *name == key)
                .map(|(_, value)| *value)
        };
        let text = |keys: &[&str]| first_by(keys, |key| written(key).map(String::from));
        let lead = find_timestamp(prefix);
        entry.level = first_by(LEVEL_KEYS, |key| written(key).and_then(LogLevel::from_word))
            .or_else(|| self.extract_level(prefix, lead.as_ref()))
            .or(Some(LogLevel::Unknown));
        if let Some(message) = text(MESSAGE_KEYS) {
            entry.message = message;
        }
        entry.timestamp = first_by(TIMESTAMP_KEYS, |key| written(key).and_then(read_timestamp))
            .or_else(|| lead.and_then(|found| read_timestamp(found.as_str())));
        entry.thread_id = text(THREAD_KEYS).or_else(|| self.extract_thread_id(prefix));
        entry.correlation_id = text(CORRELATION_KEYS);
        entry.trace_id = text(TRACE_KEYS);
        entry.span_id = text(SPAN_KEYS);
        entry.parent_span_id = text(PARENT_SPAN_KEYS);
        entry.service_name = text(SERVICE_KEYS);

        entry.fields = fields;
        Some(entry)
    }

    /// A line read by the user's regex. Every named group is read the way the JSON branch reads
    /// a string value: a group named by one of the key lists fills that field (first key
    /// present wins); every other group that took part in the match, and a listed group whose
    /// value was not read, goes into `fields` as captured.
    fn try_parse_custom(&self, line_number: usize, raw: &str, regex: &Regex) -> Option<LogEntry> {
        let caps = regex.captures(raw)?;
        let mut entry = self.base_entry(line_number, raw, LogFormat::Custom);

        let mut taken: Vec<&str> = Vec::new();
        let group = |key: &str| caps.name(key).map(|m| m.as_str());
        entry.timestamp = take_first(TIMESTAMP_KEYS, &mut taken, |key| {
            self.parse_custom_timestamp(group(key)?)
        });
        entry.level = take_first(LEVEL_KEYS, &mut taken, |key| LogLevel::parse(group(key)?));
        if let Some(message) =
            take_first(MESSAGE_KEYS, &mut taken, |key| group(key).map(String::from))
        {
            entry.message = message;
        }
        let mut id = |keys: &[&'static str]| {
            take_first(keys, &mut taken, |key| group(key).map(String::from))
        };
        entry.thread_id = id(THREAD_KEYS);
        entry.correlation_id = id(CORRELATION_KEYS);
        entry.trace_id = id(TRACE_KEYS);
        entry.span_id = id(SPAN_KEYS);
        entry.parent_span_id = id(PARENT_SPAN_KEYS);
        entry.service_name = id(SERVICE_KEYS);

        for name in regex.capture_names().flatten() {
            if taken.contains(&name) {
                continue;
            }
            if let Some(value) = group(name) {
                entry
                    .fields
                    .insert(name.to_string(), Value::String(value.to_string()));
            }
        }

        Some(entry)
    }

    /// The format's `timestamp_format` when it has one and it fits; then the shared reader,
    /// then the looser forms only a custom format's capture may hold: fields written without
    /// a leading zero (`2024-1-5 1:02:03`), or the day first.
    fn parse_custom_timestamp(&self, value: &str) -> Option<DateTime<Utc>> {
        if let Some(time) = self
            .config
            .timestamp_format
            .as_ref()
            .and_then(|format| format.read(value))
        {
            return Some(time);
        }
        read_timestamp(value).or_else(|| {
            ["%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"]
                .iter()
                .find_map(|format| NaiveDateTime::parse_from_str(value, format).ok())
                .map(|dt| DateTime::<Utc>::from_naive_utc_and_offset(dt, Utc))
        })
    }

    /// The leftmost level word in a place where one counts. In capitals a word counts
    /// anywhere. In any letter case it counts at the head of the line (`head_level`) and alone
    /// in square brackets (`bracket_level`); a lower-case word inside a sentence does not.
    /// `timestamp` is the first timestamp of `text`, as `find_timestamp` gives it.
    fn extract_level(&self, text: &str, timestamp: Option<&Found>) -> Option<LogLevel> {
        if let Some(level) = head_level(text, timestamp) {
            return Some(level);
        }
        let capital = LOG_LEVEL_RE.get()?.find(text);
        let end = capital.map_or(text.len(), |word| word.start());
        bracket_level(&text[..end])
            .or_else(|| capital.and_then(|word| LogLevel::from_word(word.as_str())))
    }

    fn extract_thread_id(&self, text: &str) -> Option<String> {
        let re = THREAD_ID_RE.get()?;
        for cap in re.captures_iter(text) {
            // Check all capture groups (1-5) since we have multiple alternations
            for i in 1..=5 {
                if let Some(m) = cap.get(i) {
                    // Group 2 is `[name]`: a level word in brackets is the level, not a thread.
                    if i == 2 && LogLevel::from_word(m.as_str()).is_some() {
                        break;
                    }
                    return Some(m.as_str().to_string());
                }
            }
        }
        None
    }

    fn extract_correlation_id(&self, text: &str) -> Option<String> {
        let re = CORRELATION_ID_RE.get()?;
        let cap = re.captures(text)?;
        Some(cap.get(1)?.as_str().to_string())
    }

    fn extract_trace_id(&self, text: &str) -> Option<String> {
        let re = TRACE_ID_RE.get()?;
        let cap = re.captures(text)?;
        Some(cap.get(1)?.as_str().to_string())
    }

    fn extract_span_id(&self, text: &str) -> Option<String> {
        let re = SPAN_ID_RE.get()?;
        let cap = re.captures(text)?;
        Some(cap.get(1)?.as_str().to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_json() {
        let parser = LogParser::new("test.log");
        let json_line = r#"{"timestamp":"2024-01-15T10:00:00Z","level":"ERROR","message":"Test error","thread_id":"worker-1"}"#;
        let entry = parser.parse_line(1, json_line).unwrap();

        assert_eq!(entry.line_number, 1);
        assert_eq!(entry.level, Some(LogLevel::Error));
        assert_eq!(entry.message, "Test error");
        assert_eq!(entry.thread_id, Some("worker-1".to_string()));
        assert_eq!(entry.format, LogFormat::Json);
    }

    #[test]
    fn test_parse_plain_text() {
        let parser = LogParser::new("test.log");
        let plain_line = "2024-01-15 10:00:00 ERROR [worker-1] Test error message";
        let entry = parser.parse_line(1, plain_line).unwrap();

        assert_eq!(entry.line_number, 1);
        assert_eq!(entry.level, Some(LogLevel::Error));
        assert!(entry.timestamp.is_some());
        assert_eq!(entry.thread_id, Some("worker-1".to_string()));
        assert_eq!(entry.format, LogFormat::PlainText);
    }

    #[test]
    fn test_parse_syslog() {
        let parser = LogParser::new("test.log");
        let line = "<14>2024-01-15T10:00:00Z host app: system rebooted";
        let entry = parser.parse_line(5, line).unwrap();

        assert_eq!(entry.format, LogFormat::Syslog);
        assert_eq!(entry.level, Some(LogLevel::Info));
        assert!(entry.timestamp.is_some());
        assert!(entry.message.contains("system rebooted"));
    }

    #[test]
    fn test_parse_common_log() {
        let parser = LogParser::new("test.log");
        let line =
            r#"127.0.0.1 - - [10/Oct/2000:13:55:36 -0700] "GET /apache.gif HTTP/1.0" 200 2326"#;
        let entry = parser.parse_line(1, line).unwrap();

        assert_eq!(entry.format, LogFormat::CommonLog);
        assert_eq!(entry.level, Some(LogLevel::Info));
        assert!(entry.timestamp.is_some());
        assert!(entry.fields.contains_key("request"));
    }

    #[test]
    fn test_parse_logfmt() {
        let parser = LogParser::new("test.log");
        let line = r#"level=info ts="2024-01-15T10:00:00Z" thread=worker-9 msg="hello world" correlation_id=req-1"#;
        let entry = parser.parse_line(2, line).unwrap();

        assert_eq!(entry.format, LogFormat::Logfmt);
        assert_eq!(entry.level, Some(LogLevel::Info));
        assert_eq!(entry.thread_id.as_deref(), Some("worker-9"));
        assert_eq!(entry.correlation_id.as_deref(), Some("req-1"));
        assert_eq!(entry.message, "hello world");
    }

    #[test]
    fn test_custom_regex() {
        let regex =
            Regex::new(r"^(?P<timestamp>[^ ]+) (?P<level>[A-Z]+) (?P<message>.+)$").unwrap();
        let parser = LogParser::with_custom_regex("test.log", regex);
        let line = "2024-01-15T10:00:00Z WARN subsystem offline";
        let entry = parser.parse_line(3, line).unwrap();

        assert_eq!(entry.format, LogFormat::Custom);
        assert_eq!(entry.level, Some(LogLevel::Warn));
        assert_eq!(entry.message, "subsystem offline");
    }

    #[test]
    fn test_invalid_json_falls_back_to_plain_with_unknown_level() {
        let parser = LogParser::new("test.log");
        let line = r#"{"timestamp": "2024-01-01"#; // malformed JSON
        let entry = parser.parse_line(10, line).unwrap();

        assert_eq!(entry.format, LogFormat::PlainText);
        assert_eq!(entry.line_number, 10);
        assert_eq!(entry.level, None);
        assert_eq!(entry.message, line);
    }

    #[test]
    fn test_logfmt_without_level_defaults_to_unknown() {
        let parser = LogParser::new("test.log");
        let line = r#"ts="2024-01-15T10:00:00Z" msg="no level set" thread=bg-worker"#;
        let entry = parser.parse_line(11, line).unwrap();

        assert_eq!(entry.format, LogFormat::Logfmt);
        assert_eq!(entry.level, Some(LogLevel::Unknown));
        assert_eq!(entry.message, "no level set");
    }

    #[test]
    fn test_logfmt_after_a_leading_timestamp_and_level_keeps_both() {
        // A common shape: the timestamp and level come first as bare words, the rest is pairs.
        let parser = LogParser::new("test.log");
        let line =
            r#"2024-01-15T15:00:00.500Z WARN service=api thread_id=api-001 message="slow start""#;
        let entry = parser.parse_line(13, line).unwrap();

        assert_eq!(entry.format, LogFormat::Logfmt);
        assert_eq!(entry.level, Some(LogLevel::Warn));
        assert_eq!(
            entry.timestamp,
            Some(
                DateTime::parse_from_rfc3339("2024-01-15T15:00:00.500Z")
                    .unwrap()
                    .with_timezone(&Utc)
            )
        );
        assert_eq!(entry.message, "slow start");
        assert_eq!(entry.service_name.as_deref(), Some("api"));
        assert_eq!(entry.thread_id.as_deref(), Some("api-001"));
    }

    #[test]
    fn test_logfmt_level_word_inside_a_value_is_not_the_level() {
        // Only the words before the first pair can name the level; a value that happens to
        // contain "error" does not, and a level key wins over a leading word.
        let parser = LogParser::new("test.log");

        let entry = parser
            .parse_line(14, r#"service=api msg="error budget is fine" user=bob"#)
            .unwrap();
        assert_eq!(entry.format, LogFormat::Logfmt);
        assert_eq!(entry.level, Some(LogLevel::Unknown));

        let entry = parser
            .parse_line(15, r#"INFO level=error msg="disk full" host=db1"#)
            .unwrap();
        assert_eq!(entry.level, Some(LogLevel::Error));
    }

    #[test]
    fn test_logfmt_words_that_parse_as_non_finite_floats_stay_strings() {
        // "nan", "inf" and "1e999" parse as f64, but JSON has no such number. In a log line
        // they are words (user=nan), so they stay the text they were.
        let parser = LogParser::new("test.log");
        let line = "level=info msg=ok user=nan limit=inf low=-Infinity big=1e999 ratio=1.5 n=7";
        let entry = parser.parse_line(12, line).unwrap();

        assert_eq!(entry.format, LogFormat::Logfmt);
        assert_eq!(entry.level, Some(LogLevel::Info));
        for (key, word) in [
            ("user", "nan"),
            ("limit", "inf"),
            ("low", "-Infinity"),
            ("big", "1e999"),
        ] {
            assert_eq!(
                entry.fields.get(key),
                Some(&Value::String(word.to_string())),
                "field {key} should keep its text"
            );
        }
        assert_eq!(entry.fields.get("ratio"), Some(&serde_json::json!(1.5)));
        assert_eq!(entry.fields.get("n"), Some(&serde_json::json!(7)));
    }

    #[test]
    fn test_syslog_priority_maps_to_error_and_keeps_body() {
        let parser = LogParser::new("test.log");
        let line = "<3>2024-01-15T10:00:00Z host app: critical failure imminent";
        let entry = parser.parse_line(12, line).unwrap();

        assert_eq!(entry.format, LogFormat::Syslog);
        assert_eq!(entry.level, Some(LogLevel::Error));
        assert!(entry.message.contains("critical failure imminent"));
    }

    #[test]
    fn test_bsd_syslog_detected_as_syslog() {
        let line =
            "Mar 15 03:00:00 host sshd[1234]: Failed password for root from 10.0.0.1 port 22";
        let format = LogParser::detect_format(line);
        assert_eq!(format, LogFormat::Syslog);
    }

    #[test]
    fn test_bsd_syslog_infers_error_level() {
        let parser = LogParser::new("test.log");
        let line =
            "Mar 15 03:00:00 host sshd[1234]: Failed password for root from 10.0.0.1 port 22";
        let entry = parser.parse_line(1, line).unwrap();

        assert_eq!(entry.format, LogFormat::Syslog);
        assert_eq!(entry.level, Some(LogLevel::Error));
        assert!(entry.message.contains("Failed password"));
    }

    #[test]
    fn test_bsd_syslog_infers_fatal_for_oom() {
        let parser = LogParser::new("test.log");
        let line = "Mar 15 03:00:00 host kernel: Out of memory: Kill process 1234 (java)";
        let entry = parser.parse_line(1, line).unwrap();

        assert_eq!(entry.format, LogFormat::Syslog);
        assert_eq!(entry.level, Some(LogLevel::Fatal));
    }

    #[test]
    fn test_bsd_syslog_infers_info_for_session() {
        let parser = LogParser::new("test.log");
        let line = "Mar 15 03:00:00 host sshd[1234]: Accepted publickey for user from 10.0.0.1";
        let entry = parser.parse_line(1, line).unwrap();

        assert_eq!(entry.format, LogFormat::Syslog);
        assert_eq!(entry.level, Some(LogLevel::Info));
    }

    #[test]
    fn test_bsd_syslog_infers_warn_for_stopping() {
        let parser = LogParser::new("test.log");
        let line = "Mar 15 03:00:00 host systemd[1]: Stopping nginx.service";
        let entry = parser.parse_line(1, line).unwrap();

        assert_eq!(entry.format, LogFormat::Syslog);
        assert_eq!(entry.level, Some(LogLevel::Warn));
    }

    #[test]
    fn test_bsd_syslog_cron_gets_info() {
        let parser = LogParser::new("test.log");
        let line = "Mar 15 03:00:00 host CRON[5678]: (root) CMD (/usr/bin/cleanup)";
        let entry = parser.parse_line(1, line).unwrap();

        assert_eq!(entry.format, LogFormat::Syslog);
        assert_eq!(entry.level, Some(LogLevel::Info));
    }

    #[test]
    fn test_infer_syslog_level_patterns() {
        // Fatal
        assert_eq!(
            LogParser::infer_syslog_level("kernel: Out of memory: Kill process 123"),
            Some(LogLevel::Fatal)
        );
        assert_eq!(
            LogParser::infer_syslog_level("kernel: segfault at 0000000"),
            Some(LogLevel::Fatal)
        );
        // Error
        assert_eq!(
            LogParser::infer_syslog_level("sshd[1]: Failed password for root"),
            Some(LogLevel::Error)
        );
        assert_eq!(
            LogParser::infer_syslog_level("sshd[1]: authentication failure; user=nobody"),
            Some(LogLevel::Error)
        );
        assert_eq!(
            LogParser::infer_syslog_level("sshd[1]: Invalid user admin from 10.0.0.1"),
            Some(LogLevel::Error)
        );
        // Warn
        assert_eq!(
            LogParser::infer_syslog_level("systemd[1]: Stopping nginx.service"),
            Some(LogLevel::Warn)
        );
        // Info
        assert_eq!(
            LogParser::infer_syslog_level("sshd[1]: Accepted publickey for user"),
            Some(LogLevel::Info)
        );
        assert_eq!(
            LogParser::infer_syslog_level("CRON[5678]: (root) CMD (/usr/bin/cleanup)"),
            Some(LogLevel::Info)
        );
        // No match
        assert_eq!(
            LogParser::infer_syslog_level("some random message with no pattern"),
            None
        );
    }

    #[test]
    fn test_common_log_detection_includes_status_field() {
        let parser = LogParser::new("test.log");
        let line = r#"10.0.0.1 - - [10/Oct/2000:13:55:36 -0700] "POST /submit HTTP/1.1" 503 123"#;
        let entry = parser.parse_line(13, line).unwrap();

        assert_eq!(entry.format, LogFormat::CommonLog);
        assert_eq!(entry.level, Some(LogLevel::Error));
        assert_eq!(
            entry.fields.get("status").and_then(|v| v.as_u64()),
            Some(503)
        );
    }

    fn parse(line: &str) -> LogEntry {
        LogParser::new("test.log").parse_line(1, line).unwrap()
    }

    fn utc(s: &str) -> Option<DateTime<Utc>> {
        Some(DateTime::parse_from_rfc3339(s).unwrap().with_timezone(&Utc))
    }

    #[test]
    fn test_plain_text_level_words_and_places() {
        let rows: &[(&str, Option<LogLevel>)] = &[
            ("2024-01-01T00:00:00Z trace Message", Some(LogLevel::Trace)),
            ("2024-01-01T00:00:00Z Trace Message", Some(LogLevel::Trace)),
            ("2024-01-01T00:00:00Z warn Message", Some(LogLevel::Warn)),
            ("2024-01-01T00:00:00Z ERR Message", Some(LogLevel::Error)),
            ("2024-01-01T00:00:00Z CRIT Message", Some(LogLevel::Fatal)),
            (
                "2024-01-01T00:00:00Z INFORMATION Message",
                Some(LogLevel::Info),
            ),
            (
                "2024-01-15 10:00:00,123 error cannot open file",
                Some(LogLevel::Error),
            ),
            ("2024-01-15 10:00:00 - info - started", Some(LogLevel::Info)),
            (
                "10:30:00.123 [info] Application myapp started",
                Some(LogLevel::Info),
            ),
            (
                "2024/01/15 10:00:00 [error] 1234#0: *1 connect() failed",
                Some(LogLevel::Error),
            ),
            ("warning: unused variable", Some(LogLevel::Warn)),
            ("Something happened ERROR occurred", Some(LogLevel::Error)),
            (
                "INFORMATION about DEBUGGING the ERROR in WARNING systems",
                Some(LogLevel::Info),
            ),
            ("2024-01-01T00:00:00Z Just a message", None),
            ("Loading user info for bob", None),
            ("no error found in 3 files", None),
            ("Server returned error NXDOMAIN", None),
            ("stack trace follows", None),
            ("2024-01-01T00:00:00Z [worker-1] fetching debug info", None),
            (
                "[2024-01-15 10:00:00] error something broke",
                Some(LogLevel::Error),
            ),
            (
                "[2024-01-15T10:00:00.123Z] info: started",
                Some(LogLevel::Info),
            ),
            ("[2024-01-15 10:00:00 worker] error in a sentence", None),
            ("x 2024-01-15 10:00:00 error in a sentence", None),
        ];
        for (line, expected) in rows {
            assert_eq!(parse(line).level, *expected, "level of {line:?}");
        }
    }

    #[test]
    fn test_bracketed_level_word_is_never_the_thread_id() {
        let entry = parse("2024-01-01 10:00:00 [INFO] started");
        assert_eq!(entry.level, Some(LogLevel::Info), "level of [INFO] line");
        assert_eq!(entry.thread_id, None, "thread id of [INFO] line");

        let entry = parse("2024-01-01 10:00:00 [INFO] [worker-1] started");
        assert_eq!(entry.level, Some(LogLevel::Info), "level of two brackets");
        assert_eq!(
            entry.thread_id.as_deref(),
            Some("worker-1"),
            "thread id of two brackets"
        );
    }

    #[test]
    fn test_json_and_logfmt_read_one_list_of_keys_per_field() {
        let json_levels = [
            (r#"{"loglevel": "error", "message": "test"}"#, "loglevel"),
            (r#"{"lvl": "error", "message": "test"}"#, "lvl"),
        ];
        for (line, what) in json_levels {
            assert_eq!(parse(line).level, Some(LogLevel::Error), "level of {what}");
        }

        let entry = parse(r#"{"level": "err", "content": "disk full"}"#);
        assert_eq!(entry.level, Some(LogLevel::Error), "level of err");
        assert_eq!(entry.message, "disk full", "message from content");

        let entry = parse(r#"{"datetime": "2024-01-15T10:00:00Z", "msg": "x"}"#);
        assert_eq!(entry.timestamp, utc("2024-01-15T10:00:00Z"), "datetime key");

        let entry = parse(r#"{"requestId": "r-9", "msg": "x"}"#);
        assert_eq!(entry.correlation_id.as_deref(), Some("r-9"), "requestId");
        assert!(
            !entry.fields.contains_key("requestId"),
            "requestId must not stay in fields: {:?}",
            entry.fields
        );

        let line = r#"ts=2024-01-15T10:00:00Z severity=warning tid=api-7 requestId=r-9 msg="slow""#;
        let entry = parse(line);
        assert_eq!(entry.format, LogFormat::Logfmt, "format of logfmt row");
        assert_eq!(entry.level, Some(LogLevel::Warn), "logfmt level");
        assert_eq!(entry.thread_id.as_deref(), Some("api-7"), "logfmt thread");
        assert_eq!(
            entry.correlation_id.as_deref(),
            Some("r-9"),
            "logfmt correlation"
        );
        assert_eq!(entry.message, "slow", "logfmt message");

        let entry = parse("2024-01-15T10:00:00Z INFO time=12ms user=bob");
        assert_eq!(entry.level, Some(LogLevel::Info), "prefix level");
        assert_eq!(
            entry.timestamp,
            utc("2024-01-15T10:00:00Z"),
            "12ms is no timestamp, the prefix is read"
        );
    }

    #[test]
    fn test_an_id_that_is_a_number_is_still_an_id() {
        let entry = parse(r#"{"tid": 1234, "msg": "x"}"#);
        assert_eq!(entry.thread_id.as_deref(), Some("1234"), "json number tid");

        let entry = parse(r#"level=info thread=7 msg="x""#);
        assert_eq!(
            entry.thread_id.as_deref(),
            Some("7"),
            "logfmt number thread"
        );

        let entry = parse(r#"level=info trace_id=0012345678901234 span_id=00000042 msg="x""#);
        assert_eq!(
            entry.trace_id.as_deref(),
            Some("0012345678901234"),
            "trace id keeps its zeros"
        );
        assert_eq!(
            entry.span_id.as_deref(),
            Some("00000042"),
            "span id keeps its zeros"
        );
    }

    #[test]
    fn test_an_all_zero_trace_span_or_parent_span_id_is_no_id() {
        let zero32 = "0".repeat(32);
        let zero16 = "0".repeat(16);
        let none = (None, None, None);
        let ids = |entry: &LogEntry| {
            (
                entry.trace_id.clone(),
                entry.span_id.clone(),
                entry.parent_span_id.clone(),
            )
        };

        let entry = parse(&format!(
            r#"{{"msg":"x","trace_id":"{zero32}","span_id":"{zero16}","parent_span_id":"{zero16}"}}"#
        ));
        assert_eq!(ids(&entry), none, "json");

        let entry = parse(&format!(
            r#"level=info trace_id={zero32} span_id={zero16} parent_span_id={zero16} msg="x""#
        ));
        assert_eq!(ids(&entry), none, "logfmt");

        let entry = parse(&format!(
            "2024-01-01 00:00:00 INFO trace_id={zero32} span_id={zero16} hello"
        ));
        assert_eq!(ids(&entry), none, "plain");

        let entry = parse(&format!(
            r#"{{"msg":"x","trace_id":"ab12ab12ab12ab12","span_id":"{zero16}","parent_span_id":"0"}}"#
        ));
        assert_eq!(
            ids(&entry),
            (
                Some("ab12ab12ab12ab12".to_string()),
                None,
                Some("0".to_string())
            ),
            "a real trace id stays; a single zero is not the zero id"
        );
    }

    /// Every spelling `read_timestamp` takes names the instant chrono reads from the RFC 3339
    /// spelling of the same fields, and what chrono refuses there (month 13, 30 February,
    /// hour 24, a zone past a day) is refused in every spelling.
    #[test]
    fn test_read_timestamp_agrees_with_chrono_in_every_spelling() {
        let dates = [
            "2024-01-15",
            "2024-02-29",
            "2023-02-29",
            "2024-13-01",
            "2024-00-10",
            "2024-04-31",
            "0001-01-01",
            "9999-12-31",
        ];
        let times = [
            "00:00:00", "10:00:00", "23:59:59", "23:59:60", "10:30:60", "24:00:00", "10:60:00",
            "10:00:61",
        ];
        let fractions = ["", ".5", ".123", ".123456789", ".1234567891234"];
        let zones = [
            "Z", "+00:00", "+09:00", "-05:30", "+23:59", "+24:00", "-00:00", "+09:60",
        ];
        let (mut read, mut refused) = (0, 0);
        for date in dates {
            for time in times {
                for fraction in fractions {
                    for zone in zones {
                        let rfc3339 = format!("{date}T{time}{fraction}{zone}");
                        let expected = DateTime::parse_from_rfc3339(&rfc3339)
                            .ok()
                            .map(|dt| dt.with_timezone(&Utc));
                        match expected {
                            Some(_) => read += 1,
                            None => refused += 1,
                        }
                        let mut spellings = vec![
                            rfc3339.clone(),
                            rfc3339.replace('T', " "),
                            rfc3339.replace('T', "t"),
                            rfc3339.replace('.', ","),
                            format!("{date}T{time}{fraction}{}", zone.replace(':', "")),
                            format!("{date} {time}{fraction} {zone}"),
                            format!("  {rfc3339}  "),
                        ];
                        if zone == "Z" {
                            spellings.extend([
                                format!("{date}T{time}{fraction}"),
                                format!("{date} {time}{fraction}z"),
                            ]);
                        }
                        for spelling in spellings {
                            assert_eq!(read_timestamp(&spelling), expected, "{spelling:?}");
                        }
                    }
                }
            }
        }
        assert_eq!(
            (read, refused),
            (600, 1960),
            "how many of the table chrono reads"
        );
    }

    #[test]
    fn test_read_timestamp_refuses_any_other_shape() {
        for text in [
            "",
            "2024-01-15",
            "2024-01-15T10:00",
            "2024-01-1510:00:00",
            "2024-01-15_10:00:00",
            "2024-1-15 10:00:00",
            "2024-01-15 1:00:00",
            "24-01-15 10:00:00",
            "2024/01/15 10:00:00",
            "2024-01-15 10:00:00.",
            "2024-01-15 10:00:00.x",
            "2024-01-15 10:00:00+09",
            "2024-01-15 10:00:00+9:00",
            "2024-01-15 10:00:00+09:00x",
            "2024-01-15 10:00:00 UTC",
            "2024-01-15 10:00:00 tomorrow",
            "+024-01-15 10:00:00",
            "２０２４-01-15 10:00:00",
            "2024-01-15 10:00:00\u{3000}Z",
        ] {
            assert_eq!(read_timestamp(text), None, "{text:?}");
        }
    }

    #[test]
    fn test_one_reader_for_timestamp_strings() {
        let rows: &[(&str, &str)] = &[
            (
                r#"{"timestamp": "2024-01-15 10:00:00", "msg": "x"}"#,
                "2024-01-15T10:00:00Z",
            ),
            (
                r#"{"timestamp": "2024-01-15T10:00:00", "msg": "x"}"#,
                "2024-01-15T10:00:00Z",
            ),
            (
                r#"{"time": "2024-01-15 10:00:00,123", "msg": "x"}"#,
                "2024-01-15T10:00:00.123Z",
            ),
            (
                r#"{"ts": "2024-01-15T19:00:00+0900", "msg": "x"}"#,
                "2024-01-15T10:00:00Z",
            ),
            (
                "2024-01-15 10:00:00.123 INFO started",
                "2024-01-15T10:00:00.123Z",
            ),
            (
                "2024-01-15 10:00:00,123 INFO started",
                "2024-01-15T10:00:00.123Z",
            ),
            (
                r#"ts="2024-01-15 10:00:00" level=info msg="x""#,
                "2024-01-15T10:00:00Z",
            ),
            (
                r#"{"ts": "2024-01-15 19:00:00+09:00", "msg": "x"}"#,
                "2024-01-15T10:00:00Z",
            ),
            (
                r#"{"ts": "2024-01-15 19:00:00.250+0900", "msg": "x"}"#,
                "2024-01-15T10:00:00.250Z",
            ),
            (
                r#"{"ts": "2024-01-15 10:00:00Z", "msg": "x"}"#,
                "2024-01-15T10:00:00Z",
            ),
            (
                r#"{"ts": "2024-01-15T05:00:00.5-05:00", "msg": "x"}"#,
                "2024-01-15T10:00:00.5Z",
            ),
            (
                "2024-01-15 05:00:00-0500 INFO started",
                "2024-01-15T10:00:00Z",
            ),
        ];
        for (line, expected) in rows {
            assert_eq!(parse(line).timestamp, utc(expected), "timestamp of {line}");
        }
        for line in [
            r#"{"timestamp": "not a time", "msg": "x"}"#,
            r#"{"timestamp": "時刻ではない文字列です、ほんとうに", "msg": "x"}"#,
            r#"{"timestamp": "2024-01-15 10:00:00 tomorrow", "msg": "x"}"#,
        ] {
            assert_eq!(parse(line).timestamp, None, "no timestamp in {line}");
        }

        let regex = Regex::new(r"^(?P<timestamp>\S+ \S+) (?P<message>.*)$").unwrap();
        let custom = LogParser::with_custom_regex("test.log", regex);
        let entry = custom.parse_line(1, "15-01-2024 10:00:00 hello").unwrap();
        assert_eq!(
            entry.timestamp,
            utc("2024-01-15T10:00:00Z"),
            "custom regex keeps its day-first form"
        );
        let entry = custom.parse_line(1, "2024-01-15 10:00:00,5 hello").unwrap();
        assert_eq!(
            entry.timestamp,
            utc("2024-01-15T10:00:00.5Z"),
            "custom regex reads the shared forms"
        );
        let entry = custom.parse_line(1, "2024-1-5 1:02:03 hello").unwrap();
        assert_eq!(
            entry.timestamp,
            utc("2024-01-05T01:02:03Z"),
            "custom regex keeps fields written without a leading zero"
        );
    }

    #[test]
    fn test_logfmt_thread_in_brackets_before_the_pairs_is_read() {
        let line = "2024-01-01T00:00:00Z INFO [worker-1] correlation_id=req-123 trace_id=abcd1234abcd1234 span_id=efef5678 Database query";
        let entry = parse(line);
        assert_eq!(entry.format, LogFormat::Logfmt, "format");
        assert_eq!(entry.thread_id.as_deref(), Some("worker-1"), "thread id");
        assert_eq!(entry.level, Some(LogLevel::Info), "level");
    }

    #[test]
    fn test_json_epoch_number_is_read_in_the_unit_its_size_tells() {
        let rows: &[(&str, &str)] = &[
            (r#"{"ts": 1705312800, "msg": "x"}"#, "2024-01-15T10:00:00Z"),
            (
                r#"{"time": 1705312800123, "msg": "x"}"#,
                "2024-01-15T10:00:00.123Z",
            ),
            (
                r#"{"time": 1705312800123456, "msg": "x"}"#,
                "2024-01-15T10:00:00.123456Z",
            ),
            (
                r#"{"time": 1705312800123456789, "msg": "x"}"#,
                "2024-01-15T10:00:00.123456789Z",
            ),
            (
                r#"{"ts": 1705312800.25, "msg": "x"}"#,
                "2024-01-15T10:00:00.25Z",
            ),
            (
                r#"{"ts": 1705312800123.5, "msg": "x"}"#,
                "2024-01-15T10:00:00.1235Z",
            ),
            (r#"{"ts": 0, "msg": "x"}"#, "1970-01-01T00:00:00Z"),
            (r#"{"ts": -1, "msg": "x"}"#, "1969-12-31T23:59:59Z"),
            (r#"{"ts": -1500, "msg": "x"}"#, "1969-12-31T23:35:00Z"),
        ];
        for (line, expected) in rows {
            assert_eq!(parse(line).timestamp, utc(expected), "timestamp of {line}");
        }
        for line in [
            r#"{"ts": 1e300, "msg": "x"}"#,
            r#"{"ts": true, "msg": "x"}"#,
        ] {
            assert_eq!(parse(line).timestamp, None, "no timestamp in {line}");
        }
    }

    #[test]
    fn test_json_numeric_level_is_read_from_the_two_tables() {
        let rows: &[(&str, Option<LogLevel>)] = &[
            (r#"{"level": 10, "msg": "x"}"#, Some(LogLevel::Trace)),
            (r#"{"level": 20, "msg": "x"}"#, Some(LogLevel::Debug)),
            (r#"{"level": 30, "msg": "x"}"#, Some(LogLevel::Info)),
            (r#"{"level": 40, "msg": "x"}"#, Some(LogLevel::Warn)),
            (r#"{"level": 50, "msg": "x"}"#, Some(LogLevel::Error)),
            (r#"{"level": 60, "msg": "x"}"#, Some(LogLevel::Fatal)),
            (r#"{"level": 0, "msg": "x"}"#, Some(LogLevel::Fatal)),
            (r#"{"level": 1, "msg": "x"}"#, Some(LogLevel::Fatal)),
            (r#"{"level": 2, "msg": "x"}"#, Some(LogLevel::Fatal)),
            (r#"{"level": 3, "msg": "x"}"#, Some(LogLevel::Error)),
            (r#"{"level": 4, "msg": "x"}"#, Some(LogLevel::Warn)),
            (r#"{"level": 5, "msg": "x"}"#, Some(LogLevel::Info)),
            (r#"{"level": 6, "msg": "x"}"#, Some(LogLevel::Info)),
            (r#"{"level": 7, "msg": "x"}"#, Some(LogLevel::Debug)),
            (r#"{"severity": 6, "msg": "x"}"#, Some(LogLevel::Info)),
            // Any other number, a string of digits and a bool are not a level: the entry has none,
            // and counts as UNKNOWN wherever levels are counted.
            (r#"{"level": 8, "msg": "x"}"#, None),
            (r#"{"level": 35, "msg": "x"}"#, None),
            (r#"{"level": 600, "msg": "x"}"#, None),
            (r#"{"level": -1, "msg": "x"}"#, None),
            (r#"{"level": 3.5, "msg": "x"}"#, None),
            (r#"{"level": 30.0, "msg": "x"}"#, None),
            (r#"{"level": 1e3, "msg": "x"}"#, None),
            (r#"{"level": "30", "msg": "x"}"#, Some(LogLevel::Unknown)),
            (r#"{"level": true, "msg": "x"}"#, None),
            (r#"{"level": "warn", "msg": "x"}"#, Some(LogLevel::Warn)),
        ];
        for (line, expected) in rows {
            assert_eq!(parse(line).level, *expected, "{line}");
        }
        // A number that is not a level stays in `fields`; one that is a level is taken.
        assert_eq!(
            parse(r#"{"level": 35}"#).fields.get("level"),
            Some(&serde_json::json!(35))
        );
        assert_eq!(parse(r#"{"level": 30}"#).fields.get("level"), None);
    }

    #[test]
    fn test_json_level_word_beats_a_level_number() {
        // A word in a later key beats a number in an earlier one, and the number stays a field.
        let entry = parse(r#"{"level": 30, "severity": "ERROR"}"#);
        assert_eq!(entry.level, Some(LogLevel::Error), "word after number");
        assert_eq!(entry.fields.get("level"), Some(&serde_json::json!(30)));
        assert_eq!(entry.fields.get("severity"), None);
        let entry = parse(r#"{"level": "warn", "severity": 3}"#);
        assert_eq!(entry.level, Some(LogLevel::Warn), "word before number");
        assert_eq!(entry.fields.get("severity"), Some(&serde_json::json!(3)));
        // Among numbers the first one in the table is read: 35 is no level, 4 is WARN.
        let entry = parse(r#"{"level": 35, "severity": 4, "lvl": 50}"#);
        assert_eq!(
            entry.level,
            Some(LogLevel::Warn),
            "first number in the table"
        );
        assert_eq!(entry.fields.get("level"), Some(&serde_json::json!(35)));
        assert_eq!(entry.fields.get("severity"), None);
        assert_eq!(entry.fields.get("lvl"), Some(&serde_json::json!(50)));
        // Among words the first key wins, as before.
        let entry = parse(r#"{"level": "info", "lvl": "warn"}"#);
        assert_eq!(entry.level, Some(LogLevel::Info), "first word");
        assert_eq!(entry.fields.get("lvl"), Some(&serde_json::json!("warn")));
    }

    #[test]
    fn test_syslog_severities_through_the_one_table() {
        let rows: &[(&str, LogLevel)] = &[
            ("<0>Oct 11 22:14:15 host su: x", LogLevel::Fatal),
            ("<9>Oct 11 22:14:15 host su: x", LogLevel::Fatal),
            ("<10>Oct 11 22:14:15 host su: x", LogLevel::Fatal),
            ("<11>Oct 11 22:14:15 host su: x", LogLevel::Error),
            ("<12>Oct 11 22:14:15 host su: x", LogLevel::Warn),
            ("<13>Oct 11 22:14:15 host su: x", LogLevel::Info),
            ("<14>Oct 11 22:14:15 host su: x", LogLevel::Info),
            ("<15>Oct 11 22:14:15 host su: x", LogLevel::Debug),
            ("<191>Oct 11 22:14:15 host su: x", LogLevel::Debug),
        ];
        for (line, expected) in rows {
            assert_eq!(parse(line).level, Some(*expected), "{line}");
        }
    }

    #[test]
    fn test_json_key_that_was_not_read_stays_in_fields() {
        let entry = parse(
            r#"{"msg": "a", "text": "b", "level": 35, "lvl": "warn", "time": "soon", "ts": 1705312800, "thread": ["x"], "tid": 7, "user": "u1"}"#,
        );
        assert_eq!(entry.message, "a", "message");
        assert_eq!(entry.level, Some(LogLevel::Warn), "level");
        assert_eq!(entry.timestamp, utc("2024-01-15T10:00:00Z"), "timestamp");
        assert_eq!(entry.thread_id.as_deref(), Some("7"), "thread id");
        let expected: HashMap<String, Value> = serde_json::from_str(
            r#"{"text": "b", "level": 35, "time": "soon", "thread": ["x"], "user": "u1"}"#,
        )
        .unwrap();
        assert_eq!(entry.fields, expected, "fields");
    }

    #[test]
    fn test_custom_regex_reads_every_named_group() {
        let plc = Regex::new(
            r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\|(?P<level>\w+)\|(?P<station>[\w-]+)\|(?P<message>.*)$",
        )
        .unwrap();
        let robot = Regex::new(r"^(?P<lvl>\w+);(?P<axis>\d+);(?P<msg>.*)$").unwrap();
        let ids = Regex::new(
            r"^(?P<request_id>\S+) (?P<threadName>\S+) (?P<level>\S+) (?P<user>\S+)?(?P<note>x)?$",
        )
        .unwrap();
        let stamped = Regex::new(r"^(?P<timestamp>\S+) (?P<message>.*)$").unwrap();
        let fields = |pairs: &[(&str, &str)]| -> HashMap<String, Value> {
            pairs
                .iter()
                .map(|(k, v)| (k.to_string(), Value::String(v.to_string())))
                .collect()
        };

        // (regex, line, format, level, timestamp, message, thread, correlation, fields)
        #[allow(clippy::type_complexity)]
        let rows: Vec<(
            &Regex,
            &str,
            LogFormat,
            Option<LogLevel>,
            Option<&str>,
            &str,
            Option<&str>,
            Option<&str>,
            HashMap<String, Value>,
        )> = vec![
            (
                &plc,
                "2024-01-15 10:00:00|warn|ST-07|pressure low",
                LogFormat::Custom,
                Some(LogLevel::Warn),
                Some("2024-01-15T10:00:00Z"),
                "pressure low",
                None,
                None,
                fields(&[("station", "ST-07")]),
            ),
            (
                &plc,
                "2024-01-15 10:00:01|error|ST-07|valve stuck",
                LogFormat::Custom,
                Some(LogLevel::Error),
                Some("2024-01-15T10:00:01Z"),
                "valve stuck",
                None,
                None,
                fields(&[("station", "ST-07")]),
            ),
            (
                &plc,
                "2024-01-15 10:00:02 INFO a plain line in a plc file",
                LogFormat::PlainText,
                Some(LogLevel::Info),
                Some("2024-01-15T10:00:02Z"),
                "2024-01-15 10:00:02 INFO a plain line in a plc file",
                None,
                None,
                HashMap::new(),
            ),
            (
                &robot,
                "error;3;overtravel",
                LogFormat::Custom,
                Some(LogLevel::Error),
                None,
                "overtravel",
                None,
                None,
                fields(&[("axis", "3")]),
            ),
            (
                &robot,
                "info;1;homed",
                LogFormat::Custom,
                Some(LogLevel::Info),
                None,
                "homed",
                None,
                None,
                fields(&[("axis", "1")]),
            ),
            (
                &ids,
                "req-9 pool-3 bogus bob",
                LogFormat::Custom,
                // A word that names no level reads as Unknown, as in the JSON branch.
                Some(LogLevel::Unknown),
                None,
                "req-9 pool-3 bogus bob",
                Some("pool-3"),
                Some("req-9"),
                // `note` did not take part in the match: it is absent.
                fields(&[("user", "bob")]),
            ),
            (
                &stamped,
                "notatime hi",
                LogFormat::Custom,
                None,
                None,
                "hi",
                None,
                None,
                // A listed group whose value could not be read is kept as captured.
                fields(&[("timestamp", "notatime")]),
            ),
        ];
        for (regex, line, format, level, timestamp, message, thread, correlation, expected) in rows
        {
            let entry = LogParser::with_custom_regex("test.log", regex.clone())
                .parse_line(1, line)
                .unwrap();
            assert_eq!(entry.format, format, "format of {line}");
            assert_eq!(entry.level, level, "level of {line}");
            assert_eq!(
                entry.timestamp,
                timestamp.and_then(utc),
                "timestamp of {line}"
            );
            assert_eq!(entry.message, message, "message of {line}");
            assert_eq!(entry.thread_id.as_deref(), thread, "thread of {line}");
            assert_eq!(
                entry.correlation_id.as_deref(),
                correlation,
                "correlation id of {line}"
            );
            assert_eq!(entry.fields, expected, "fields of {line}");
        }
    }

    #[test]
    fn test_zone_after_a_space_is_the_timestamps_zone() {
        // (line, timestamp, level): a numeric offset after one space, then a space or the
        // end of the line, belongs to the timestamp; the level is read after it.
        let rows: &[(&str, &str, Option<LogLevel>)] = &[
            (
                "2024-01-15 10:00:00 +0900 INFO started",
                "2024-01-15T01:00:00Z",
                Some(LogLevel::Info),
            ),
            (
                "2024-01-15 10:00:00 +09:00 INFO started",
                "2024-01-15T01:00:00Z",
                Some(LogLevel::Info),
            ),
            (
                "2024-01-15 10:00:00 -0500 WARN started",
                "2024-01-15T15:00:00Z",
                Some(LogLevel::Warn),
            ),
            (
                "2024-01-15 10:00:00 +0900 info started",
                "2024-01-15T01:00:00Z",
                Some(LogLevel::Info),
            ),
            (
                "2024-01-15 10:00:00.123 +0530 ERROR started",
                "2024-01-15T04:30:00.123Z",
                Some(LogLevel::Error),
            ),
            (
                "2024-01-15T10:00:00,5 -03:30 started",
                "2024-01-15T13:30:00.5Z",
                None,
            ),
            ("2024-01-15 10:00:00 +0900", "2024-01-15T01:00:00Z", None),
            (
                "2024-01-15 10:00:00.250 +05:45",
                "2024-01-15T04:15:00.250Z",
                None,
            ),
            (
                "2024-01-15 10:00:00 +1400 INFO a",
                "2024-01-14T20:00:00Z",
                Some(LogLevel::Info),
            ),
            // `+0100 items` is read as the zone: a real offset and then a space.
            (
                "2024-01-15 10:00:00 +0100 items",
                "2024-01-15T09:00:00Z",
                None,
            ),
            // A zone written with no space is the zone as before.
            (
                "2024-01-15 10:00:00+0900 INFO a",
                "2024-01-15T01:00:00Z",
                Some(LogLevel::Info),
            ),
            // A zone twice: the first is the timestamp's, the second is message.
            (
                "2024-01-15 10:00:00 +0900 +0100 INFO a",
                "2024-01-15T01:00:00Z",
                Some(LogLevel::Info),
            ),
            (
                "2024-01-15 10:00:00Z +0900 INFO a",
                "2024-01-15T10:00:00Z",
                Some(LogLevel::Info),
            ),
            // A timestamp in brackets: the offset ends at the bracket, the level follows it.
            (
                "[2024-01-15 10:00:00 +0900] warn started",
                "2024-01-15T01:00:00Z",
                Some(LogLevel::Warn),
            ),
            (
                "[2024-01-15 10:00:00.5 -05:00] started",
                "2024-01-15T15:00:00.5Z",
                None,
            ),
            // A timestamp that does not lead the line.
            (
                "started at 2024-01-15 10:00:00 +0900 by INFO desk",
                "2024-01-15T01:00:00Z",
                Some(LogLevel::Info),
            ),
        ];
        for (line, timestamp, level) in rows {
            let entry = LogParser::new("test.log").parse_line(1, line).unwrap();
            assert_eq!(entry.timestamp, utc(timestamp), "timestamp of {line}");
            assert_eq!(entry.level, *level, "level of {line}");
            assert_eq!(entry.message, *line, "message of {line}");
            assert_eq!(entry.format, LogFormat::PlainText, "format of {line}");
        }
    }

    #[test]
    fn test_zone_after_a_space_leads_a_logfmt_line_too() {
        let line = "2024-01-15 10:00:00 +0900 level=info msg=started";
        let entry = LogParser::new("test.log").parse_line(1, line).unwrap();
        assert_eq!(entry.format, LogFormat::Logfmt);
        assert_eq!(entry.timestamp, utc("2024-01-15T01:00:00Z"));
        assert_eq!(entry.level, Some(LogLevel::Info));
        assert_eq!(entry.message, "started");
    }

    #[test]
    fn test_a_digit_that_is_not_ascii_in_the_time_is_no_timestamp() {
        // The pattern's `\d` takes any Unicode digit, so the text it finds is not always
        // 19 bytes of ASCII: byte 19 can fall inside a letter.
        for line in [
            "2024-01-15 10:00:0\u{0660} INFO x",
            "2024-01-15 10:00:\u{0966}0 +0900 INFO x",
            "\u{ff12}024-01-15 10:00:00 INFO x",
        ] {
            let entry = LogParser::new("test.log").parse_line(1, line).unwrap();
            assert_eq!(entry.timestamp, None, "timestamp of {line}");
            assert_eq!(entry.level, Some(LogLevel::Info), "level of {line}");
            assert_eq!(entry.message, line, "message of {line}");
        }
    }

    #[test]
    fn test_text_after_the_seconds_that_is_no_zone_stays_message() {
        let rows: &[&str] = &[
            "2024-01-15 10:00:00 -1234 widgets left",
            "2024-01-15 10:00:00 +9 retries",
            "2024-01-15 10:00:00 -0500ms",
            "2024-01-15 10:00:00 +0900x INFO a",
            "2024-01-15 10:00:00 +1500 INFO a",
            "2024-01-15 10:00:00 +0910 INFO a",
            "2024-01-15 10:00:00  +0900 INFO a",
            "2024-01-15 10:00:00 +09:0 INFO a",
        ];
        for line in rows {
            let entry = LogParser::new("test.log").parse_line(1, line).unwrap();
            assert_eq!(
                entry.timestamp,
                utc("2024-01-15T10:00:00Z"),
                "timestamp of {line}"
            );
            assert_eq!(entry.message, *line, "message of {line}");
        }
        let entry = LogParser::new("test.log")
            .parse_line(1, "2024-01-15 10:00:00 -1234 widgets left")
            .unwrap();
        assert_eq!(
            entry.level, None,
            "level of a line with a count after the time"
        );
    }

    #[test]
    fn test_utc_and_gmt_after_the_seconds_read_as_they_did() {
        // Pins head: the time has no zone word and is UTC already, and the level is found.
        for zone in ["UTC", "GMT"] {
            let parser = LogParser::new("test.log");
            let line = format!("2024-01-15 10:00:00 {zone} INFO started");
            let entry = parser.parse_line(1, &line).unwrap();
            assert_eq!(entry.timestamp, utc("2024-01-15T10:00:00Z"), "{line}");
            assert_eq!(entry.level, Some(LogLevel::Info), "{line}");
            assert_eq!(entry.message, line, "{line}");
        }
    }

    #[test]
    fn test_json_line_edge_shapes() {
        let parser = LogParser::new("test.log");

        let entry = parser.parse_line(1, "{not json").unwrap();
        assert_eq!(entry.format, LogFormat::PlainText, "format of {{not json");
        assert_eq!(entry.message, "{not json");
        assert_eq!(entry.level, None);

        let line = r#"{"a":1} trailing"#;
        let entry = parser.parse_line(1, line).unwrap();
        assert_eq!(entry.format, LogFormat::PlainText, "format of {line}");
        assert_eq!(entry.message, line);
        assert!(
            entry.fields.is_empty(),
            "no fields from a line that is no JSON"
        );

        let entry = parser.parse_line(1, "{}").unwrap();
        assert_eq!(entry.format, LogFormat::Json, "format of {{}}");
        assert_eq!(entry.message, "{}", "message of an empty object");
        assert!(entry.fields.is_empty(), "fields of an empty object");

        let line = r#"  {"level":"ERROR"}  "#;
        let entry = parser.parse_line(1, line).unwrap();
        assert_eq!(entry.format, LogFormat::Json, "format of {line}");
        assert_eq!(entry.level, Some(LogLevel::Error));
        assert_eq!(entry.raw, line, "raw keeps the spaces");
        assert_eq!(entry.message, r#"{"level":"ERROR"}"#);
        assert!(entry.fields.is_empty(), "the level key is taken");

        // A line that starts with `{` and is logfmt after it is not JSON.
        let line = "{ level=info msg=hello";
        let entry = parser.parse_line(1, line).unwrap();
        assert_eq!(entry.format, LogFormat::Logfmt, "format of {line}");
        assert_eq!(entry.level, Some(LogLevel::Info));
        assert_eq!(entry.message, "hello");

        let text = "x".repeat(1_000_000);
        let line = format!(r#"{{"level":"INFO","message":"{text}","n":7}}"#);
        let entry = parser.parse_line(1, &line).unwrap();
        assert_eq!(entry.format, LogFormat::Json, "format of a 1 MB line");
        assert_eq!(entry.message.len(), 1_000_000, "message of a 1 MB line");
        assert_eq!(entry.fields.get("n"), Some(&Value::from(7)));
        assert_eq!(LogParser::detect_format(&line), LogFormat::Json);
    }

    #[test]
    fn test_detect_format_answers_for_each_shape() {
        let rows: &[(&str, LogFormat)] = &[
            (r#"{"a":1}"#, LogFormat::Json),
            (r#"  {"a":1}  "#, LogFormat::Json),
            ("{not json", LogFormat::PlainText),
            ("<34>Oct 11 22:14:15 host su: x", LogFormat::Syslog),
            ("  <34>Oct 11 22:14:15 host su: x", LogFormat::Syslog),
            ("Mar 15 03:00:00 host sshd[1]: x", LogFormat::Syslog),
            (
                r#"127.0.0.1 - - [10/Oct/2000:13:55:36 -0700] "GET / HTTP/1.0" 200 2326"#,
                LogFormat::CommonLog,
            ),
            ("a=1 b=2", LogFormat::Logfmt),
            ("a=1", LogFormat::PlainText),
            ("[x] no equals", LogFormat::PlainText),
            ("Mar 15 03:00:00 host x", LogFormat::PlainText),
            ("", LogFormat::PlainText),
        ];
        for (line, format) in rows {
            assert_eq!(LogParser::detect_format(line), *format, "format of {line}");
            let entry = LogParser::new("test.log").parse_line(1, line).unwrap();
            assert_eq!(entry.format, *format, "parsed format of {line}");
        }
    }

    fn compiled(format: &str) -> TimestampFormat {
        TimestampFormat::compile(format).unwrap_or_else(|e| panic!("{format}: {e}"))
    }

    /// Each row: a format in Python's strptime words, the text of the timestamp group, and the
    /// instant Python's `datetime.strptime` reads (UTC when the format has no `%z`); `None`
    /// where Python refuses the text. Two rows differ from Python on purpose, as every other
    /// timestamp in logler does: a second 60 is a leap second, and a digit is an ASCII digit.
    #[test]
    fn test_timestamp_format_reads_as_python_strptime_does() {
        let rows: &[(&str, &str, Option<&str>)] = &[
            (
                "%d.%m.%Y %H:%M:%S",
                "31.12.2024 23:59:58",
                Some("2024-12-31T23:59:58Z"),
            ),
            (
                "%Y-%m-%d %H:%M:%S,%f",
                "2024-01-15 10:00:00,123",
                Some("2024-01-15T10:00:00.123Z"),
            ),
            (
                "%Y-%m-%d %H:%M:%S,%f",
                "2024-01-15 10:00:00,123456",
                Some("2024-01-15T10:00:00.123456Z"),
            ),
            (
                "%Y-%m-%d %H:%M:%S,%f",
                "2024-01-15 10:00:00,5",
                Some("2024-01-15T10:00:00.5Z"),
            ),
            ("%Y-%m-%d %H:%M:%S,%f", "2024-01-15 10:00:00,1234567", None),
            (
                "%y%m%d %H%M%S",
                "690115 100000",
                Some("1969-01-15T10:00:00Z"),
            ),
            (
                "%y%m%d %H%M%S",
                "680115 100000",
                Some("2068-01-15T10:00:00Z"),
            ),
            (
                "%d/%b/%Y:%H:%M:%S %z",
                "10/Oct/2024:13:55:36 -0700",
                Some("2024-10-10T20:55:36Z"),
            ),
            (
                "%d/%b/%Y:%H:%M:%S %z",
                "10/oct/2024:13:55:36 -0700",
                Some("2024-10-10T20:55:36Z"),
            ),
            (
                "%d/%b/%Y:%H:%M:%S %z",
                "10/OCT/2024:13:55:36 -0700",
                Some("2024-10-10T20:55:36Z"),
            ),
            (
                "%B %d %Y %H:%M",
                "september 5 2024 10:30",
                Some("2024-09-05T10:30:00Z"),
            ),
            (
                "%Y-%m-%d %H:%M:%S%z",
                "2024-01-15 10:00:00+0900",
                Some("2024-01-15T01:00:00Z"),
            ),
            (
                "%Y-%m-%d %H:%M:%S%z",
                "2024-01-15 10:00:00+09:00",
                Some("2024-01-15T01:00:00Z"),
            ),
            (
                "%Y-%m-%d %H:%M:%S%z",
                "2024-01-15 10:00:00-05:30",
                Some("2024-01-15T15:30:00Z"),
            ),
            (
                "%Y-%m-%d %H:%M:%S%z",
                "2024-01-15 10:00:00Z",
                Some("2024-01-15T10:00:00Z"),
            ),
            ("%Y-%m-%d %H:%M:%S%z", "2024-01-15 10:00:00z", None),
            ("%Y-%m-%d %H:%M:%S%z", "2024-01-15 10:00:00+09", None),
            ("%Y-%m-%d %H:%M:%S%z", "2024-01-15 10:00:00+0960", None),
            (
                "100%% %Y-%m-%d",
                "100% 2024-01-15",
                Some("2024-01-15T00:00:00Z"),
            ),
            ("%Y-%m-%d %H:%M:%S", "2024-01-15 10:00:00 and more", None),
            ("%Y-%m-%d %H:%M", "2024-01-15 10:00:00", None),
            ("%d.%m.%Y", "31.02.2024", None),
            ("%d.%m.%Y", "29.02.2024", Some("2024-02-29T00:00:00Z")),
            (
                "%d.%m.%Y %H:%M:%S",
                "31.12.2016 23:59:60",
                Some("2016-12-31T23:59:60Z"),
            ),
            ("%d.%m.%Y %H:%M:%S", "31.12.2016 23:59:61", None),
            (
                "%Y-%m-%dT%H:%M:%S",
                "2024-01-15t10:00:00",
                Some("2024-01-15T10:00:00Z"),
            ),
            (
                "%Y-%m-%d  %H:%M",
                "2024-01-15 10:00",
                Some("2024-01-15T10:00:00Z"),
            ),
            (
                "%Y-%m-%d %H:%M",
                "2024-01-15\t \t10:00",
                Some("2024-01-15T10:00:00Z"),
            ),
            ("%d.%m.%Y", "5.1.2024", Some("2024-01-05T00:00:00Z")),
            ("%d.%m.%Y", " 5.1.2024", Some("2024-01-05T00:00:00Z")),
            ("%b %d %Y", "Jan  5 2024", Some("2024-01-05T00:00:00Z")),
            ("%m%d%Y", "1102024", Some("2024-01-10T00:00:00Z")),
            ("%Y-%m-%d", "２０２４-01-15", None),
            (
                "(%Y) [%m] {%d} a.b*c",
                "(2024) [01] {15} a.b*c",
                Some("2024-01-15T00:00:00Z"),
            ),
            ("(%Y) [%m] {%d} a.b*c", "(2024) [01] {15} aXb*c", None),
        ];
        for (format, text, expected) in rows {
            assert_eq!(
                compiled(format).read(text),
                expected.and_then(utc),
                "{format:?} reading {text:?}"
            );
        }
    }

    #[test]
    fn test_timestamp_format_refuses_a_word_it_cannot_read_as_python_does() {
        const LOCALE: &str =
            "is read in the machine's language, which differs from machine to machine";
        const OTHER: &str =
            "is not supported; the words read are %Y %y %m %b %B %d %H %M %S %f %z and %%";
        let rows: Vec<(&str, String)> = vec![
            (
                "%Y-%m-%d %H:%M:%S.%f %Z",
                "%Z is not supported: a zone name is read differently from machine to machine; \
                 write the zone as an offset and read it with %z"
                    .to_string(),
            ),
            ("%a %Y-%m-%d", format!("%a {LOCALE}")),
            ("%A %Y-%m-%d", format!("%A {LOCALE}")),
            ("%c", format!("%c {LOCALE}")),
            ("%x", format!("%x {LOCALE}")),
            ("%Y-%m-%d %X", format!("%X {LOCALE}")),
            ("%Y-%m-%d %I:%M %p", format!("%I {OTHER}")),
            ("%Y-%m-%d %H:%M %p", format!("%p {LOCALE}")),
            ("%Y %j", format!("%j {OTHER}")),
            ("%Y-%m-%d %:z", format!("%: {OTHER}")),
            ("%Y-%m-%d %é", format!("%é {OTHER}")),
            (
                "%Y-%m-%d %H:%M:%S %",
                "the format ends in a lone %; write a literal % as %%".to_string(),
            ),
            (
                "%Y %Y-%m-%d",
                "the year is given by two words, %Y and %Y".to_string(),
            ),
            (
                "%y-%m-%d %Y",
                "the year is given by two words, %y and %Y".to_string(),
            ),
            (
                "%Y-%m-%d %b",
                "the month is given by two words, %m and %b".to_string(),
            ),
            (
                "%Y-%m-%d %H:%M:%S %S",
                "the second is given by two words, %S and %S".to_string(),
            ),
            (
                "%Y-%m-%d %z %z",
                "the zone is given by two words, %z and %z".to_string(),
            ),
            (
                "%H:%M:%S",
                "a timestamp needs a date: the format has no year (%Y or %y), no month \
                 (%m, %b or %B) and no day (%d)"
                    .to_string(),
            ),
            (
                "%b %d %H:%M:%S",
                "a timestamp needs a date: the format has no year (%Y or %y)".to_string(),
            ),
            (
                "%Y %H:%M",
                "a timestamp needs a date: the format has no month (%m, %b or %B) and no day (%d)"
                    .to_string(),
            ),
            (
                "",
                "a timestamp needs a date: the format has no year (%Y or %y), no month \
                 (%m, %b or %B) and no day (%d)"
                    .to_string(),
            ),
        ];
        for (format, message) in rows {
            assert_eq!(
                TimestampFormat::compile(format).map(|_| ()),
                Err(message),
                "{format:?}"
            );
        }
    }

    /// A custom line's timestamp group is read by the format first; where the format does not
    /// fit, by the shapes a custom group is read in without one.
    #[test]
    fn test_custom_format_reads_its_group_with_the_timestamp_format_first() {
        let regex = Regex::new(r"^(?P<timestamp>\S+ \S+) (?P<message>.*)$").unwrap();
        let with = |format: &str| {
            ParserConfig::new()
                .with_custom_regex(regex.clone())
                .with_timestamp_format(compiled(format))
                .build_for_file("test.log")
        };
        let without = LogParser::with_custom_regex("test.log", regex.clone());
        let rows: &[(&str, &str, Option<&str>, Option<&str>)] = &[
            // format, line, read with the format, read without it
            (
                "%d.%m.%Y %H:%M:%S",
                "31.12.2024 23:59:58 hello",
                Some("2024-12-31T23:59:58Z"),
                None,
            ),
            (
                "%Y-%d-%m %H:%M:%S",
                "2024-01-02 10:00:00 hello",
                Some("2024-02-01T10:00:00Z"),
                Some("2024-01-02T10:00:00Z"),
            ),
            (
                "%d.%m.%Y %H:%M:%S",
                "2024-01-15 10:00:00 hello",
                Some("2024-01-15T10:00:00Z"),
                Some("2024-01-15T10:00:00Z"),
            ),
            (
                "%d.%m.%Y %H:%M:%S",
                "15-01-2024 10:00:00 hello",
                Some("2024-01-15T10:00:00Z"),
                Some("2024-01-15T10:00:00Z"),
            ),
            (
                "%Y-%m-%d %H:%M:%S,%f",
                "2024-01-15 10:00:00,1234567 hello",
                Some("2024-01-15T10:00:00.1234567Z"),
                Some("2024-01-15T10:00:00.1234567Z"),
            ),
            ("%d.%m.%Y %H:%M:%S", "31.02.2024 10:00:00 hello", None, None),
            ("%d.%m.%Y %H:%M:%S", "no time here", None, None),
        ];
        for (format, line, read_with, read_without) in rows {
            let entry = with(format).parse_line(1, line).unwrap();
            assert_eq!(
                entry.timestamp,
                read_with.and_then(utc),
                "{format:?} on {line:?}"
            );
            let entry = without.parse_line(1, line).unwrap();
            assert_eq!(
                entry.timestamp,
                read_without.and_then(utc),
                "no format on {line:?}"
            );
        }
    }

    #[test]
    fn test_a_timestamp_format_reads_whichever_timestamp_group_the_regex_names() {
        let regex = Regex::new(r"^(?P<time>\S+) (?P<message>.*)$").unwrap();
        let parser = ParserConfig::new()
            .with_custom_regex(regex)
            .with_timestamp_format(compiled("%d.%m.%Y/%H:%M"))
            .build_for_file("test.log");
        let entry = parser.parse_line(1, "15.01.2024/10:30 hello").unwrap();
        assert_eq!(entry.timestamp, utc("2024-01-15T10:30:00Z"));
        assert_eq!(entry.message, "hello");
    }

    fn ids_of(parser: &LogParser, count: usize) -> Vec<Uuid> {
        (1..=count)
            .map(|n| parser.parse_line(n, "plain line").unwrap().id)
            .collect()
    }

    /// The 60 counter bits of an id: bytes 0 to 5, the low half of byte 6, byte 7.
    fn entry_id_count(id: Uuid) -> u64 {
        let bytes = id.as_bytes();
        let mut count = 0u64;
        for byte in &bytes[0..6] {
            count = (count << 8) | u64::from(*byte);
        }
        count = (count << 4) | u64::from(bytes[6] & 0x0F);
        (count << 8) | u64::from(bytes[7])
    }

    /// Held by the tests that read or change the run's random bits, which the whole process shares.
    static ID_RUN: std::sync::Mutex<()> = std::sync::Mutex::new(());

    #[test]
    fn test_ids_of_one_run_count_up_inside_one_block() {
        let _run = ID_RUN.lock().unwrap();
        let parser = LogParser::new("a.log");
        let ids = ids_of(&parser, 100);
        for pair in ids.windows(2) {
            // Only the counter bits differ between two ids of one run.
            assert_eq!(pair[0].as_bytes()[8..], pair[1].as_bytes()[8..]);
        }
        let counts: Vec<u64> = ids.iter().map(|id| entry_id_count(*id)).collect();
        for pair in counts.windows(2) {
            assert_eq!(pair[1], pair[0] + 1);
        }
    }

    #[test]
    fn test_ids_are_uuid_version_4_shaped() {
        let parser = LogParser::new("a.log");
        for id in ids_of(&parser, 50) {
            assert_eq!(id.get_version_num(), 4);
            assert_eq!(id.get_variant(), uuid::Variant::RFC4122);
            assert_eq!(id.to_string().len(), 36);
        }
    }

    #[test]
    fn test_two_parsers_and_many_threads_never_share_an_id() {
        let mut handles = Vec::new();
        for _ in 0..8 {
            handles.push(std::thread::spawn(|| {
                let first = LogParser::new("same.log");
                let second = LogParser::new("same.log");
                let mut ids = ids_of(&first, 3000);
                ids.extend(ids_of(&second, 3000));
                ids
            }));
        }
        let mut all = std::collections::HashSet::new();
        let mut total = 0;
        for handle in handles {
            for id in handle.join().unwrap() {
                total += 1;
                all.insert(id);
            }
        }
        assert_eq!(total, 48_000);
        assert_eq!(all.len(), 48_000);
    }

    #[test]
    fn test_a_new_id_run_draws_new_random_bits() {
        let _run = ID_RUN.lock().unwrap();
        let parser = LogParser::new("a.log");
        let before = ids_of(&parser, 1)[0];
        start_new_id_run();
        let after = ids_of(&parser, 1)[0];
        assert_ne!(before.as_bytes()[8..], after.as_bytes()[8..]);
        assert_eq!(after.get_version_num(), 4);
        assert_eq!(after.get_variant(), uuid::Variant::RFC4122);
        assert_eq!(entry_id_count(after), entry_id_count(before) + 1);
    }

    #[test]
    fn test_the_same_line_number_read_twice_gets_two_ids() {
        let parser = LogParser::new("a.log");
        let first = parser.parse_line(7, "plain line").unwrap();
        let second = parser.parse_line(7, "plain line").unwrap();
        assert_ne!(first.id, second.id);
    }
}
