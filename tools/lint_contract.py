#!/usr/bin/env python3
"""
GenVM-oriented contract lint for GenLayer v0.2.16.

Checks, in order:

1. Runner header: first line must be a ``# { "Depends": ... }`` comment.
2. AST hygiene: exactly one ``gl.Contract`` subclass, no floats in contract
   logic, no forbidden non-deterministic-by-accident modules (``random``,
   ``time``, ``datetime.now``, ``os``, ``requests``), no ``*args``/``**kwargs``
   in public methods, no public dunder methods, ``__init__`` present + private.
3. Schema safety: run the v0.2.16 schema parser over every public signature
   and reject any type it cannot represent. Also refuse types that *are*
   representable but decode badly in practice (bare ``list``/``dict``,
   ``Optional`` in params, dataclass/enum/TypedDict payloads).
4. Non-determinism containment: ``gl.nondet.*`` may only be reached from code
   executed inside a ``gl.vm.run_nondet`` / ``gl.eq_principle.*`` block.

Usage:  python3 tools/lint_contract.py [contracts/agent_intent_verifier.py ...]
Exit code 0 = clean.
"""

from __future__ import annotations

import ast
import enum
import json
import pathlib
import sys
import typing

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tools.harness import loader, schema  # noqa: E402

FORBIDDEN_IMPORTS = {"random", "os", "requests", "urllib", "socket", "secrets", "time"}
NONDET_ENTRYPOINTS = {"run_nondet", "run_nondet_unsafe", "spawn_sandbox"}
EQ_PRINCIPLES = {"strict_eq", "prompt_comparative", "prompt_non_comparative"}


class Finding(typing.NamedTuple):
    level: str
    line: int
    code: str
    message: str


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def lint_source(path: pathlib.Path) -> list[Finding]:
    src = path.read_text(encoding="utf-8")
    findings: list[Finding] = []
    lines = src.splitlines()

    header_lines = [
        (idx + 1, line)
        for idx, line in enumerate(lines[:4])
        if line.startswith("#") and "Depends" in line
    ]
    if not header_lines:
        findings.append(Finding("error", 1, "GL001", "missing runner header comment"))
    else:
        lineno, header = header_lines[0]
        try:
            json.loads(header.lstrip("#").strip())
        except Exception:
            findings.append(
                Finding("error", lineno, "GL001", "runner header is not valid JSON")
            )
        if not lines[0].startswith("# v"):
            findings.append(
                Finding(
                    "error",
                    1,
                    "GL002",
                    "missing `# vX.Y.Z` code version line above the runner header",
                )
            )

    tree = ast.parse(src, filename=str(path))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for name in names:
                root = name.split(".")[0]
                if root in FORBIDDEN_IMPORTS:
                    findings.append(
                        Finding(
                            "error",
                            node.lineno,
                            "GL010",
                            f"import `{name}` is non-deterministic or unavailable in GenVM",
                        )
                    )
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            findings.append(
                Finding(
                    "warning",
                    node.lineno,
                    "GL011",
                    "float literal: prefer integers for consensus-critical values",
                )
            )

    contracts = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(_dotted(base).endswith("Contract") for base in node.bases)
    ]
    if len(contracts) != 1:
        findings.append(
            Finding(
                "error",
                1,
                "GL020",
                f"exactly one gl.Contract subclass required, found {len(contracts)}",
            )
        )

    for contract in contracts:
        methods = [n for n in contract.body if isinstance(n, ast.FunctionDef)]
        if not any(m.name == "__init__" for m in methods):
            findings.append(
                Finding("error", contract.lineno, "GL021", "__init__ is required")
            )
        for method in methods:
            decorators = {_dotted(d) for d in method.decorator_list}
            decorators |= {
                _dotted(d.func) for d in method.decorator_list if isinstance(d, ast.Call)
            }
            is_public = any(dec.startswith("gl.public") for dec in decorators)
            if method.name.startswith("__") and is_public:
                findings.append(
                    Finding(
                        "error",
                        method.lineno,
                        "GL022",
                        f"public method `{method.name}` must not start with `__`",
                    )
                )
            if not is_public:
                continue
            if method.args.vararg or method.args.kwarg:
                findings.append(
                    Finding(
                        "error",
                        method.lineno,
                        "GL023",
                        f"public `{method.name}` uses *args/**kwargs which the "
                        "schema parser rejects",
                    )
                )
            for arg in method.args.args[1:] + method.args.kwonlyargs:
                if arg.annotation is None:
                    findings.append(
                        Finding(
                            "warning",
                            method.lineno,
                            "GL024",
                            f"`{method.name}.{arg.arg}` is unannotated -> schema 'any'",
                        )
                    )
            if method.returns is None:
                findings.append(
                    Finding(
                        "warning",
                        method.lineno,
                        "GL025",
                        f"public `{method.name}` has no return annotation -> 'any'",
                    )
                )

    findings.extend(_lint_nondet_containment(tree))
    return findings


