import importlib.util
import sys
from pathlib import Path

from pydantic import Field

MODULE_NAME = "pydantic_utils_under_test"
MODULE_PATH = (
    Path(__file__).resolve().parents[4]
    / "sdk"
    / "nexent"
    / "core"
    / "utils"
    / "pydantic_utils.py"
)
spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
pydantic_utils_module = importlib.util.module_from_spec(spec)
sys.modules[MODULE_NAME] = pydantic_utils_module
assert spec and spec.loader
spec.loader.exec_module(pydantic_utils_module)

unwrap_field_info = pydantic_utils_module.unwrap_field_info


def test_unwrap_field_info_returns_plain_value():
    assert unwrap_field_info("hello") == "hello"
    assert unwrap_field_info(42) == 42
    assert unwrap_field_info(None) is None
    assert unwrap_field_info(True) is True
    assert unwrap_field_info([1, 2, 3]) == [1, 2, 3]


def test_unwrap_field_info_returns_fieldinfo_default():
    field_info = Field(default="my_default", description="test")
    assert unwrap_field_info(field_info) == "my_default"


def test_unwrap_field_info_returns_none_default():
    field_info = Field(default=None)
    assert unwrap_field_info(field_info) is None


def test_unwrap_field_info_calls_default_factory():
    field_info = Field(default_factory=list)
    assert unwrap_field_info(field_info) == []


def test_unwrap_field_info_default_factory_is_isolated():
    """Each call must produce a fresh instance, not a shared mutable default."""
    field_info = Field(default_factory=dict)
    first = unwrap_field_info(field_info)
    second = unwrap_field_info(field_info)
    assert first == {} and second == {}
    assert first is not second