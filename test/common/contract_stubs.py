# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Retain configured contract doubles after shared schemas move by business.

Business modules also contain pre-existing dataclasses and value objects. Keep
those real exports while applying a test's configured request-model doubles.
"""

import importlib
import json
from pathlib import Path
import sys
import types

_definitions = json.loads(
    Path(__file__).with_name("contract_stub_exports.json").read_text(encoding="utf-8")
)
MODEL_EXPORTS = _definitions["models"]
CONSTANT_EXPORTS = _definitions["constants"]
SHARED_EXPORTS = _definitions["shared"]
_original_exports = {
    name: dict(importlib.import_module(name).__dict__)
    for name in {*MODEL_EXPORTS, *CONSTANT_EXPORTS}
}


def install_business_contract_stubs(source):
    """Install configured request doubles without replacing unrelated types."""
    for name, exports in MODEL_EXPORTS.items():
        _register_business_module(name, _BusinessContractStub(name, source, exports))


def install_business_constant_stubs(source):
    """Carry explicitly configured constant values into their new owner."""
    for name, exports in CONSTANT_EXPORTS.items():
        _register_business_module(
            name,
            _BusinessContractStub(
                name,
                source,
                {key: key for key in exports},
                explicit=True,
            ),
        )


# Preserve the unaffected exports of other merged business modules as well.
for _module in [
    "contracts.constants.agent",
    "contracts.constants.evaluation",
    "contracts.constants.knowledge",
    "contracts.constants.model",
    "contracts.constants.tool",
    "contracts.errors.codes",
    "contracts.errors.exceptions",
]:
    _original_exports.setdefault(
        _module, dict(importlib.import_module(_module).__dict__)
    )


def install_shared_contract_stub(source, grouped):
    """Overlay the exports that a test previously stubbed as one small module."""
    if isinstance(grouped, str):
        grouped = SHARED_EXPORTS[grouped]
    for name, exports in grouped.items():
        _register_business_module(name, _BusinessContractStub(name, source, exports))


def _register_business_module(name, module):
    """Keep package imports and direct imports bound to the same test double."""
    sys.modules[name] = module
    parent, _, child = name.rpartition(".")
    if parent in sys.modules:
        setattr(sys.modules[parent], child, module)


class _BusinessContractStub(types.ModuleType):
    """Keep late fixture configuration visible through each business module."""

    def __init__(self, name, source, exports, explicit=False):
        super().__init__(name)
        self.__dict__.update(_original_exports[name])
        self.__dict__["_source"] = source
        self.__dict__["_bindings"] = {
            target: original for original, target in exports.items()
        }
        self.__dict__["_explicit"] = explicit
        previous = sys.modules.get(name)
        self.__dict__["_fallback"] = (
            previous if isinstance(previous, _BusinessContractStub) else None
        )

    def __getattribute__(self, name):
        state = super().__getattribute__("__dict__")
        original = state.get("_bindings", {}).get(name)
        if original is not None:
            source = state["_source"]
            configured = vars(source)
            if (
                not state["_explicit"]
                or original in configured
                or original in configured.get("_mock_children", {})
            ):
                if hasattr(source, original):
                    return getattr(source, original)
        fallback = state.get("_fallback")
        if fallback is not None and hasattr(fallback, name):
            return getattr(fallback, name)
        return super().__getattribute__(name)

    def __setattr__(self, name, value):
        state = super().__getattribute__("__dict__")
        original = state.get("_bindings", {}).get(name)
        if original is not None:
            setattr(state["_source"], original, value)
        elif state.get("_fallback") is not None and hasattr(state["_fallback"], name):
            setattr(state["_fallback"], name, value)
        else:
            super().__setattr__(name, value)
