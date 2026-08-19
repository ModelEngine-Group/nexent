from utils.bytes_utils import bytes_to_readable


def test_bytes_to_readable_handles_unlimited_value():
    assert bytes_to_readable(None) is None


def test_bytes_to_readable_formats_supported_units():
    assert bytes_to_readable(1024 * 1024 * 1024) == "1.0 GB"
    assert bytes_to_readable(500 * 1024 * 1024) == "500.0 MB"
    assert bytes_to_readable(500 * 1024) == "500.0 KB"
    assert bytes_to_readable(500) == "500 B"
