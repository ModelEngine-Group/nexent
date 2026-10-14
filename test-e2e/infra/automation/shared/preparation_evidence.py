"""Typed prerequisite failure receipts, distinct from product acceptance."""
import asyncio
import json
import os
import re

from shared.asset_registry import AssetDependencyError, AssetTimeoutError, runtime_dir
from shared.config import load_secret_env


def safe_reason(value):
    text = str(value)
    values = dict(os.environ)
    try:
        values.update(load_secret_env())
    except (OSError, RuntimeError, ValueError):
        pass
    for key, secret in sorted(values.items(), key=lambda item: len(item[1]), reverse=True):
        if len(secret) >= 4 and re.search(r'PASSWORD|SECRET|TOKEN|API_?KEY', key, re.I):
            text = text.replace(secret, '[REDACTED]')
    return re.sub(r'(authorization|api[-_ ]?key|password)\s*[:=]\s*[^\s,;]+',
                  r'\1=[REDACTED]', text, flags=re.I)[:2000]


def failure_receipt(exc):
    dependency = isinstance(exc, AssetDependencyError)
    return {
        'result': 'BLOCKED_BY_DEPENDENCY' if dependency else
                  ('TIMEOUT' if isinstance(exc, AssetTimeoutError) else 'BLOCKED'),
        'error_type': type(exc).__name__,
        # Arbitrary exceptions may embed request headers/full bodies. Retain
        # the class plus the local process log, not those bodies in the report.
        'reason': safe_reason(exc) if dependency else type(exc).__name__,
        'asset_role': f'{exc.section}.{exc.key}' if dependency else None,
        'dependency_case_id': exc.dependency_case_id if dependency else None,
    }


def record_failure(exc):
    root = runtime_dir()
    receipt = failure_receipt(exc)
    if root:
        # The runtime directory may not exist yet when a prerequisite fails
        # before any preparation step ran (e.g. the ext attach gate).
        root.mkdir(parents=True, exist_ok=True)
        (root / 'preparation-failure.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


def run_preparation(operation):
    try:
        return asyncio.run(operation)
    except Exception as exc:
        record_failure(exc)
        raise
