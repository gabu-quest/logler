"""Follow mode of the terminal viewer: line numbers, no lost line, no split line."""

import asyncio
import io
import re
import time

import pytest
from rich.console import Console

from logler.log_reader import CompleteLines
from logler.terminal import TerminalViewer

SHOWN = re.compile(r"^\s*(\d+) \S+ \S+ (\w+)\s+(.*)$")


def _line(n: int, level: str = "INFO", message: str | None = None) -> str:
    return f"2024-01-15 10:00:{n % 60:02d} {level} {message or f'message {n}'}\n"


def _text(n: int, level: str = "INFO", message: str | None = None) -> str:
    """What the viewer shows for that line: the plain format keeps the whole text."""
    return _line(n, level, message).rstrip("\n")


@pytest.fixture
def capture():
    return io.StringIO()


def _viewer(capture) -> TerminalViewer:
    viewer = TerminalViewer(use_colors=False)
    viewer.console = Console(file=capture, width=200, color_system=None)
    return viewer


def _shown(capture) -> list:
    """(line number, message) of every entry printed so far."""
    out = []
    for text in capture.getvalue().splitlines():
        m = SHOWN.match(text)
        if m:
            out.append((int(m.group(1)), m.group(3).strip()))
    return out


async def _follow(path, viewer, capture, actions, expected, **kwargs):
    """Run view_file(follow=True); do `actions` once following; wait for `expected`."""
    task = asyncio.create_task(viewer.view_file(str(path), follow=True, **kwargs))
    try:
        await actions()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if _shown(capture)[-len(expected) :] == expected:
                break
            await asyncio.sleep(0.01)
        return _shown(capture)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def _following(capture):
    deadline = time.monotonic() + 3
    while "Following" not in capture.getvalue() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)


def _append(path, text):
    with open(path, "a") as f:
        f.write(text)


def _run(scenario):
    return asyncio.run(scenario())


def test_appended_line_is_numbered_by_its_line_in_the_file(tmp_path, capture):
    path = tmp_path / "a.log"
    path.write_text("".join(_line(i) for i in range(1, 101)))
    viewer = _viewer(capture)

    async def scenario():
        async def actions():
            await _following(capture)
            _append(path, _line(101, message="appended"))

        return await _follow(
            path, viewer, capture, actions, [(101, _text(101, message="appended"))], lines=10
        )

    shown = _run(scenario)
    assert shown[:10] == [(n, _text(n)) for n in range(91, 101)]
    assert shown[10:] == [(101, _text(101, message="appended"))]


def test_filtered_follow_numbers_by_line_in_the_file(tmp_path, capture):
    path = tmp_path / "b.log"
    path.write_text("".join(_line(i, "ERROR" if i % 2 else "INFO", f"m{i}") for i in range(1, 21)))
    viewer = _viewer(capture)

    async def scenario():
        async def actions():
            await _following(capture)
            _append(path, _line(21, "INFO", "skipped") + _line(22, "ERROR", "wanted"))

        return await _follow(
            path,
            viewer,
            capture,
            actions,
            [(22, _text(22, "ERROR", "wanted"))],
            level_filter="ERROR",
        )

    shown = _run(scenario)
    assert shown == [(n, _text(n, "ERROR", f"m{n}")) for n in range(1, 21, 2)] + [
        (22, _text(22, "ERROR", "wanted"))
    ]


@pytest.fixture
def polls(monkeypatch):
    """Counts the passes the viewer makes over the file: the first read, then one per poll."""
    count = [0]
    real = CompleteLines.__iter__

    def counting(self):
        count[0] += 1
        return real(self)

    monkeypatch.setattr(CompleteLines, "__iter__", counting)
    return count


async def _polled_twice_more(polls):
    """Wait until the follow has read the file twice more: one read began after this call."""
    target = polls[0] + 2
    deadline = time.monotonic() + 3
    while polls[0] < target and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert polls[0] >= target


