# Diagnosing the GenVM v0.2.16 contract schema parser

"Contract schema issues" on GenLayer Studio almost always come from one place:
the ABI schema the node derives from your contract at deploy time via
`#get-schema`. In GenVM **v0.2.16** that logic lives in
`runners/genlayer-py-std/src/genlayer/py/get_schema.py` and it is a strict,
reflection-based type walker. If it raises, deployment fails with an opaque
`couldn't get schema for method ...` / `type is not supported` error.

`tools/harness/schema.py` in this repository is a faithful re-implementation of
that exact file, and `tools/lint_contract.py` runs it over the contract, so the
failure is caught locally instead of at deploy time.

## What the parser actually does

For the single `gl.Contract` subclass in the module it produces:

```json
{ "ctor": {"params": [...], "kwparams": {...}},
  "methods": {"name": {"params": [...], "kwparams": {}, "readonly": bool, "ret": ..., "payable": bool}} }
```

Type mapping (`_repr_type`, permissive mode is used for methods):

| Python annotation | Schema |
| --- | --- |
| missing / `typing.Any` / `Literal[...]` | `any` |
| `None`, `NoneType` | `null` |
| `bool`, `int`, `str`, `bytes` | `bool`, `int`, `string`, `bytes` |
| `Address` | `address` |
| `u256`, `i64`, … (`typing.NewType`) | unwrapped to `int` |
| `list[T]`, `tuple[T, ...]` | `[{"$rep": T}]` |
| `tuple[A, B]` | `[A, B]` |
| `dict[str, V]` | `{"$dict": V}` |
| bare `list` / `Sequence` | `array` (element type lost) |
| bare `dict` / `Mapping` | `dict` (value type lost) |
| `A \| B`, `Optional[A]` | `{"$or": [...]}` |
| dataclass | dict of its resolved field types |
| **anything else** | `TypeError: type is not supported` |

Hard structural rules:

1. `__init__` must exist on the class, be a plain function, and must **not** be
   decorated public.
2. First parameter must be literally named `self`.
3. Only `POSITIONAL_ONLY`, `POSITIONAL_OR_KEYWORD` and `KEYWORD_ONLY`
   parameters — `*args` / `**kwargs` raise.
4. Public method names must not start with `__`.
5. Exactly one `gl.Contract` subclass per module (enforced by
   `__init_subclass__`, not by the schema parser, but it fails just as hard).

## Failure modes and their real cause

| Symptom at deploy | Cause | Fix |
| --- | --- | --- |
| `type is not supported: <enum 'Decision'>` | `enum.Enum` in a signature | pass `str` and validate against a tuple of allowed values |
| `type is not supported: <class 'X'>` | `TypedDict`, `NamedTuple`, Pydantic model, custom class | use `dict[str, typing.Any]` and normalize inside |
| `dictionary can have only string keys` | `dict[int, ...]` | key by `str` |
| `assert len(args) == 1` | `list[str, int]`-style malformed generic | one arg only |
| `missing self` | decorator swallowed the bound signature | decorate with `gl.public.*` directly, no `functools.wraps` wrappers |
| `__init__ must be private` | `@gl.public.write` on `__init__` | remove the decorator |
| `couldn't get schema for method` + `NameError` | `from __future__ import annotations` + unresolvable string annotation | avoid deferred annotations, or keep every annotation importable at module scope |
| schema OK but calls fail to decode | returning objects calldata cannot encode (sets, custom classes, `Decimal`) | return `str`, `int`, `bool`, `bytes`, `list`, `dict`, `Address`, `None` |

## The schema-safe subset this contract uses

Every public signature in `contracts/agent_intent_verifier.py` is limited to:

* parameters: `str`, `int`, `list[str]`
* returns: `dict[str, typing.Any]`, `list[dict[str, typing.Any]]`, `list[str]`
* no keyword-only parameters, no enums, no dataclasses, no `Optional`, no bare
  `list`/`dict`, no `from __future__ import annotations`
* rich structures travel as JSON-shaped dicts and are validated deterministically
  in Python (`normalize_intent_spec`, `normalize_verdict`), which is *stronger*
  than the ABI would be anyway.

`tests/test_schema.py` asserts this subset, and
`tests/fixtures/bad_schema_contract.py` is a negative fixture proving the lint
rules fire on an enum parameter, a bare `dict`, and `*args`.

## Reproduce locally

```bash
python3 tools/lint_contract.py                       # lint + schema check
python3 tools/lint_contract.py --print-schema        # dump the derived ABI
python3 -m pytest tests -q                           # contract tests
```
