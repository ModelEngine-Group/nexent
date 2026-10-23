import pytest

from backend.utils.config_validation import parse_positive_float, parse_positive_int


@pytest.mark.parametrize(
    ("raw_value", "default", "expected"),
    [(None, 100, 100), ("7", 100, 7), (7, 100, 7)],
)
def test_parse_positive_int_accepts_values_and_default(raw_value, default, expected):
    assert parse_positive_int(raw_value, "LIMIT", default) == expected


@pytest.mark.parametrize("raw_value", ["", "0", "-1", "not-a-number"])
def test_parse_positive_int_rejects_invalid_values(raw_value):
    with pytest.raises(ValueError, match="LIMIT must be a positive integer"):
        parse_positive_int(raw_value, "LIMIT", 100)


@pytest.mark.parametrize(
    ("raw_value", "default", "expected"),
    [(None, 10.0, 10.0), ("0.25", 10.0, 0.25), (2, 10.0, 2.0)],
)
def test_parse_positive_float_accepts_values_and_default(raw_value, default, expected):
    assert parse_positive_float(raw_value, "TIMEOUT", default) == expected


@pytest.mark.parametrize("raw_value", ["", "0", "-1", "nan", "inf", "not-a-number"])
def test_parse_positive_float_rejects_invalid_values(raw_value):
    with pytest.raises(ValueError, match="TIMEOUT must be a positive number"):
        parse_positive_float(raw_value, "TIMEOUT", 10.0)
