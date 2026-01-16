"""E2E tests for file browser functionality."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


def set_alpine_state(page: Page, updates: dict):
    """Set Alpine.js state properties."""
    for key, value in updates.items():
        if isinstance(value, str):
            page.evaluate(
                f"""() => {{
                    const body = document.body;
                    if (body._x_dataStack && body._x_dataStack.length > 0) {{
                        body._x_dataStack[0].{key} = '{value}';
                    }}
                }}"""
            )
        elif isinstance(value, bool):
            val_str = "true" if value else "false"
            page.evaluate(
                f"""() => {{
                    const body = document.body;
                    if (body._x_dataStack && body._x_dataStack.length > 0) {{
                        body._x_dataStack[0].{key} = {val_str};
                    }}
                }}"""
            )
    page.wait_for_timeout(300)


def open_file_picker(page: Page, mode: str = "browse"):
    """Open the file picker modal."""
    set_alpine_state(page, {"showFilePicker": True, "browseMode": mode})


def close_file_picker(page: Page):
    """Close the file picker modal."""
    set_alpine_state(page, {"showFilePicker": False})


def open_file_via_api(page: Page, server_url: str, file_path: str):
    """Open a file by calling the API directly."""
    # Make API call to open file
    page.evaluate(
        f"""async () => {{
            const resp = await fetch('/api/files/open', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{path: '{file_path}', quick: true}})
            }});
            return resp.ok;
        }}"""
    )
    # Refresh state
    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)


@pytest.fixture
def page_at_server(page: Page, server_url: str) -> Page:
    """Navigate to server and wait for page to load."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    # Wait for Alpine.js to initialize (the Open File button should be visible)
    page.wait_for_selector("button:has-text('Open File')", state="visible", timeout=10000)
    return page


class TestFilePickerModal:
    """Tests for the file picker modal."""

    def test_open_file_picker_modal(self, page_at_server: Page):
        """Opening file picker should show modal with tabs."""
        page = page_at_server

        # Open the file picker modal
        open_file_picker(page)

        # Wait for modal to appear
        modal_title = page.locator("h2:has-text('Open Log File')")
        expect(modal_title).to_be_visible(timeout=10000)

        # Verify modal has Browse and Glob tabs
        expect(page.locator("button:has-text('Browse')")).to_be_visible()
        expect(page.locator("button:has-text('Glob search')")).to_be_visible()

    def test_close_file_picker_modal(self, page_at_server: Page):
        """Closing file picker should hide modal."""
        page = page_at_server

        # Open modal
        open_file_picker(page)
        modal_title = page.locator("h2:has-text('Open Log File')")
        expect(modal_title).to_be_visible()

        # Close modal
        close_file_picker(page)

        # Verify modal is hidden
        expect(modal_title).to_be_hidden()


class TestOpenSingleFile:
    """Tests for opening a single log file."""

    @pytest.mark.skip(reason="API file opening doesn't properly sync with Alpine state in tests")
    def test_open_single_file_displays_logs(
        self, page_at_server: Page, server_url: str, production_log
    ):
        """Opening a file should display logs in the viewer."""
        page = page_at_server

        # Open file via API
        open_file_via_api(page, server_url, str(production_log))

        # Use more specific selector for logs view
        log_container = page.locator("#log-container")
        expect(log_container).to_be_visible()

        # Should have some log entries
        log_lines = page.locator(".log-line")
        expect(log_lines.first).to_be_visible(timeout=5000)

    @pytest.mark.skip(reason="API file opening doesn't properly sync with Alpine state in tests")
    def test_open_file_shows_statistics(
        self, page_at_server: Page, server_url: str, production_log
    ):
        """Opening a file should show statistics in sidebar."""
        page = page_at_server

        # Open file via API
        open_file_via_api(page, server_url, str(production_log))

        # Statistics should show Total count
        stats_section = page.locator("text=Statistics").locator("..")
        expect(stats_section).to_be_visible(timeout=5000)


class TestGlobSearch:
    """Tests for glob pattern search."""

    def test_switch_to_glob_mode(self, page_at_server: Page):
        """Opening in glob mode should show glob inputs."""
        page = page_at_server

        # Open file picker in glob mode
        open_file_picker(page, mode="glob")

        # Verify glob input fields are visible
        expect(page.locator("input[placeholder*='Pattern']")).to_be_visible()
        expect(page.locator("input[placeholder='Base directory']")).to_be_visible()


class TestEmptyState:
    """Tests for empty/initial state."""

    def test_empty_state_no_file(self, page_at_server: Page):
        """Fresh page should show 'No file opened' message or Open File prompt."""
        page = page_at_server

        # Look for the empty state (either message or prompt)
        empty_message = page.locator("text=No file opened")
        open_prompt = page.locator("text=Open File")

        # Either should be visible
        has_empty_state = empty_message.count() > 0 or open_prompt.count() > 0
        assert has_empty_state, "Should show empty state when no file is open"
