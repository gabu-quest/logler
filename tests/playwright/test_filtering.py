"""E2E tests for filtering functionality."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


@pytest.fixture
def page_at_server(page: Page, server_url: str) -> Page:
    """Navigate to server and wait for page to load."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("button:has-text('Open File')", state="visible", timeout=10000)
    return page


class TestSearchFilter:
    """Tests for text search filtering."""

    def test_search_input_exists(self, page_at_server: Page):
        """Search input should be visible in the interface."""
        page = page_at_server

        # Look for search input - use exact placeholder
        search_input = page.locator("input[placeholder='Search logs...']")
        expect(search_input).to_be_visible()


class TestLevelFilter:
    """Tests for log level filtering."""

    def test_level_checkboxes_exist(self, page_at_server: Page):
        """Level filter checkboxes should be present."""
        page = page_at_server

        # Level checkboxes should exist in sidebar
        checkboxes = page.locator("aside input[type='checkbox']")
        assert checkboxes.count() >= 4, "Should have at least 4 level checkboxes"

    def test_level_checkboxes_interactive(self, page_at_server: Page):
        """Level checkboxes should be interactive."""
        page = page_at_server

        # Get first level checkbox and verify it's interactive
        checkbox = page.locator("aside input[type='checkbox']").first
        expect(checkbox).to_be_enabled()


class TestCorrelationFilter:
    """Tests for correlation ID filtering."""

    def test_correlation_filter_input_exists(self, page_at_server: Page):
        """Correlation ID filter input should exist."""
        page = page_at_server

        # Use exact placeholder
        correlation_input = page.locator("input[placeholder='Filter by correlation ID...']")
        expect(correlation_input).to_be_visible()


class TestThreadSection:
    """Tests for thread section in sidebar."""

    def test_thread_section_exists(self, page_at_server: Page):
        """Threads section should exist in sidebar."""
        page = page_at_server

        # Look for Threads section
        threads_text = page.locator("text=Threads")

        # Should have threads section visible
        has_threads = threads_text.count() > 0
        assert has_threads, "Should have Threads section in sidebar"
