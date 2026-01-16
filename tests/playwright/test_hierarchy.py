"""E2E tests for hierarchy and waterfall view functionality."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page


@pytest.fixture
def page_at_server(page: Page, server_url: str) -> Page:
    """Navigate to server and wait for page to load."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("button:has-text('Open File')", state="visible", timeout=10000)
    return page


class TestHierarchyView:
    """Tests for hierarchy view elements."""

    def test_hierarchy_view_exists(self, page_at_server: Page):
        """Hierarchy view section should exist."""
        page = page_at_server

        # Look for hierarchy-related elements
        hierarchy_text = page.locator("text=Hierarchy")

        # Should have hierarchy option
        has_hierarchy = hierarchy_text.count() > 0
        assert has_hierarchy, "Hierarchy option should exist"

    def test_root_id_input_exists(self, page_at_server: Page):
        """Root ID input for hierarchy should exist in the DOM."""
        page = page_at_server

        # Look for the root ID input - it exists but may be hidden
        root_input = page.locator("input[placeholder*='Root ID']")

        # Should exist in the DOM (count > 0), even if not visible
        assert root_input.count() > 0, "Root ID input should exist in the DOM"


class TestWaterfallView:
    """Tests for waterfall view elements."""

    def test_waterfall_view_exists(self, page_at_server: Page):
        """Waterfall view section should exist."""
        page = page_at_server

        # Look for waterfall-related elements
        waterfall_text = page.locator("text=Waterfall")

        # Should have waterfall option
        has_waterfall = waterfall_text.count() > 0
        assert has_waterfall, "Waterfall option should exist"
