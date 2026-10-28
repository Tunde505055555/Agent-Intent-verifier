"""Load a contract module under the stub runtime."""

from __future__ import annotations

import importlib.util
import pathlib
import typing

from . import genlayer_stub

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "contracts" / "agent_intent_verifier.py"


def load_contract_module(path: pathlib.Path | str = CONTRACT_PATH):
    genlayer_stub.install()
    path = pathlib.Path(path)
    spec = importlib.util.spec_from_file_location(f"gl_contract_{path.stem}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def find_contract_class(module) -> type:
    candidates = [
        obj
        for obj in vars(module).values()
        if isinstance(obj, type)
        and getattr(obj, "__gl_contract__", False)
        and obj is not genlayer_stub.Contract
    ]
    if len(candidates) != 1:
        raise AssertionError(
            f"expected exactly one gl.Contract subclass, found {len(candidates)}"
        )
    return candidates[0]


def public_methods(contract_cls: type) -> dict[str, typing.Any]:
    return {
        name: getattr(contract_cls, name)
        for name in dir(contract_cls)
        if callable(getattr(contract_cls, name, None))
        and getattr(getattr(contract_cls, name), genlayer_stub.PUBLIC_ATTR, False)
    }
