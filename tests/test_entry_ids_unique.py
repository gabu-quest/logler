"""Entry ids are unique among the entries of one process, however the files were loaded."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import uuid

import pytest

from logler.investigate import Investigator

LINES = 200


def _write(tmp_path, name):
    path = tmp_path / name
    path.write_text("".join(f"line {n}\n" for n in range(LINES)))
    return str(path)


def _ids(investigator):
    result = investigator.search(limit=LINES * 2)
    return [hit["entry"]["id"] for hit in result["results"]]


def test_the_same_file_in_two_investigators_shares_no_id(tmp_path):
    path = _write(tmp_path, "a.log")
    first, second = Investigator(), Investigator()
    first.load_files([path])
    second.load_files([path])
    ids = _ids(first) + _ids(second)
    assert len(ids) == 2 * LINES
    assert len(set(ids)) == 2 * LINES


def test_ids_are_hyphenated_uuid_version_4_strings(tmp_path):
    investigator = Investigator()
    investigator.load_files([_write(tmp_path, "a.log")])
    ids = _ids(investigator)
    assert len(ids) == LINES
    for entry_id in ids:
        assert re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", entry_id)
        assert uuid.UUID(entry_id).version == 4


def test_a_file_loaded_again_gets_new_ids(tmp_path):
    path = _write(tmp_path, "a.log")
    investigator = Investigator()
    investigator.load_files([path])
    before = set(_ids(investigator))
    again = Investigator()
    again.load_files([path])
    assert before.isdisjoint(_ids(again))


def test_investigators_loading_on_several_threads_share_no_id(tmp_path):
    paths = [_write(tmp_path, f"f{n}.log") for n in range(8)]
    found: list[list[str]] = [[] for _ in paths]

    def work(index):
        investigator = Investigator()
        investigator.load_files([paths[index]])
        found[index] = _ids(investigator)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(len(paths))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    everything = [entry_id for ids in found for entry_id in ids]
    assert len(everything) == 8 * LINES
    assert len(set(everything)) == 8 * LINES


# Runs in a fresh interpreter: a process that has loaded files has started the engine's worker
# threads, and a child made by fork does not have them.
_FORK_SCRIPT = """
import json, os, sys
from logler.investigate import Investigator
from logler.parser import LogParser

path = sys.argv[1]


def ids_of_the_file():
    investigator = Investigator()
    investigator.load_files([path])
    return [hit["entry"]["id"] for hit in investigator.search(limit=1000)["results"]]


def ids_from_a_forked_child():
    read_end, write_end = os.pipe()
    pid = os.fork()
    if pid == 0:
        status = 1
        try:
            os.close(read_end)
            os.write(write_end, json.dumps(ids_of_the_file()).encode())
            status = 0
        finally:
            os._exit(status)
    os.close(write_end)
    with os.fdopen(read_end) as pipe:
        ids = json.loads(pipe.read())
    assert os.waitpid(pid, 0)[1] == 0
    return ids


LogParser().parse_line(1, "the parent has made an id before it forks")
first, second = ids_from_a_forked_child(), ids_from_a_forked_child()
print(json.dumps({"first": first, "second": second, "parent": ids_of_the_file()}))
"""


@pytest.mark.skipif(not hasattr(os, "fork"), reason="the platform has no fork")
def test_forked_children_share_no_id_with_each_other_or_their_parent(tmp_path):
    """A process made by fork starts with a copy of its parent's id counters."""
    path = _write(tmp_path, "a.log")
    done = subprocess.run(
        [sys.executable, "-c", _FORK_SCRIPT, path],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    ids = json.loads(done.stdout)

    assert [len(ids["first"]), len(ids["second"]), len(ids["parent"])] == [LINES, LINES, LINES]
    assert len({*ids["first"], *ids["second"], *ids["parent"]}) == 3 * LINES
