"""Stub the `genlayer` SDK so the deterministic layer can be unit tested off-chain."""
import sys, types, pathlib

stub = types.ModuleType("genlayer")

class _Any:
    def __getattr__(self, name): return _Any()
    def __call__(self, *a, **k):
        if len(a) == 1 and callable(a[0]) and not k: return a[0]
        return _Any()
    def __getitem__(self, k): return _Any()

class _Contract: pass

gl = _Any(); gl.Contract = _Contract
stub.gl = gl
stub.TreeMap = _Any()
stub.DynArray = _Any()
stub.u256 = int
stub.Address = str
stub.__all__ = ["gl", "TreeMap", "DynArray", "u256", "Address"]
sys.modules["genlayer"] = stub
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "contracts"))
