"""Tests for reason code constants."""

from nexent.core.agents.context import reason_codes


EXPECTED_CODE_NAMES = [
    "SELECTED_MANDATORY_MINIMUM",
    "SELECTED_BUDGET_UPGRADE",
    "EXCLUDED_BUDGET",
    "EXCLUDED_POLICY_DISABLED",
    "EXCLUDED_LOWER_AUTHORITY",
    "MEMORY_OPERATION_ALLOWED",
    "MEMORY_OPERATION_DENIED",
    "CONFIRMATION_REQUIRED",
    "MINIMUM_FIDELITY_VIOLATION",
    "REDUCER_FAILED",
    "REPRESENTATION_STALE",
    "POLICY_INVALID",
    "POLICY_BUDGET_INVALID",
    "POLICY_DISABLED_MANDATORY",
    "POLICY_INVALID_REPRESENTATION",
]


class TestReasonCodes:
    """Tests for reason code string constants."""

    def test_expected_reason_codes_exist(self):
        for name in EXPECTED_CODE_NAMES:
            assert hasattr(reason_codes, name), f"Missing reason code: {name}"

    def test_all_reason_codes_are_strings(self):
        for name in EXPECTED_CODE_NAMES:
            value = getattr(reason_codes, name)
            assert isinstance(value, str), f"{name} is not a string"

    def test_all_reason_codes_are_non_empty(self):
        for name in EXPECTED_CODE_NAMES:
            value = getattr(reason_codes, name)
            assert len(value) > 0, f"{name} is an empty string"

    def test_all_reason_codes_are_unique(self):
        values = [getattr(reason_codes, name) for name in EXPECTED_CODE_NAMES]
        assert len(values) == len(set(values)), "Duplicate reason code values found"
