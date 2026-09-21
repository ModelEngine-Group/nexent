"""Shared building blocks for the ext-knowledge mock service.

Each external-knowledge route set (dify / datamate / idata / ragflow /
haotian / assets) keeps its own StateStore instance so state corruption or
resets in one service never leak into another. FaultInjector and WireLog are
process-wide singletons driven by the unified control plane (control.py).

Style and semantics deliberately mirror the AIDP management mock at
test/ext_components/aidp/mock_servers/aidp_mgmt_mock_server.py.
"""
import json
import logging
import os
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from urllib.parse import quote

logger = logging.getLogger("ext_knowledge_mock")

BASE_DIR = Path(__file__).resolve().parent
SEEDS_DIR = BASE_DIR / "seeds"
STATE_DIR = BASE_DIR / "_state"

# Route-set prefixes mounted by server.py. The AIDP protocol family lives at
# the ROOT of this service (no prefix) on purpose: the product reconstructs
# AIDP image URLs keeping only scheme+netloc from AIDP_SERVER_URL (dropping
# any base path) and allowlists paths starting with /KnowledgeBase/Tenants/,
# so a prefixed AIDP base would break the image flow entirely. The fault
# provider is root-mounted as /fault/v1 for the same reason real model
# gateways are: an OpenAI-compatible base_url is the gateway root + path.
SERVICE_PREFIXES: Dict[str, str] = {
    "dify": "/dify",
    "datamate": "/datamate",
    "idata": "/idata",
    "ragflow": "/ragflow",
    "haotian": "/haotian",
    "assets": "/assets",
    "fault": "/fault",
}
AIDP_PREFIXES = ("/KnowledgeBase", "/ModelService")

# Mock API keys. Single fixed values, same philosophy as the AIDP mock's
# EXPECTED_API_KEY: visible literals in source, never real credentials.
DIFY_API_KEY = "mock-dify-key"
IDATA_API_KEY = "mock-idata-key"
RAGFLOW_API_KEY = "mock-ragflow-key"
HAOTIAN_AUTHORIZATION = "Bearer mock-haotian-key"


def service_for_path(path: str) -> Optional[str]:
    """Map a request path to the route-set/service name it belongs to."""
    for service, prefix in SERVICE_PREFIXES.items():
        if path == prefix or path.startswith(prefix + "/"):
            return service
    if path.startswith(AIDP_PREFIXES):
        return "aidp"
    return None


def require_bearer(authorization: Optional[str]) -> None:
    """401 unless a non-empty Bearer token is present.

    Any token value is accepted: wrong-key scenarios are injected through
    the fault-injection control plane (POST /_mock/fail-next, status=401)
    instead of baking a second credential into the seeds.
    """
    if (
        not authorization
        or not authorization.startswith("Bearer ")
        or not authorization[len("Bearer "):].strip()
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def require_authorization(authorization: Optional[str]) -> None:
    """401 unless some non-empty Authorization header is present (raw value,
    not necessarily Bearer) — mirrors the Haotian connector contract."""
    if not authorization or not authorization.strip():
        raise HTTPException(status_code=401, detail="Missing Authorization header")


def content_disposition(filename: str) -> str:
    """Content-Disposition with an ASCII fallback plus RFC 5987 UTF-8 name.

    HTTP headers are latin-1 only, so a raw non-ASCII filename cannot go into
    the header verbatim; the product's download proxies parse both forms.
    """
    ascii_name = "".join(
        ch if 32 <= ord(ch) < 127 and ch not in {'"', "\\"} else "_"
        for ch in filename
    )
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )


def term_boost(query: str, haystack: str, bonus: float = 0.05, cap: float = 0.15) -> float:
    """Deterministic relevance boost: +bonus per query term hit, capped.

    Same scoring idea as the AIDP mock's FusionSearch so retrieval results
    stay stable and reproducible across runs.
    """
    terms = [t.strip().lower() for t in query.split() if t.strip()]
    lowered = haystack.lower()
    return min(bonus * sum(1 for t in terms if t in lowered), cap)


