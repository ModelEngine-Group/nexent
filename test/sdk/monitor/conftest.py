"""
Test configuration for SDK monitoring module.

This conftest.py ensures OpenTelemetry is properly mocked BEFORE any test
modules are imported. This is critical because the monitoring module uses
binding imports (e.g., `from opentelemetry import trace`) which bind the
imported objects at module load time.
"""

import sys
from unittest.mock import MagicMock


def pytest_configure(config):
    """
    Configure OpenTelemetry mocks before any test modules are collected.

    This runs at the very beginning of pytest execution, before test
    collection. We mock the entire OpenTelemetry package tree in sys.modules
    so that when monitoring.py is imported, it sees the mock objects.
    """
    # Create mock modules for OpenTelemetry
    mock_opentelemetry = MagicMock()
    mock_opentelemetry.trace = MagicMock()
    mock_opentelemetry.metrics = MagicMock()
    mock_opentelemetry.trace.status = MagicMock()
    mock_opentelemetry.exporter = MagicMock()
    mock_opentelemetry.exporter.prometheus = MagicMock()
    mock_opentelemetry.exporter.jaeger = MagicMock()
    mock_opentelemetry.exporter.jaeger.thrift = MagicMock()
    mock_opentelemetry.sdk = MagicMock()
    mock_opentelemetry.sdk.metrics = MagicMock()
    mock_opentelemetry.sdk.trace = MagicMock()
    mock_opentelemetry.sdk.trace.export = MagicMock()
    mock_opentelemetry.sdk.resources = MagicMock()
    mock_opentelemetry.instrumentation = MagicMock()
    mock_opentelemetry.instrumentation.requests = MagicMock()
    mock_opentelemetry.instrumentation.fastapi = MagicMock()

    # Insert mocks into sys.modules BEFORE any imports
    modules_to_mock = {
        'opentelemetry': mock_opentelemetry,
        'opentelemetry.trace': mock_opentelemetry.trace,
        'opentelemetry.metrics': mock_opentelemetry.metrics,
        'opentelemetry.trace.status': mock_opentelemetry.trace.status,
        'opentelemetry.exporter': mock_opentelemetry.exporter,
        'opentelemetry.exporter.prometheus': mock_opentelemetry.exporter.prometheus,
        'opentelemetry.exporter.jaeger': mock_opentelemetry.exporter.jaeger,
        'opentelemetry.exporter.jaeger.thrift': mock_opentelemetry.exporter.jaeger.thrift,
        'opentelemetry.sdk': mock_opentelemetry.sdk,
        'opentelemetry.sdk.metrics': mock_opentelemetry.sdk.metrics,
        'opentelemetry.sdk.trace': mock_opentelemetry.sdk.trace,
        'opentelemetry.sdk.trace.export': mock_opentelemetry.sdk.trace.export,
        'opentelemetry.sdk.resources': mock_opentelemetry.sdk.resources,
        'opentelemetry.instrumentation': mock_opentelemetry.instrumentation,
        'opentelemetry.instrumentation.requests': mock_opentelemetry.instrumentation.requests,
        'opentelemetry.instrumentation.fastapi': mock_opentelemetry.instrumentation.fastapi,
    }

    # Store original modules for cleanup
    original_modules = {}
    for module_name in modules_to_mock:
        if module_name in sys.modules:
            original_modules[module_name] = sys.modules[module_name]
        sys.modules[module_name] = modules_to_mock[module_name]

    # Store for cleanup in pytest_unconfigure
    config._mocked_otel_modules = original_modules


def pytest_unconfigure(config):
    """
    Restore original OpenTelemetry modules after tests complete.
    """
    if hasattr(config, '_mocked_otel_modules'):
        for module_name, original_module in config._mocked_otel_modules.items():
            sys.modules[module_name] = original_module

