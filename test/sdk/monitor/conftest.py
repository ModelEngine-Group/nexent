"""
Test configuration for SDK monitoring module.

This conftest.py ensures OpenTelemetry is properly mocked BEFORE any test
modules are imported. This is critical because the monitoring module uses
binding imports (e.g., `from opentelemetry import trace`) which bind the
imported objects at module load time.
"""

import sys
import types
import importlib.util
from pathlib import Path
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
    mock_opentelemetry.exporter.otlp = MagicMock()
    mock_opentelemetry.exporter.otlp.proto = MagicMock()
    mock_opentelemetry.exporter.otlp.proto.http = MagicMock()
    mock_opentelemetry.exporter.otlp.proto.http.trace_exporter = MagicMock()
    mock_opentelemetry.exporter.otlp.proto.http.metric_exporter = MagicMock()
    mock_opentelemetry.exporter.otlp.proto.grpc = MagicMock()
    mock_opentelemetry.exporter.otlp.proto.grpc.trace_exporter = MagicMock()
    mock_opentelemetry.exporter.otlp.proto.grpc.metric_exporter = MagicMock()
    mock_opentelemetry.sdk = MagicMock()
    mock_opentelemetry.sdk.metrics = MagicMock()
    mock_opentelemetry.sdk.metrics.export = MagicMock()
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
        'opentelemetry.exporter.otlp': mock_opentelemetry.exporter.otlp,
        'opentelemetry.exporter.otlp.proto': mock_opentelemetry.exporter.otlp.proto,
        'opentelemetry.exporter.otlp.proto.http': mock_opentelemetry.exporter.otlp.proto.http,
        'opentelemetry.exporter.otlp.proto.http.trace_exporter': (
            mock_opentelemetry.exporter.otlp.proto.http.trace_exporter
        ),
        'opentelemetry.exporter.otlp.proto.http.metric_exporter': (
            mock_opentelemetry.exporter.otlp.proto.http.metric_exporter
        ),
        'opentelemetry.exporter.otlp.proto.grpc': mock_opentelemetry.exporter.otlp.proto.grpc,
        'opentelemetry.exporter.otlp.proto.grpc.trace_exporter': (
            mock_opentelemetry.exporter.otlp.proto.grpc.trace_exporter
        ),
        'opentelemetry.exporter.otlp.proto.grpc.metric_exporter': (
            mock_opentelemetry.exporter.otlp.proto.grpc.metric_exporter
        ),
        'opentelemetry.sdk': mock_opentelemetry.sdk,
        'opentelemetry.sdk.metrics': mock_opentelemetry.sdk.metrics,
        'opentelemetry.sdk.metrics.export': mock_opentelemetry.sdk.metrics.export,
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

    # Load the monitoring module directly so these tests do not import the full SDK package.
    # The package __init__ imports data-processing dependencies that are unrelated here.
    package_modules = {
        "sdk": types.ModuleType("sdk"),
        "sdk.nexent": types.ModuleType("sdk.nexent"),
        "sdk.nexent.monitor": types.ModuleType("sdk.nexent.monitor"),
    }
    for module_name, module in package_modules.items():
        if module_name in sys.modules:
            original_modules[module_name] = sys.modules[module_name]
        sys.modules[module_name] = module
    sys.modules["sdk"].nexent = sys.modules["sdk.nexent"]
    sys.modules["sdk.nexent"].monitor = sys.modules["sdk.nexent.monitor"]

    repo_root = Path(__file__).resolve().parents[3]
    sys.modules["sdk"].__path__ = [str(repo_root / "sdk")]
    sys.modules["sdk.nexent"].__path__ = [str(repo_root / "sdk" / "nexent")]
    sys.modules["sdk.nexent.monitor"].__path__ = [
        str(repo_root / "sdk" / "nexent" / "monitor")
    ]
    monitoring_path = repo_root / "sdk" / "nexent" / "monitor" / "monitoring.py"
    spec = importlib.util.spec_from_file_location(
        "sdk.nexent.monitor.monitoring",
        monitoring_path
    )
    monitoring_module = importlib.util.module_from_spec(spec)
    if "sdk.nexent.monitor.monitoring" in sys.modules:
        original_modules["sdk.nexent.monitor.monitoring"] = sys.modules["sdk.nexent.monitor.monitoring"]
    sys.modules["sdk.nexent.monitor.monitoring"] = monitoring_module
    spec.loader.exec_module(monitoring_module)
    sys.modules["sdk.nexent.monitor"].monitoring = monitoring_module

    # Store for cleanup in pytest_unconfigure
    config._mocked_otel_modules = original_modules


def pytest_unconfigure(config):
    """
    Restore original OpenTelemetry modules after tests complete.
    """
    if hasattr(config, '_mocked_otel_modules'):
        for module_name, original_module in config._mocked_otel_modules.items():
            sys.modules[module_name] = original_module
