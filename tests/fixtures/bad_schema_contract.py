# { "Depends": "py-genlayer:test" }
"""
Negative fixture: intentionally violates v0.2.16 schema rules so the lint tests
prove the checks actually fire. NOT deployable, NOT part of the product.
"""

import enum
import typing

from genlayer import *


class Verdict(enum.Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


class BadContract(gl.Contract):
    def __init__(self) -> None:
        pass

    @gl.public.write
    def bad_enum(self, verdict: Verdict) -> None:  # enum is unrepresentable
        pass

    @gl.public.write
    def bad_bare(self, payload: dict) -> dict:  # bare dict loses typing
        return payload

    @gl.public.view
    def bad_varargs(self, *values: str) -> typing.Any:  # *args rejected by parser
        return values