def test_line_written_in_two_parts_is_shown_once_and_whole(tmp_path, capture, polls):
    path = tmp_path / "c.log"
    path.write_text(_line(1))
    viewer = _viewer(capture)
    seen_after_first_part = []

    async def scenario():
        async def actions():
            await _following(capture)
            _append(path, "2024-01-15 10:00:00 INFO hel")
            await _polled_twice_more(polls)
            seen_after_first_part.extend(_shown(capture))
            _append(path, "lo\n")

        return await _follow(
            path, viewer, capture, actions, [(2, "2024-01-15 10:00:00 INFO hello")]
        )

    shown = _run(scenario)
    assert seen_after_first_part == [(1, _text(1))]
    assert shown == [(1, _text(1)), (2, "2024-01-15 10:00:00 INFO hello")]


def test_file_ending_in_half_line_shows_it_once_and_whole_when_finished(tmp_path, capture, polls):
    path = tmp_path / "e.log"
    path.write_text(_line(1) + _line(2) + "2024-01-15 10:00:00 INFO hel")
    viewer = _viewer(capture)
    seen_before_rest = []

    async def scenario():
        async def actions():
            await _following(capture)
            await _polled_twice_more(polls)
            seen_before_rest.extend(_shown(capture))
            _append(path, "lo\n")

        return await _follow(
            path, viewer, capture, actions, [(3, "2024-01-15 10:00:00 INFO hello")]
        )

    shown = _run(scenario)
    assert seen_before_rest == [(1, _text(1)), (2, _text(2))]
    assert shown == [(1, _text(1)), (2, _text(2)), (3, "2024-01-15 10:00:00 INFO hello")]


def test_without_follow_a_last_line_with_no_newline_is_shown(tmp_path, capture):
    path = tmp_path / "f.log"
    path.write_text(_line(1) + "2024-01-15 10:00:00 INFO last")
    viewer = _viewer(capture)

    asyncio.run(viewer.view_file(str(path)))

    assert _shown(capture) == [(1, _text(1)), (2, "2024-01-15 10:00:00 INFO last")]


def test_line_written_between_first_read_and_follow_is_shown(tmp_path, capture):
    path = tmp_path / "d.log"
    path.write_text(_line(1) + _line(2))
    viewer = _viewer(capture)
    original = viewer._display_entries
    calls = []

    def display_then_write(entries):
        original(entries)
        if not calls:
            calls.append(1)
            _append(path, _line(3, message="in the gap"))

    viewer._display_entries = display_then_write

    async def scenario():
        async def actions():
            await _following(capture)

        return await _follow(path, viewer, capture, actions, [(3, _text(3, message="in the gap"))])

    shown = _run(scenario)
    assert shown == [(1, _text(1)), (2, _text(2)), (3, _text(3, message="in the gap"))]


def test_a_byte_that_is_not_utf8_is_shown_as_the_replacement_character(tmp_path, capture):
    path = tmp_path / "g.log"
    path.write_bytes(_line(1).encode() + b"2024-01-15 10:00:00 INFO caf\xe9 open\n")
    viewer = _viewer(capture)

    asyncio.run(viewer.view_file(str(path)))

    assert _shown(capture) == [(1, _text(1)), (2, "2024-01-15 10:00:00 INFO caf\ufffd open")]


def test_a_byte_order_mark_is_not_part_of_line_one(tmp_path, capture):
    path = tmp_path / "bom.log"
    path.write_bytes(b"\xef\xbb\xbf" + _line(1).encode() + _line(2).encode())
    viewer = _viewer(capture)

    asyncio.run(viewer.view_file(str(path)))

    assert _shown(capture) == [(1, _text(1)), (2, _text(2))]


def test_a_line_keeps_its_trailing_spaces_in_the_entry(tmp_path, capture):
    """The viewer cuts a line as search does: only the line ending goes. The pattern is
    looked for in the entry's message, so it finds two closing spaces only when they stay."""
    path = tmp_path / "s.log"
    path.write_text(_line(1, message="shop open") + _line(2, message="shop open  "))
    viewer = _viewer(capture)

    asyncio.run(viewer.view_file(str(path), pattern="open  "))

    assert _shown(capture) == [(2, _text(2, message="shop open"))]


def test_cut_newline_takes_the_line_ending_and_nothing_else():
    from logler.parser import cut_newline

    assert [cut_newline(s) for s in ("a  \n", "a\r\n", "a\rb\n", "a\r\r\n", "a ")] == [
        "a  ",
        "a",
        "a\rb",
        "a\r",
        "a ",
    ]
