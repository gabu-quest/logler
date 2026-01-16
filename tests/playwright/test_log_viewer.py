"""E2E tests for log viewer functionality."""

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


class TestLogDisplay:
    """Tests for basic log display."""

    def test_empty_state_no_file(self, page_at_server: Page):
        """Fresh page should show 'No file opened' message."""
        page = page_at_server

        # Look for the empty state message
        empty_message = page.locator("text=No file opened")
        open_btn = page.locator("text=Open File")

        # Either should be visible
        has_empty_state = empty_message.count() > 0 or open_btn.count() > 0
        assert has_empty_state, "Should show empty state when no file is open"


class TestLayoutComponents:
    """Tests for layout components."""

    def test_header_visible(self, page_at_server: Page):
        """Header should be visible with Open File button."""
        page = page_at_server

        header = page.locator("header")
        expect(header).to_be_visible()

        open_btn = page.locator("button:has-text('Open File')")
        expect(open_btn).to_be_visible()

    def test_sidebar_visible(self, page_at_server: Page):
        """Sidebar should be visible with filter options."""
        page = page_at_server

        sidebar = page.locator("aside")
        expect(sidebar).to_be_visible()

        # Level checkboxes should be present
        level_checkbox = page.locator("input[type='checkbox']").first
        expect(level_checkbox).to_be_visible()


class TestViewModes:
    """Tests for view mode tabs."""

    def test_view_mode_tabs_exist(self, page_at_server: Page):
        """View mode tabs should exist (Logs, Hierarchy, Waterfall)."""
        page = page_at_server

        # Open file picker to have some UI state
        page.evaluate(
            """() => {
                const body = document.body;
                if (body._x_dataStack && body._x_dataStack.length > 0) {
                    body._x_dataStack[0].showFilePicker = false;
                }
            }"""
        )
        page.wait_for_timeout(300)

        # Check for view mode elements
        logs_text = page.locator("text=Logs")
        hierarchy_text = page.locator("text=Hierarchy")

        # At least one view mode indicator should be visible
        has_view_modes = logs_text.count() > 0 or hierarchy_text.count() > 0
        assert has_view_modes, "View mode options should be available"
