"""`logler.__version__` is the installed package's version, with no second written copy."""

import importlib
import importlib.metadata
from importlib.metadata import PackageNotFoundError, version

import logler


def test_dunder_version_is_the_installed_version():
    assert logler.__version__ == version("logler")


def test_a_source_tree_that_was_never_installed_still_imports(monkeypatch):
    def not_installed(name):
        raise PackageNotFoundError(name)

    with monkeypatch.context() as patched:
        patched.setattr(importlib.metadata, "version", not_installed)
        importlib.reload(logler)
        seen = logler.__version__
    importlib.reload(logler)

    assert seen == "0+unknown"
    assert logler.__version__ == version("logler")