class StateStore:
    """Seed-backed persistent state for one route set.

    Startup order: persisted state file wins when present (so data created in
    interactive sessions survives restarts); otherwise the seed file is
    loaded and written out. ``reset()`` drops runtime state back to seeds and
    re-persists, keeping disk and memory consistent.
    """

    def __init__(self, name: str):
        self.name = name
        self.seed_file = SEEDS_DIR / f"{name}.json"
        self.state_file = STATE_DIR / f"{name}.json"
        self.data: Dict[str, Any] = {}
        self._load()

    def _load_seed(self) -> Dict[str, Any]:
        if not self.seed_file.exists():
            logger.warning("STATE  seed file missing for %s: %s", self.name, self.seed_file)
            return {}
        return json.loads(self.seed_file.read_text(encoding="utf-8"))

    def _load(self) -> None:
        if self.state_file.exists():
            try:
                self.data = json.loads(self.state_file.read_text(encoding="utf-8"))
                if not isinstance(self.data, dict):
                    raise ValueError("state payload is not an object")
                logger.info("STATE LOAD  %s restored from %s", self.name, self.state_file)
                return
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                logger.warning(
                    "STATE LOAD FAILED  %s unreadable (%s); falling back to seeds",
                    self.name, exc,
                )
        self.data = self._load_seed()
        self.save()
        logger.info("STATE INIT  %s seeded -> %s", self.name, self.state_file)

    def save(self) -> None:
        """Atomically persist state (tmp file + rename, mirrors AIDP mock)."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_file.with_suffix(".json.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.state_file)
        except OSError as exc:
            logger.warning("STATE SAVE FAILED  %s: %s", self.state_file, exc)

    def reset(self) -> None:
        self.data = self._load_seed()
        self.save()
        logger.info("STATE RESET  %s restored to seeds", self.name)


class FaultInjector:
    """Per-service fail-next counters and latency injection.

    Counters are deliberately in-memory only (same semantics as the AIDP
    mock): every restart starts with a clean failure plan.
    """

    def __init__(self) -> None:
        self._fail_remaining: Dict[str, int] = {}
        self._fail_status: Dict[str, int] = {}
        self._latency_ms: Dict[str, float] = {}

    def schedule(self, service: str, count: int, status: int = 503) -> None:
        self._fail_remaining[service] = count
        self._fail_status[service] = status
        logger.info(
            "MOCK SCHEDULE  service=%s next %d requests -> status %d",
            service, count, status,
        )

    def pop_failure(self, service: str) -> Optional[int]:
        """Consume one scheduled failure; returns the status code or None."""
        remaining = self._fail_remaining.get(service, 0)
        if remaining <= 0:
            return None
        self._fail_remaining[service] = remaining - 1
        return self._fail_status.get(service, 503)

    def clear_failures(self, service: Optional[str] = None) -> None:
        if service is None:
            self._fail_remaining.clear()
            self._fail_status.clear()
        else:
            self._fail_remaining.pop(service, None)
            self._fail_status.pop(service, None)

    def set_latency(self, service: str, delay_ms: float) -> None:
        self._latency_ms[service] = delay_ms
        logger.info("MOCK LATENCY  service=%s delay=%.1fms", service, delay_ms)

    def get_latency(self, service: str) -> float:
        return self._latency_ms.get(service, 0.0)

    def reset(self, service: Optional[str] = None) -> None:
        self.clear_failures(service)
        if service is None:
            self._latency_ms.clear()
        else:
            self._latency_ms.pop(service, None)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "fail_remaining": dict(self._fail_remaining),
            "fail_status": dict(self._fail_status),
            "latency_ms": dict(self._latency_ms),
        }


class WireLog:
    """Bounded in-memory request log queried via GET /_wire-log for evidence.

    Mirrors the wire-log/observation role of the suite's test-mcp service and
    the A2A mock control plane, but local to this process.
    """

    def __init__(self, maxlen: int = 2000) -> None:
        self._records: deque = deque(maxlen=maxlen)

    def record(
        self,
        service: Optional[str],
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        body: Optional[str] = None,
    ) -> None:
        self._records.append({
            "service": service or "control",
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "request_body": body,
        })

    def query(self, service: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        records = list(self._records)
        if service:
            records = [r for r in records if r["service"] == service]
        return records[-limit:]

    def clear(self) -> None:
        self._records.clear()
