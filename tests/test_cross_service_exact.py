"""
PARAMETRIZED CROSS-SERVICE TESTS - Exact Value Assertions

These tests verify cross-service timeline functionality with KNOWN values:
- Deduplication (no duplicate entries)
- Exact counts per correlation
- Chronological ordering

Fixture: multi_service_deterministic
- 3 services: api-gateway, auth-service, db-service
- 30 entries each = 90 total entries
- correlation_id = req-{i % 5} (so req-0 through req-4)
- For each req-N: 6 entries per service (entries 0,5,10,15,20,25 for req-0)
- Total per correlation: 18 entries (6 per service × 3 services)
"""

import pytest

try:
    from logler.investigate import cross_service_timeline, RUST_AVAILABLE
except ImportError as e:
    if "logler_rs" in str(e):
        RUST_AVAILABLE = False
    else:
        raise


pytestmark = pytest.mark.skipif(
    not RUST_AVAILABLE, reason="Rust backend required for cross-service tests"
)


class TestCrossServiceExactCounts:
    """Test exact entry counts for correlations across services."""

    @pytest.mark.parametrize(
        "correlation_id,expected_count",
        [
            ("req-0", 18),  # 6 entries × 3 services
            ("req-1", 18),
            ("req-2", 18),
            ("req-3", 18),
            ("req-4", 18),
        ],
        ids=["req0_18", "req1_18", "req2_18", "req3_18", "req4_18"],
    )
    def test_correlation_exact_count_across_services(
        self, multi_service_deterministic, correlation_id, expected_count
    ):
        """Each correlation ID has exactly 18 entries (6 per service × 3)."""
        result = cross_service_timeline(
            files=multi_service_deterministic, correlation_id=correlation_id
        )

        timeline = result.get("timeline", result.get("entries", []))

        assert len(timeline) == expected_count, (
            f"Correlation {correlation_id} should have {expected_count} entries, "
            f"got {len(timeline)}"
        )


class TestCrossServiceDeduplication:
    """Test that entries are not duplicated in the timeline."""

    def test_no_duplicate_entries(self, multi_service_deterministic):
        """Timeline should not contain duplicate entries."""
        result = cross_service_timeline(files=multi_service_deterministic, correlation_id="req-0")

        timeline = result.get("timeline", result.get("entries", []))

        # Track (file, line_number) or (service, timestamp, message) as unique keys
        seen = set()
        duplicates = []

        for entry in timeline:
            # Create a unique key for each entry
            # Try file+line_number first
            if "file" in entry and "line_number" in entry:
                key = (entry["file"], entry["line_number"])
            elif "service" in entry:
                # Fall back to service+timestamp+message
                inner = entry.get("entry", entry)
                key = (
                    entry.get("service"),
                    inner.get("timestamp"),
                    inner.get("message"),
                )
            else:
                inner = entry.get("entry", entry)
                key = (inner.get("timestamp"), inner.get("message"))

            if key in seen:
                duplicates.append(key)
            seen.add(key)

        assert (
            len(duplicates) == 0
        ), f"Found {len(duplicates)} duplicate entries: {duplicates[:5]}..."

    def test_unique_entries_per_service(self, multi_service_deterministic):
        """Each service should contribute unique entries only."""
        result = cross_service_timeline(files=multi_service_deterministic, correlation_id="req-0")

        timeline = result.get("timeline", result.get("entries", []))

        # Group by service
        by_service = {}
        for entry in timeline:
            service = entry.get("service", "unknown")
            if service not in by_service:
                by_service[service] = []
            by_service[service].append(entry)

        # Each service should have exactly 6 entries for req-0
        for service, entries in by_service.items():
            assert len(entries) == 6, f"Service {service} should have 6 entries, got {len(entries)}"


