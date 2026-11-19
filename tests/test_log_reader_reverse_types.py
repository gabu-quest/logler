"""What `LogReader.read_lines(reverse=True)` yields, pinned so the rewrite of the reverse
read keeps it: `str`, like the forward read, never `bytes`."""

from logler.log_reader import LogReader


def _file(tmp_path):
    path = tmp_path / "app.log"
    path.write_bytes("alpha\nbeta \xe9\r\ngamma\n".encode())
    return path


def test_reverse_read_yields_str_lines_in_reverse_order(tmp_path):
    lines = list(LogReader(_file(tmp_path)).read_lines(reverse=True))
    assert lines == ["gamma", "beta \xe9", "alpha"]
    assert [type(x) for x in lines] == [str, str, str]


def test_forward_read_yields_the_same_type(tmp_path):
    lines = list(LogReader(_file(tmp_path)).read_lines())
    assert [type(x) for x in lines] == [str, str, str]
