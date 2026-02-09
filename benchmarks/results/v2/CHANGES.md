Three targeted performance optimizations, each independently testable and revertable:

**1. Cached investigator for all functions** (Python)

Five functions (`follow_thread`, `find_patterns`, `get_metadata`, `follow_thread_hierarchy`,
`detect_correlation_chains`) were calling standalone `logler_rs.*()` functions that create a new
Rust `Investigator` and re-parse all files on every call. Now they use `get_cached_investigator()`
which returns a pre-parsed instance keyed on (sorted file paths, mtimes).

Also fixed `detect_correlation_chains()` which called `logler_rs.search()` with 10 arguments
(standalone function only accepts 3) — this would crash at runtime if ever called.

**2. BTreeSet prefix index for hierarchy naming inference** (Rust)

`infer_children_from_naming()` scanned all thread+span IDs (O(parents x unique_IDs)) for each
parent node to find children by naming patterns (e.g., `worker-1` -> `worker-1.task-a`). Replaced
with a `BTreeSet<String>` populated during `add_entry()`, using `range()` for O(log n + k) prefix
lookups where k = number of actual matches.

**3. Capped smart_sample fetch size** (Python)

`smart_sample()` fetched ALL entries (`search(limit=None)`) then sampled 50. At 50K entries this
meant deserializing 50K JSON objects into Python dicts, then throwing away 49,950 of them.

Now fetches at most `sample_size * 10` entries (capped at 500 minimum) and reads `total_matches`
from the Rust search result to get the true population count — no separate count query needed.
Rust always returns `total_matches` (the pre-truncation count) even with a `limit`, so one search
gives both the capped results and the exact population size. For `errors_focused` strategy, uses
two targeted fetches (errors + context) instead of one huge fetch.
