"""The hand-written stub of the compiled extension names what the extension has.

Compared with the built module: the public names, each parameter's name and place, and
whether it has a default. The types are not compared.
"""

import ast
import inspect
from pathlib import Path

import pytest

from logler_rs import logler_rs as live

STUB = Path(__file__).resolve().parent.parent / "src" / "logler_rs" / "logler_rs.pyi"


Params = list[tuple[str, bool]]  # a parameter's name and whether it has a default


def _params(fn: ast.FunctionDef) -> Params:
    a = fn.args
    positional = a.posonlyargs + a.args
    with_default = {x.arg for x in positional[len(positional) - len(a.defaults) :]}
    with_default |= {
        x.arg for x, d in zip(a.kwonlyargs, a.kw_defaults, strict=True) if d is not None
    }
    return [(x.arg, x.arg in with_default) for x in positional + a.kwonlyargs if x.arg != "self"]


def _stub_names() -> dict[str, Params | dict[str, Params]]:
    out: dict[str, Params | dict[str, Params]] = {}
    for node in ast.parse(STUB.read_text()).body:
        if isinstance(node, ast.ClassDef):
            out[node.name] = {
                f.name: _params(f) for f in node.body if isinstance(f, ast.FunctionDef)
            }
        elif isinstance(node, ast.FunctionDef):
            out[node.name] = _params(node)
    return out


def _live_params(obj: object) -> Params:
    sig = inspect.signature(obj)  # type: ignore[arg-type]  # inspect takes a callable; the extension's objects are
    return [
        (name, p.default is not inspect.Parameter.empty)
        for name, p in sig.parameters.items()
        if name != "self"
    ]


def _public(obj: object) -> list[str]:
    return sorted(n for n in dir(obj) if not n.startswith("_"))


def test_stub_names_are_the_extension_names():
    assert sorted(_stub_names()) == _public(live)


@pytest.mark.parametrize("cls_name", ["PyInvestigator", "PyLineParser"])
def test_stub_methods_and_parameters_match_the_extension(cls_name):
    stub = _stub_names()[cls_name]
    assert isinstance(stub, dict)
    cls = getattr(live, cls_name)
    methods = {k: v for k, v in stub.items() if k != "__init__"}
    assert sorted(methods) == _public(cls)
    for name, params in methods.items():
        assert params == _live_params(getattr(cls, name)), f"{cls_name}.{name}"
    assert stub["__init__"] == _live_params(cls), f"{cls_name}.__init__"


def test_stub_function_parameters_match_the_extension():
    assert _stub_names()["level_name"] == _live_params(live.level_name)


def test_the_packages_are_marked_typed():
    root = STUB.parent.parent
    assert (root / "logler" / "py.typed").is_file()
    assert (root / "logler_rs" / "py.typed").is_file()
