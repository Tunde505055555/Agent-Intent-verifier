"""
Minimal in-memory stand-in for the ``genlayer`` runtime (GenVM v0.2.16 API
surface) so contracts can be imported and exercised off-chain.

Implemented faithfully enough for contract tests:
  * ``gl.Contract`` with storage annotations (``TreeMap``, ``DynArray``, ``u256``)
  * ``gl.public.view`` / ``gl.public.write`` / ``.payable`` schema attributes
  * ``gl.vm.run_nondet`` executing leader AND validator (consensus simulation)
  * ``gl.nondet.exec_prompt`` / ``gl.nondet.web.render`` backed by test doubles
  * ``gl.message`` / ``gl.message_raw``

Anything not implemented raises loudly instead of silently diverging.
"""

from __future__ import annotations

import dataclasses
import sys
import types
import typing

PUBLIC_ATTR = "__gl_public__"
READONLY_ATTR = "__gl_readonly__"
PAYABLE_ATTR = "__gl_payable__"


# --- types -----------------------------------------------------------------


class Address:
    def __init__(self, value: str = "0x" + "11" * 20):
        self._value = value

    @property
    def as_hex(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"Address({self._value})"


u256 = typing.NewType("u256", int)
u8 = typing.NewType("u8", int)
i256 = typing.NewType("i256", int)
bigint = typing.NewType("bigint", int)


class TreeMap(dict):
    """Ordered mapping stand-in for genlayer storage TreeMap."""

    def __class_getitem__(cls, _item):
        return cls


class DynArray(list):
    def __class_getitem__(cls, _item):
        return cls


class Array(list):
    def __class_getitem__(cls, _item):
        return cls


def allow_storage(cls):
    return cls


# --- consensus / vm --------------------------------------------------------


@dataclasses.dataclass
class Return:
    calldata: typing.Any


@dataclasses.dataclass
class VMError:
    message: str


class UserError(Exception):
    def __init__(self, message: str = ""):
        super().__init__(message)
        self.message = message


class ConsensusFailure(Exception):
    """Raised when the simulated validator set does not agree with the leader."""


@dataclasses.dataclass
class NondetTrace:
    prompts: list[str] = dataclasses.field(default_factory=list)
    urls: list[str] = dataclasses.field(default_factory=list)
    leader_runs: int = 0
    validator_runs: int = 0
    agreements: list[bool] = dataclasses.field(default_factory=list)


class Runtime:
    """Test-controlled non-determinism source."""

    def __init__(self) -> None:
        self.prompt_handler: typing.Callable[[str], typing.Any] | None = None
        self.web_handler: typing.Callable[[str], str] | None = None
        self.validator_count = 2
        self.trace = NondetTrace()

    def reset(self) -> None:
        self.trace = NondetTrace()

    def exec_prompt(self, prompt: str, **_config) -> typing.Any:
        if self.prompt_handler is None:
            raise RuntimeError("harness: no prompt_handler configured")
        self.trace.prompts.append(prompt)
        return self.prompt_handler(prompt)

    def render(self, url: str, **_config) -> str:
        if self.web_handler is None:
            raise RuntimeError("harness: no web_handler configured")
        self.trace.urls.append(url)
        return self.web_handler(url)


RUNTIME = Runtime()


class Lazy:
    """Stand-in for genlayer ``Lazy[T]``: value is retrieved via ``.get()``."""

    def __init__(self, value: typing.Any):
        self._value = value

    def get(self) -> typing.Any:
        return self._value


def _run_nondet(leader_fn, validator_fn):
    RUNTIME.trace.leader_runs += 1
    leader_value = leader_fn()
    for _ in range(RUNTIME.validator_count):
        RUNTIME.trace.validator_runs += 1
        agreed = bool(validator_fn(Return(leader_value)))
        RUNTIME.trace.agreements.append(agreed)
        if not agreed:
            raise ConsensusFailure("validator disagreed with leader verdict")
    return Lazy(leader_value)


def _spawn_sandbox(fn, **_kwargs):
    try:
        return Return(fn())
    except UserError as exc:  # pragma: no cover - defensive
        return exc
    except Exception as exc:  # pragma: no cover - defensive
        return VMError(str(exc))


# --- public decorators -----------------------------------------------------


class _Write:
    def __call__(self, f):
        setattr(f, PUBLIC_ATTR, True)
        setattr(f, READONLY_ATTR, False)
        return f

    def payable(self, f):
        self(f)
        setattr(f, PAYABLE_ATTR, True)
        return f

    def min_gas(self, *, leader: int, validator: int):  # noqa: ARG002
        return self


class public:  # noqa: N801 - mirrors SDK naming
    write = _Write()

    @staticmethod
    def view(f):
        setattr(f, PUBLIC_ATTR, True)
        setattr(f, READONLY_ATTR, True)
        return f


def private(f):
    return f


# --- contract base ---------------------------------------------------------


class Contract:
    """Storage-backed base class: annotations become initialized containers."""

    def __init_subclass__(cls) -> None:
        cls.__gl_contract__ = True

    def __new__(cls, *args, **kwargs):  # noqa: ARG003
        obj = super().__new__(cls)
        for klass in reversed(cls.__mro__):
            for name, annotation in getattr(klass, "__annotations__", {}).items():
                origin = typing.get_origin(annotation) or annotation
                if origin in (TreeMap,) or annotation is TreeMap:
                    setattr(obj, name, TreeMap())
                elif origin in (DynArray, Array) or annotation in (DynArray, Array):
                    setattr(obj, name, DynArray())
                elif annotation in (u256, u8, i256, bigint, int):
                    setattr(obj, name, 0)
                elif annotation is str:
                    setattr(obj, name, "")
                elif annotation is bool:
                    setattr(obj, name, False)
        return obj

    @property
    def balance(self) -> int:
        return 0

    @property
    def address(self) -> Address:
        return message.contract_address


# --- message ---------------------------------------------------------------


class _Message(typing.NamedTuple):
    contract_address: Address
    sender_address: Address
    origin_address: Address
    value: int
    chain_id: int

    @property
    def raw(self) -> dict:
        return message_raw


message = _Message(
    contract_address=Address("0x" + "cc" * 20),
    sender_address=Address("0x" + "ab" * 20),
    origin_address=Address("0x" + "ab" * 20),
    value=0,
    chain_id=61999,
)

message_raw: dict[str, typing.Any] = {
    "contract_address": message.contract_address,
    "sender_address": message.sender_address,
    "origin_address": message.origin_address,
    "value": 0,
    "datetime": "2026-01-01T00:00:00+00:00",
    "is_init": False,
    "chain_id": 61999,
    "entry_kind": 0,
}


def set_sender(hex_address: str) -> None:
    global message, message_raw
    message = message._replace(sender_address=Address(hex_address))
    message_raw = dict(message_raw, sender_address=message.sender_address)
    _gl_module.message = message
    _gl_module.message_raw = message_raw
    top = sys.modules.get("genlayer")
    if top is not None and getattr(top, "__gl_stub__", False):
        top.message = message


# --- module assembly -------------------------------------------------------


def _build_gl_module() -> types.ModuleType:
    vm = types.ModuleType("genlayer.gl.vm")
    vm.Return = Return
    vm.VMError = VMError
    vm.UserError = UserError
    vm.run_nondet = _run_nondet
    vm.run_nondet_default = _run_nondet
    vm.run_nondet_unsafe = _run_nondet
    vm.spawn_sandbox = _spawn_sandbox

    web = types.ModuleType("genlayer.gl.nondet.web")
    web.render = lambda url, **kw: RUNTIME.render(url, **kw)

    nondet = types.ModuleType("genlayer.gl.nondet")
    nondet.exec_prompt = lambda prompt, **kw: RUNTIME.exec_prompt(prompt, **kw)
    nondet.web = web

    eq_principle = types.ModuleType("genlayer.gl.eq_principle")
    eq_principle.strict_eq = lambda fn: _run_nondet(fn, lambda res: fn() == res.calldata)
    eq_principle.prompt_comparative = lambda fn, principle: _run_nondet(  # noqa: ARG005
        fn, lambda _res: True
    )
    eq_principle.prompt_non_comparative = lambda fn, *, task, criteria: fn()  # noqa: ARG005

    gl = types.ModuleType("genlayer.gl")
    gl.vm = vm
    gl.nondet = nondet
    gl.eq_principle = eq_principle
    gl.public = public
    gl.private = private
    gl.Contract = Contract
    contract_mod = types.ModuleType("genlayer.contract")
    contract_mod.Contract = Contract
    gl.contract = contract_mod
    sys.modules["genlayer.contract"] = contract_mod
    gl.TreeMap = TreeMap
    gl.DynArray = DynArray
    gl.Array = Array
    gl.Address = Address
    gl.u256 = u256
    gl.u8 = u8
    gl.i256 = i256
    gl.bigint = bigint
    gl.Lazy = Lazy
    gl.message = message
    gl.message_raw = message_raw
    gl.storage = types.SimpleNamespace(TreeMap=TreeMap, DynArray=DynArray, Array=Array)
    gl.trace = lambda *objs, sep=" ": None
    gl.advanced = types.SimpleNamespace(
        user_error_immediate=lambda reason: (_ for _ in ()).throw(UserError(reason))
    )

    sys.modules["genlayer.gl"] = gl
    sys.modules["genlayer.gl.vm"] = vm
    sys.modules["genlayer.gl.nondet"] = nondet
    sys.modules["genlayer.gl.nondet.web"] = web
    sys.modules["genlayer.gl.eq_principle"] = eq_principle
    return gl


_gl_module = _build_gl_module()


def install() -> types.ModuleType:
    """Install the stub ``genlayer`` package into ``sys.modules``."""
    if "genlayer" in sys.modules and getattr(
        sys.modules["genlayer"], "__gl_stub__", False
    ):
        return sys.modules["genlayer"]

    genlayer = types.ModuleType("genlayer")
    genlayer.__gl_stub__ = True
    genlayer.__all__ = (
        "gl",
        "Address",
        "TreeMap",
        "DynArray",
        "Array",
        "allow_storage",
        "u256",
        "u8",
        "i256",
        "bigint",
    )
    types_mod = types.ModuleType("genlayer.types")
    types_mod.Address = Address
    types_mod.Lazy = Lazy
    types_mod.u256 = u256
    types_mod.u8 = u8
    types_mod.i256 = i256
    types_mod.bigint = bigint
    types_mod.__all__ = ("Address", "Lazy", "u256", "u8", "i256", "bigint")
    sys.modules["genlayer.types"] = types_mod
    genlayer.types = types_mod

    # new-style API: ``import genlayer as gl``
    for _name in (
        "vm",
        "nondet",
        "eq_principle",
        "public",
        "private",
        "contract",
        "message",
        "storage",
        "trace",
        "advanced",
        "Contract",
        "Lazy",
    ):
        setattr(genlayer, _name, getattr(_gl_module, _name))

    genlayer.gl = _gl_module
    genlayer.Address = Address
    genlayer.TreeMap = TreeMap
    genlayer.DynArray = DynArray
    genlayer.Array = Array
    genlayer.allow_storage = allow_storage
    genlayer.u256 = u256
    genlayer.u8 = u8
    genlayer.i256 = i256
    genlayer.bigint = bigint
    sys.modules["genlayer"] = genlayer
    return genlayer
