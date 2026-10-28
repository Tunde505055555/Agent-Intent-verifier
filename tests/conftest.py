import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.harness import genlayer_stub, loader  # noqa: E402

from tests.fake_model import FakeModel  # noqa: E402


@pytest.fixture()
def contract_module():
    return loader.load_contract_module()


@pytest.fixture()
def model():
    fake = FakeModel()
    genlayer_stub.RUNTIME.reset()
    genlayer_stub.RUNTIME.prompt_handler = fake
    genlayer_stub.RUNTIME.web_handler = fake.render
    genlayer_stub.RUNTIME.validator_count = 2
    return fake


@pytest.fixture()
def contract(contract_module, model):  # noqa: ARG001 - model must be installed first
    cls = loader.find_contract_class(contract_module)
    return cls()


@pytest.fixture()
def runtime():
    return genlayer_stub.RUNTIME
