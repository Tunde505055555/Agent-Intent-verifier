"""
Faithful re-implementation of the GenVM v0.2.16 ABI schema parser
(``runners/genlayer-py-std/src/genlayer/py/get_schema.py``).

We reproduce it here so the repository can *prove* — without a node — that
every public signature is representable, and so lint failures point at the same
place the real parser would fail. Rules mirrored from v0.2.16:

  * primitives: ``None``/``NoneType`` -> ``null``, ``bool``, ``int``, ``str`` ->
    ``string``, ``bytes``, ``Address`` -> ``address``
  * ``typing.NewType`` unwraps to its supertype (``u256`` -> ``int``)
  * ``list``/``Sequence`` -> ``array``, ``dict``/``Mapping`` -> ``dict``
  * ``dict[K, V]`` requires ``K is str``
  * ``list[T]`` -> ``[{"$rep": T}]``; ``tuple[...]`` -> positional list;
    ``tuple[T, ...]`` -> ``[{"$rep": T}]``
  * unions -> ``{"$or": [...]}``; dataclasses -> field dict;
    ``typing.Literal`` -> ``any``; missing annotation -> ``any``
  * anything else raises ``TypeError('type is not supported')``
  * ``__init__`` must exist and must NOT be public
  * public method names must not start with ``__``
  * only ``self``, positional(-or-keyword) and keyword-only params are allowed
"""

from __future__ import annotations

import collections.abc
import dataclasses
import inspect
import types
import typing

PUBLIC_ATTR = "__gl_public__"
READONLY_ATTR = "__gl_readonly__"
PAYABLE_ATTR = "__gl_payable__"


class SchemaError(TypeError):
    pass


def _is_list(t: typing.Any, permissive: bool) -> bool:
    if t is list:
        return True
    if not permissive:
        return False
    try:
        return issubclass(t, collections.abc.Sequence)
    except Exception:
        return False


def _is_dict(t: typing.Any, permissive: bool) -> bool:
    if t is dict:
        return True
    if not permissive:
        return False
    try:
        return issubclass(t, collections.abc.Mapping)
    except Exception:
        return False


def repr_type(t: typing.Any, permissive: bool = True) -> typing.Any:
    if t is inspect.Signature.empty:
        return "any"
    if type(t) is typing.NewType:
        return repr_type(t.__supertype__, permissive)
    if t is None or t is types.NoneType:
        return "null"
    if t is bool:
        return "bool"
    if t is int:
        return "int"
    if t is str:
        return "string"
    if t is bytes:
        return "bytes"
    if getattr(t, "__name__", "") == "Address":
        return "address"
    if _is_list(t, permissive):
        return "array"
    if _is_dict(t, permissive):
        return "dict"
    if t is typing.Any:
        return "any"
    ttype = type(t)
    if ttype is getattr(typing, "_UnionGenericAlias", None) or ttype is types.UnionType:
        return {"$or": [repr_type(x, permissive) for x in typing.get_args(t)]}
    if dataclasses.is_dataclass(t) and isinstance(t, type):
        return {
            name: repr_type(value, permissive)
            for name, value in typing.get_type_hints(t).items()
        }
    origin = typing.get_origin(t)
    if origin is not None:
        args = typing.get_args(t)
        if _is_dict(origin, permissive):
            if len(args) != 2:
                raise SchemaError(f"dict needs 2 args: {t}")
            if args[0] is not str:
                raise SchemaError(f"dictionary can have only string keys: {t}")
            return {"$dict": repr_type(args[1], permissive)}
        if origin is tuple:
            if len(args) == 2 and args[1] is Ellipsis:
                return [{"$rep": repr_type(args[0], permissive)}]
            return [repr_type(a, permissive) for a in args]
        if _is_list(origin, permissive):
            if len(args) != 1:
                raise SchemaError(f"list needs exactly 1 arg: {t}")
            return [{"$rep": repr_type(args[0], permissive)}]
        if origin is typing.Literal:
            return "any"
    raise SchemaError(f"type is not supported: {t!r} (kind {ttype!r})")


def _escape_dict_prop(prop: str) -> str:
    return "$" + prop if prop.startswith("$") else prop


def _get_params(method, *, is_ctor: bool) -> dict:
    signature = inspect.signature(method)
    hints = typing.get_type_hints(method)
    params: list[list[typing.Any]] = []
    kwparams: dict[str, typing.Any] = {}

    first = True
    for name, par in signature.parameters.items():
        if first:
            if name != "self":
                raise SchemaError(f"missing self in `{method.__qualname__}`")
            first = False
            continue
        annotation = hints.get(name, par.annotation)
        kind = str(par.kind)
        if kind in ("POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD"):
            params.append([name, repr_type(annotation, True)])
        elif kind == "KEYWORD_ONLY":
            kwparams[_escape_dict_prop(name)] = repr_type(annotation, True)
        else:
            raise SchemaError(
                f"unsupported parameter kind {kind} for `{name}` in "
                f"`{method.__qualname__}` (no *args / **kwargs in public methods)"
            )

    out: dict[str, typing.Any] = {"params": params, "kwparams": kwparams}
    if not is_ctor:
        ret = hints.get("return", signature.return_annotation)
        out["readonly"] = getattr(method, READONLY_ATTR, False)
        out["ret"] = repr_type(ret, True)
        if not out["readonly"]:
            out["payable"] = getattr(method, PAYABLE_ATTR, False)
    return out


def get_schema(contract: type) -> dict[str, typing.Any]:
    if "__init__" not in contract.__dict__:
        raise SchemaError("__init__ is absent")
    ctor = contract.__dict__["__init__"]
    if not inspect.isfunction(ctor):
        raise SchemaError("__init__ is not a function")
    if getattr(ctor, PUBLIC_ATTR, False):
        raise SchemaError("__init__ must be private")

    methods = {
        name: meth
        for name, meth in sorted(inspect.getmembers(contract))
        if inspect.isfunction(meth)
        and getattr(meth, PUBLIC_ATTR, False)
        and name != "__on_errored_message__"
    }
    for name in methods:
        if name.startswith("__"):
            raise SchemaError(f"public method names should not start with `__`: {name}")

    return {
        "ctor": _get_params(ctor, is_ctor=True),
        "methods": {
            name: _get_params(meth, is_ctor=False) for name, meth in methods.items()
        },
    }