class TestCrossServiceBreakdown:
    """Test service breakdown metadata is accurate."""

    def test_service_breakdown_exact_counts(self, multi_service_deterministic):
        """service_breakdown should show exact counts per service."""
        result = cross_service_timeline(files=multi_service_deterministic, correlation_id="req-0")

        breakdown = result.get("service_breakdown", {})

        if breakdown:
            # Each service should have exactly 6 entries
            expected = {"api-gateway": 6, "auth-service": 6, "db-service": 6}

            for service, expected_count in expected.items():
                actual_count = breakdown.get(service, 0)
                assert (
                    actual_count == expected_count
                ), f"Service {service} should have {expected_count} entries, got {actual_count}"

    def test_total_entries_matches_breakdown_sum(self, multi_service_deterministic):
        """total_entries should equal sum of service_breakdown."""
        result = cross_service_timeline(files=multi_service_deterministic, correlation_id="req-0")

        timeline = result.get("timeline", result.get("entries", []))
        breakdown = result.get("service_breakdown", {})

        if breakdown:
            breakdown_sum = sum(breakdown.values())
            assert breakdown_sum == len(
                timeline
            ), f"Breakdown sum ({breakdown_sum}) should equal timeline length ({len(timeline)})"


class TestCrossServiceChronologicalOrder:
    """Test that timeline entries are in chronological order."""

    def test_entries_ordered_by_timestamp(self, multi_service_deterministic):
        """Entries should be in chronological order."""
        result = cross_service_timeline(files=multi_service_deterministic, correlation_id="req-0")

        timeline = result.get("timeline", result.get("entries", []))

        # Extract timestamps
        timestamps = []
        for entry in timeline:
            inner = entry.get("entry", entry)
            ts = inner.get("timestamp", entry.get("timestamp"))
            if ts:
                timestamps.append(ts)

        # Timestamps should be sorted
        assert timestamps == sorted(timestamps), "Timeline entries should be in chronological order"


class TestCrossServiceAllServices:
    """Test that all services are represented."""

    def test_all_services_present(self, multi_service_deterministic):
        """All three services should be present in timeline."""
        result = cross_service_timeline(files=multi_service_deterministic, correlation_id="req-0")

        timeline = result.get("timeline", result.get("entries", []))

        services_found = set()
        for entry in timeline:
            service = entry.get("service")
            if service:
                services_found.add(service)

        expected_services = {"api-gateway", "auth-service", "db-service"}

        assert (
            services_found == expected_services
        ), f"Expected services {expected_services}, found {services_found}"

    def test_services_metadata(self, multi_service_deterministic):
        """Result should list all services in metadata."""
        result = cross_service_timeline(files=multi_service_deterministic, correlation_id="req-0")

        services = result.get("services", [])

        if services:
            expected = {"api-gateway", "auth-service", "db-service"}
            assert (
                set(services) == expected
            ), f"Services metadata should be {expected}, got {set(services)}"


class TestCrossServiceNonexistentCorrelation:
    """Test behavior with non-existent correlation."""

    def test_nonexistent_correlation_returns_empty(self, multi_service_deterministic):
        """Non-existent correlation should return exactly 0 entries."""
        result = cross_service_timeline(
            files=multi_service_deterministic, correlation_id="req-nonexistent"
        )

        timeline = result.get("timeline", result.get("entries", []))

        assert (
            len(timeline) == 0
        ), f"Non-existent correlation should return 0 entries, got {len(timeline)}"


class TestCrossServiceEntryStructure:
    """Test that timeline entries have required fields."""

    def test_entries_have_service_field(self, multi_service_deterministic):
        """Each timeline entry should have a service field."""
        result = cross_service_timeline(files=multi_service_deterministic, correlation_id="req-0")

        timeline = result.get("timeline", result.get("entries", []))
        assert len(timeline) > 0

        for entry in timeline:
            assert "service" in entry, "Entry should have 'service' field"

    def test_entries_have_timestamp(self, multi_service_deterministic):
        """Each timeline entry should have a timestamp."""
        result = cross_service_timeline(files=multi_service_deterministic, correlation_id="req-0")

        timeline = result.get("timeline", result.get("entries", []))
        assert len(timeline) > 0

        for entry in timeline:
            inner = entry.get("entry", entry)
            has_timestamp = "timestamp" in inner or "timestamp" in entry
            assert has_timestamp, "Entry should have 'timestamp' field"

    def test_entries_have_correlation_id(self, multi_service_deterministic):
        """Each entry should have the correct correlation_id."""
        result = cross_service_timeline(files=multi_service_deterministic, correlation_id="req-0")

        timeline = result.get("timeline", result.get("entries", []))
        assert len(timeline) > 0

        for entry in timeline:
            inner = entry.get("entry", entry)
            corr_id = inner.get("correlation_id")
            assert corr_id == "req-0", f"Entry should have correlation_id 'req-0', got '{corr_id}'"


