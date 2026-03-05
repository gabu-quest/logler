# v3 Changes: Memory & Scale

v2 made logler fast. v3 makes it safe.

## What Changed

### 1. Two-Phase Search in Rust Engine

**Before:** `search()` scored every matching entry by allocating full `SearchResult` structs (~2-4 KB each) for all candidates, sorted them, then truncated to the limit.

**After:** Phase 1 uses lightweight `MatchCandidate` structs (~40 bytes) containing only the score and entry index. Phase 2 materializes only the final N results into full `SearchResult` structs.

**Impact:** A broad query matching 60K entries (INFO level in a 100K corpus) previously allocated ~120 MB of intermediate `SearchResult` objects. Now it allocates ~2.4 MB of candidates + ~400 KB for the final 100 results. Memory reduction: **~50x** for broad queries.

### 2. Streaming `fetchmany` in `_read_sqler_table`

**Before:** `cursor.fetchall()` loaded all raw `sqlite3.Row` objects into memory simultaneously with the growing converted entries list.

**After:** `cursor.fetchmany(1000)` processes rows in batches of 1000, releasing raw rows before fetching the next batch.

**Impact:** At 80K rows, peak memory drops by ~80 MB (no longer holding raw rows + converted entries simultaneously).

### 3. Streaming `db_to_jsonl` Per-Table

**Before:** All entries from all tables were accumulated into a single list, sorted globally by timestamp, then written to JSONL.

**After:** Each table's entries are streamed directly to the temp file in table order (ordered by `_id` within each table). No cross-table accumulation. The Rust parser handles indexing and sorting at query time.

**Impact:** Eliminates the cross-table sort buffer entirely. At 80K rows across two tables, this saved ~80 MB of peak memory.

## New Benchmark Scenarios

| # | Scenario | What It Proves |
|---|----------|---------------|
| 15 | `search_broad_query` | Broad queries (INFO ~60%) don't regress under two-phase search |
| 16 | `search_memory_profile` | RSS grows sub-linearly from 10K to 100K entries |
| 17 | `db_to_jsonl_scaling` | Streaming conversion throughput at 1K/10K/50K rows |
| 18 | `db_source_search` | End-to-end DB search (convert + parse + search) throughput |
| 19 | `db_source_memory` | Streaming fetchmany keeps RSS flat regardless of table size |
