"""
Schema-parser contract tests.

These reproduce the GenVM v0.2.16 ABI parser (see tools/harness/schema.py) and
assert that every public signature stays inside the representable subset, which
is what "no contract schema issues" means in practice.
"""

import pathlib

import pytest

from tools.harness import loader, schema

ALLOWED_PARAM_SHAPES = (
    "string",
    "int",
    "bool",
    "bytes",
    "address",
    [{"$rep": "string"}],
)


@pytest.fixture()
def abi(contract_module):
    return schema.get_schema(loader.find_contract_class(contract_module))


def test_ctor_is_private_and_argument_free(abi):
    assert abi["ctor"] == {"params": [], "kwparams": {}}


def test_expected_public_surface(abi):
    assert set(abi["methods"]) == {
        "register_intent",
        "amend_intent",
        "grant_agent_authority",
        "revoke_agent_authority",
        "verify_action",
        "challenge_decision",
        "run_demo_scenario",
        "get_intent",
        "get_intent_versions",
        "get_decision",
        "get_decision_ids",
        "get_intent_decisions",
        "get_audit_trail",
        "get_agent_alignment_history",
        "get_agent_delegates",
        "get_authorization",
        "list_demo_scenarios",
        "get_policy",
    }


def test_every_param_is_schema_safe(abi):
    for name, entry in abi["methods"].items():
        assert entry["kwparams"] == {}, f"{name} must not use keyword-only params"
        for pname, shape in entry["params"]:
            assert shape in ALLOWED_PARAM_SHAPES, f"{name}.{pname} -> {shape}"


def test_returns_are_decodable(abi):
    for name, entry in abi["methods"].items():
        ret = entry["ret"]
        assert ret in ("string", "int", "bool", {"$dict": "any"}) or ret == [
            {"$rep": {"$dict": "any"}}
        ] or ret == [{"$rep": "string"}], f"{name} -> {ret}"


def test_readonly_flags(abi):
    for name, entry in abi["methods"].items():
        assert entry["readonly"] is name.startswith(("get_", "list_"))
        if not entry["readonly"]:
            assert entry["payable"] is False


def test_parser_rejects_unrepresentable_types():
    class Bad:
        def __init__(self):
            pass

        def bad(self, value: set[int]) -> None: ...

    setattr(Bad.bad, schema.PUBLIC_ATTR, True)
    with pytest.raises(schema.SchemaError):
        schema.get_schema(Bad)


def test_parser_rejects_non_string_dict_keys():
    class Bad:
        def __init__(self):
            pass

        def bad(self, value: dict[int, str]) -> None: ...

    setattr(Bad.bad, schema.PUBLIC_ATTR, True)
    with pytest.raises(schema.SchemaError):
        schema.get_schema(Bad)


def test_bad_fixture_contract_fails_lint():
    from tools import lint_contract

    fixture = pathlib.Path(__file__).parent / "fixtures" / "bad_schema_contract.py"
    findings, abi = lint_contract.lint_schema(fixture)
    codes = {f.code for f in findings}
    assert abi is None or codes, "the deliberately broken fixture must produce findings"


def test_reference_contract_passes_lint():
    from tools import lint_contract

    findings = lint_contract.lint_source(loader.CONTRACT_PATH)
    schema_findings, abi = lint_contract.lint_schema(loader.CONTRACT_PATH)
    errors = [f for f in findings + schema_findings if f.level == "error"]
    assert errors == [], errors
    assert abi is not None
