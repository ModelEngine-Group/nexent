"""Explicit runner/product URL selection for the ext-knowledge mock.

The mock is reached through two addresses: the runner-side control plane
(published loopback port) and the product-container-side root (compose DNS
name on the product network). Helpers here pick a side explicitly so a
single default URL can never serve both calling sides.

Which side to use:
- runner_url: control-plane calls (/_reset, /_mock/*, /_wire-log), direct
  asset fetches and latency measurements made by test code itself.
- product_url: values handed to the PRODUCT (outbound service params, model
  records, tool configuration) — the product fetches them from inside its
  container network.
- fault_model_base_url: OpenAI-compatible API base for model records —
  the product root plus /v1, so real wire traffic lands on
  /v1/chat/completions.

The env vars are exported by the suite worker's ext attach step; running a
case without them is an explicit error, never a silent fallback to the
controlled test-assets service (NEXENT_TEST_ASSETS_URL stays untouched).
"""
from __future__ import annotations

import os

# Imported helpers must never be collected as test functions by pytest.
__test__ = False

RUNNER_ENV = "NEXENT_EXT_KNOWLEDGE_RUNNER_URL"
PRODUCT_ENV = "NEXENT_EXT_KNOWLEDGE_PRODUCT_URL"


def _base(env_name: str) -> str:
    value = os.environ.get(env_name, "").strip()
    if not value:
        raise RuntimeError(
            f"{env_name} is required: declare the case dependency through "
            "required_mock_services and run it via the suite worker, or export "
            "the variable for an already-prepared environment"
        )
    return value.rstrip("/")


def runner_url(path: str = "") -> str:
    """Runner-side address (control plane, direct fetches, measurements)."""
    return f"{_base(RUNNER_ENV)}/{str(path).lstrip('/')}" if path else _base(RUNNER_ENV)


def product_url(path: str = "") -> str:
    """Product-side address for values embedded in product configuration."""
    return f"{_base(PRODUCT_ENV)}/{str(path).lstrip('/')}" if path else _base(PRODUCT_ENV)


def fault_model_base_url() -> str:
    """OpenAI-compatible API base for model records: product root + /v1."""
    return product_url("v1")
