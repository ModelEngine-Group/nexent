"""Smoke test: verify OTel traces reach Langfuse Cloud."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "sdk"))
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from dotenv import load_dotenv
load_dotenv(override=True)

print("1. Checking env vars...")
for var in ["ENABLE_TELEMETRY", "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_AUTHORIZATION"]:
    val = os.getenv(var, "")
    display = "***REDACTED***" if "AUTHORIZATION" in var else val
    print(f"   {var} = {display or '(not set)'}")

print("\n2. Initializing monitoring...")
from utils.monitoring import monitoring_manager
print(f"   is_enabled = {monitoring_manager.is_enabled}")
if not monitoring_manager.is_enabled:
    print("   ABORT: monitoring is disabled. Check ENABLE_TELEMETRY and OTel deps.")
    sys.exit(1)

print("\n3. Sending test trace...")
with monitoring_manager.trace_operation("test.smoke_test", "CHAIN") as span:
    if span:
        span.set_attribute("test.message", "Hello from nexent context module")
        span.set_attribute("test.timestamp", time.time())
        print(f"   span created: test.smoke_test")
    else:
        print("   WARNING: span is None (tracer not initialized)")

print("\n4. Flushing (waiting for batch export)...")
time.sleep(3)

if monitoring_manager._tracer_provider:
    monitoring_manager._tracer_provider.force_flush()
    print("   force_flush done")

print("\nDone. Check Langfuse UI:")
print("  https://jp.cloud.langfuse.com -> Traces -> look for 'test.smoke_test'")