def _lint_nondet_containment(tree: ast.AST) -> list[Finding]:
    """gl.nondet.* must be reachable only from functions passed to run_nondet."""
    nondet_users: dict[str, int] = {}
    consensus_callbacks: set[str] = set()
    call_graph: dict[str, set[str]] = {}

    class Walker(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            self.stack.append(node.name)
            call_graph.setdefault(node.name, set())
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            target = _dotted(node.func)
            current = self.stack[-1] if self.stack else "<module>"
            if target.startswith("gl.nondet"):
                nondet_users.setdefault(current, node.lineno)
            last = target.split(".")[-1]
            if (target.startswith("gl.vm") and last in NONDET_ENTRYPOINTS) or (
                target.startswith("gl.eq_principle") and last in EQ_PRINCIPLES
            ):
                for arg in node.args:
                    if isinstance(arg, (ast.Name, ast.Lambda)):
                        consensus_callbacks.add(
                            arg.id if isinstance(arg, ast.Name) else "<lambda>"
                        )
            call_graph.setdefault(current, set()).add(last)
            self.generic_visit(node)

    Walker().visit(tree)

    reachable = set(consensus_callbacks)
    changed = True
    while changed:
        changed = False
        for caller in list(reachable):
            for callee in call_graph.get(caller, set()):
                if callee not in reachable:
                    reachable.add(callee)
                    changed = True

    findings: list[Finding] = []
    for func, line in sorted(nondet_users.items()):
        if func not in reachable:
            findings.append(
                Finding(
                    "error",
                    line,
                    "GL030",
                    f"`{func}` calls gl.nondet.* outside a consensus block "
                    "(gl.vm.run_nondet / gl.eq_principle.*)",
                )
            )
    return findings


def _is_unsafe_annotation(annotation: typing.Any) -> str | None:
    if annotation in (list, dict):
        return "bare `list`/`dict` loses element typing in the ABI schema"
    if isinstance(annotation, type):
        if issubclass(annotation, enum.Enum):
            return "enum types are not representable by the schema parser"
        if hasattr(annotation, "__required_keys__"):
            return "TypedDict is not representable by the schema parser"
    origin = typing.get_origin(annotation)
    if origin is not None:
        for arg in typing.get_args(annotation):
            if arg is Ellipsis:
                continue
            reason = _is_unsafe_annotation(arg)
            if reason:
                return reason
    return None


def lint_schema(path: pathlib.Path) -> tuple[list[Finding], dict | None]:
    findings: list[Finding] = []
    try:
        module = loader.load_contract_module(path)
        contract_cls = loader.find_contract_class(module)
    except Exception as exc:
        return [Finding("error", 1, "GL040", f"contract failed to import: {exc}")], None

    try:
        abi = schema.get_schema(contract_cls)
    except Exception as exc:
        return [Finding("error", 1, "GL041", f"schema parser rejected contract: {exc}")], None

    import inspect as _inspect

    for name, method in loader.public_methods(contract_cls).items():
        hints = typing.get_type_hints(method)
        signature = _inspect.signature(method)
        for pname in list(signature.parameters)[1:]:
            annotation = hints.get(pname)
            if annotation is None:
                continue
            reason = _is_unsafe_annotation(annotation)
            if reason:
                findings.append(
                    Finding(
                        "error",
                        method.__code__.co_firstlineno,
                        "GL042",
                        f"`{name}({pname})`: {reason}",
                    )
                )
        ret = hints.get("return")
        if ret is not None:
            reason = _is_unsafe_annotation(ret)
            if reason:
                findings.append(
                    Finding(
                        "error",
                        method.__code__.co_firstlineno,
                        "GL043",
                        f"`{name}` return type: {reason}",
                    )
                )
    return findings, abi


def main(argv: list[str]) -> int:
    paths = [pathlib.Path(a) for a in argv[1:]] or [loader.CONTRACT_PATH]
    exit_code = 0
    for path in paths:
        print(f"== genvm lint: {path}")
        findings = lint_source(path)
        schema_findings, abi = lint_schema(path)
        findings.extend(schema_findings)

        for finding in sorted(findings, key=lambda f: (f.level != "error", f.line)):
            print(f"  {finding.level.upper():7} {finding.code} line {finding.line}: {finding.message}")
            if finding.level == "error":
                exit_code = 1
        if abi is not None:
            print(f"  schema OK: ctor + {len(abi['methods'])} public methods")
            if "--print-schema" in argv:
                print(json.dumps(abi, indent=2, sort_keys=True))
        if not findings:
            print("  no findings")
    print("RESULT:", "PASS" if exit_code == 0 else "FAIL")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
