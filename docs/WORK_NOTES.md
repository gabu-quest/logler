# Work Plan: Stress & Scale Upgrade

- **Goal**: Harder tests, bigger fixtures, better examples, and smoother distribution flow.
- **Branch**: `feature/stress-tests-and-fixtures`

## Scope (to implement)
- Expand sample logs (≥10k entries in at least one file; richer chaos fixture).
- Add wildcard/tail example covering directory globs.
- Strengthen tests:
  - Exercise Rust backend (search/metadata/patterns) on larger datasets.
  - Cover wildcard/glob handling and follow/tail behaviors.
  - Validate level normalization and service/correlation propagation.
- Rebuild and verify Rust extension usage in examples.
- UX polish already requested: file picker + follow toggle (done).

## Distribution note
- PyPI flow would be: bump version, ensure `pyproject.toml` build metadata correct, build wheels (with maturin for Rust), and `twine upload dist/*`. Not changing version here; focusing on tests/fixtures.

## Execution order
1) Expand fixtures (big logs, chaos log, wildcard-ready directory).
2) Add new example for tailing/globs.
3) Add stress/integration tests invoking Rust backend.
4) Rebuild Rust extension and rerun examples/tests.
5) Summarize and adjust docs as needed.