class TestCrossServiceDurationMetadata:
    """Test duration metadata is calculated correctly."""

    def test_duration_is_positive(self, multi_service_deterministic):
        """Duration should be positive for multi-entry timeline."""
        result = cross_service_timeline(files=multi_service_deterministic, correlation_id="req-0")

        duration = result.get("duration_ms")

        if duration is not None:
            assert duration >= 0, f"Duration should be non-negative, got {duration}"


class TestCrossServiceLimit:
    """Test limit parameter enforcement."""

    def test_limit_caps_results(self, multi_service_deterministic):
        """Limit should cap the number of results."""
        result = cross_service_timeline(
            files=multi_service_deterministic, correlation_id="req-0", limit=5
        )

        timeline = result.get("timeline", result.get("entries", []))

        assert (
            len(timeline) <= 5
        ), f"With limit=5, should return at most 5 entries, got {len(timeline)}"

    def test_no_limit_returns_all(self, multi_service_deterministic):
        """No limit should return all 18 entries."""
        result = cross_service_timeline(files=multi_service_deterministic, correlation_id="req-0")

        timeline = result.get("timeline", result.get("entries", []))

        # Should have all 18 entries
        assert (
            len(timeline) == 18
        ), f"Without limit, should return all 18 entries, got {len(timeline)}"


class TestCrossServiceErrorEntries:
    """Test that error entries are correctly identified."""

    def test_error_entries_included(self, multi_service_deterministic):
        """Error entries (every 5th) should be included."""
        # In multi_service_deterministic, level="ERROR" when i % 5 == 0
        # So for req-0 (entries 0, 5, 10, 15, 20, 25), entries 0, 5, 10, 15, 20, 25 are ERROR
        result = cross_service_timeline(files=multi_service_deterministic, correlation_id="req-0")

        timeline = result.get("timeline", result.get("entries", []))

        error_count = 0
        for entry in timeline:
            inner = entry.get("entry", entry)
            if inner.get("level", "").upper() == "ERROR":
                error_count += 1

        # For req-0, all entries should be ERROR (entries 0,5,10,15,20,25 for each service)
        # That's 6 entries per service × 3 services = 18 ERROR entries
        assert error_count == 18, f"req-0 should have 18 ERROR entries, got {error_count}"

    @pytest.mark.parametrize(
        "correlation_id,expected_error_count,expected_info_count",
        [
            ("req-0", 18, 0),  # All entries are ERROR (0,5,10,15,20,25 % 5 == 0)
            ("req-1", 0, 18),  # All entries are INFO (1,6,11,16,21,26 % 5 != 0)
            ("req-2", 0, 18),  # All entries are INFO
            ("req-3", 0, 18),  # All entries are INFO
            ("req-4", 0, 18),  # All entries are INFO
        ],
        ids=["req0_all_error", "req1_all_info", "req2_all_info", "req3_all_info", "req4_all_info"],
    )
    def test_correlation_level_distribution(
        self, multi_service_deterministic, correlation_id, expected_error_count, expected_info_count
    ):
        """Each correlation has specific level distribution."""
        result = cross_service_timeline(
            files=multi_service_deterministic, correlation_id=correlation_id
        )

        timeline = result.get("timeline", result.get("entries", []))

        error_count = 0
        info_count = 0
        for entry in timeline:
            inner = entry.get("entry", entry)
            level = inner.get("level", "").upper()
            if level == "ERROR":
                error_count += 1
            elif level == "INFO":
                info_count += 1

        assert (
            error_count == expected_error_count
        ), f"{correlation_id} should have {expected_error_count} ERROR entries, got {error_count}"
        assert (
            info_count == expected_info_count
        ), f"{correlation_id} should have {expected_info_count} INFO entries, got {info_count}"
