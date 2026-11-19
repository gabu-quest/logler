"""Type stub for the compiled extension (`crates/logler-py/src/lib.rs`).

Every method that returns JSON returns the text: callers decode it with `json.loads`.
`tests/test_rs_stub.py` compares this file with the built module.
"""

class PyInvestigator:
    def __init__(self) -> None: ...
    def load_files(self, files: list[str]) -> None: ...
    def load_files_with_config(
        self,
        files: list[str],
        force_format: str | None,
        custom_regex: str | None,
    ) -> None: ...
    def search(self, query_json: str) -> str: ...
    def follow_thread(
        self,
        files: list[str],
        thread_id: str | None,
        correlation_id: str | None,
        trace_id: str | None,
    ) -> str: ...
    def get_context(
        self,
        file: str,
        line_number: int,
        lines_before: int,
        lines_after: int,
        include_related_threads: bool,
    ) -> str: ...
    def find_patterns(self, files: list[str], min_occurrences: int) -> str: ...
    def get_metadata(self, files: list[str]) -> str: ...
    def extract_ids(self, filters_json: str | None) -> str: ...
    def get_entries_page(self, offset: int, limit: int) -> str: ...
    def build_hierarchy(
        self,
        files: list[str],
        root_identifier: str,
        max_depth: int | None,
        use_naming_patterns: bool | None,
        use_temporal_inference: bool | None,
        min_confidence: float | None,
    ) -> str: ...

class PyLineParser:
    def __init__(
        self,
        file_name: str | None = None,
        force_format: str | None = None,
        custom_regex: str | None = None,
    ) -> None: ...
    def parse_line(self, line_number: int, raw: str) -> str: ...

def level_name(word: str) -> str | None: ...
