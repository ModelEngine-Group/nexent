#!/usr/bin/env python3
"""
Performance benchmark tests for Nexent platform.

Measures:
  P-01: Single agent max concurrency (50 concurrent requests to same agent)
  P-02: Max concurrent agents (200 concurrent requests to different agents)
  P-03: API rate limit detection (sustained request rate)

Monitors system metrics (CPU, memory) during tests.

All test data uses perf_test_ prefix for safe rollback.
Run rollback_test_data.py after testing.

Usage:
    python test/perf/test_performance.py [--agents <count>] [--concurrency <n>]

Environment variables:
    NEXENT_BASE_URL   Nexent API base URL (default: http://localhost:8080)
    NEXENT_ADMIN_TOKEN  Admin auth token for API calls
    NEXENT_DB_URL     SQLAlchemy connection URL (for setup)
"""

import argparse
import json
import logging
import os
import statistics
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("perf_test")

BASE_URL = os.environ.get("NEXENT_BASE_URL", "http://localhost:8080").rstrip("/")
ADMIN_TOKEN = os.environ.get("NEXENT_ADMIN_TOKEN", "")
DB_URL = os.environ.get("NEXENT_DB_URL", "")

# Performance test parameters (can be modified)
P01_CONCURRENCY = 50       # P-01: concurrent requests to same agent
P02_AGENT_COUNT = 200      # P-02: number of different agents
P03_DURATION_SEC = 60      # P-03: duration for rate limit test
P03_REQUEST_INTERVAL = 0.1  # P-03: interval between requests (seconds)

TEST_TENANT_PREFIX = "perf_test_"
TEST_AGENT_PREFIX = "perf_test_perf_agent_"


# ---------------------------------------------------------------------------
# System metrics collection
# ---------------------------------------------------------------------------

class SystemMetrics:
    """Collects CPU and memory metrics during performance tests."""

    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self.cpu_samples: List[float] = []
        self.mem_samples: List[float] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        try:
            import psutil
            self._thread = threading.Thread(target=self._collect, args=(psutil,), daemon=True)
            self._thread.start()
            logger.info("System metrics collection started")
        except ImportError:
            logger.warning("psutil not installed, skipping system metrics")

    def _collect(self, psutil_module):
        while not self._stop.is_set():
            try:
                self.cpu_samples.append(psutil_module.cpu_percent(interval=None))
                mem = psutil_module.virtual_memory()
                self.mem_samples.append(mem.percent)
            except Exception:
                pass
            self._stop.wait(self.interval)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self.cpu_samples:
            logger.info(f"CPU: min={min(self.cpu_samples):.1f}% max={max(self.cpu_samples):.1f}% avg={statistics.mean(self.cpu_samples):.1f}%")
        if self.mem_samples:
            logger.info(f"MEM: min={min(self.mem_samples):.1f}% max={max(self.mem_samples):.1f}% avg={statistics.mean(self.mem_samples):.1f}%")

    def get_summary(self) -> Dict:
        return {
            "cpu": {
                "min": min(self.cpu_samples) if self.cpu_samples else None,
                "max": max(self.cpu_samples) if self.cpu_samples else None,
                "avg": statistics.mean(self.cpu_samples) if self.cpu_samples else None,
            },
            "memory": {
                "min": min(self.mem_samples) if self.mem_samples else None,
                "max": max(self.mem_samples) if self.mem_samples else None,
                "avg": statistics.mean(self.mem_samples) if self.mem_samples else None,
            },
        }


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def api_request(method: str, path: str, data: Optional[Dict] = None,
                timeout: int = 60) -> Tuple[int, Any, float]:
    """Make HTTP request and return (status, response, elapsed_ms)."""
    import urllib.request
    import urllib.error
    import json as json_mod

    url = f"{BASE_URL}{path}"
    body = None
    headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
    if data is not None:
        body = json_mod.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    start = time.time()

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed = (time.time() - start) * 1000
            status = resp.status
            resp_body = resp.read().decode("utf-8")
            try:
                return status, json_mod.loads(resp_body), elapsed
            except Exception:
                return status, resp_body, elapsed
    except urllib.error.HTTPError as e:
        elapsed = (time.time() - start) * 1000
        body = e.read().decode("utf-8")
        try:
            return e.code, json_mod.loads(body), elapsed
        except Exception:
            return e.code, body, elapsed
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return 0, str(e), elapsed

# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def create_test_tenant(tenant_id: str) -> str:
    status, resp, _ = api_request("POST", "/tenants", {
        "tenant_id": tenant_id,
        "tenant_name": f"Perf Test {tenant_id}",
    })
    if status in (200, 201):
        return resp.get("tenant_id", tenant_id)
    logger.warning(f"Could not create tenant {tenant_id}: status={status}")
    return tenant_id


def create_test_agent(tenant_id: str, agent_id: str, name: str) -> bool:
    status, resp, _ = api_request("POST", "/agent/update", {
        "agent_id": agent_id,
        "agent_info": {"name": name, "display_name": name, "description": "Performance test agent"},
    })
    if status in (200, 201):
        return True
    logger.warning(f"Could not create agent {agent_id}: status={status}, resp={str(resp)[:100]}")
    return False


def setup_test_environment(agent_count: int = 50) -> Dict:
    """Create test tenant and agents for performance testing."""
    logger.info("Setting up test environment...")
    tenant_id = f"{TEST_TENANT_PREFIX}perf"
    create_test_tenant(tenant_id)

    agent_ids = []
    for i in range(agent_count):
        aid = f"{TEST_AGENT_PREFIX}{i}"
        if create_test_agent(tenant_id, aid, f"Perf Agent {i}"):
            agent_ids.append(aid)
        if (i + 1) % 50 == 0:
            logger.info(f"  Created {i + 1}/{agent_count} agents...")

    logger.info(f"  Setup complete: {len(agent_ids)} agents ready")
    return {"tenant_id": tenant_id, "agent_ids": agent_ids}


# ---------------------------------------------------------------------------
# P-01: Single agent max concurrency
# ---------------------------------------------------------------------------

def test_P01_single_agent_concurrency(agent_id: str, concurrency: int = 50) -> Dict:
    """Send concurrent requests to the same agent and measure performance."""
    logger.info(f"=== P-01: Single agent concurrency ({concurrency} concurrent) ===")

    latencies: List[float] = []
    errors: List[Dict] = []
    lock = threading.Lock()

    def send_request():
        status, resp, elapsed = api_request("POST", "/agent/run", {
            "agent_id": agent_id,
            "message": "Hello, this is a performance test message.",
        }, timeout=120)
        with lock:
            latencies.append(elapsed)
            if status >= 400 or status == 0:
                errors.append({"status": status, "detail": str(resp)[:100]})
        return status

    start = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(send_request) for _ in range(concurrency)]
        results = [f.result() for f in as_completed(futures)]
    elapsed_total = time.time() - start

    success_count = sum(1 for r in results if 200 <= r < 400)
    error_count = len(results) - success_count

    if latencies:
        sorted_lat = sorted(latencies)
        p50 = sorted_lat[len(sorted_lat) // 2]
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)]
        p99 = sorted_lat[int(len(sorted_lat) * 0.99)] if len(sorted_lat) >= 100 else sorted_lat[-1]
        avg = statistics.mean(sorted_lat)
        min_lat = sorted_lat[0]
        max_lat = sorted_lat[-1]
    else:
        p50 = p95 = p99 = avg = min_lat = max_lat = 0

    result = {
        "test_id": "P-01",
        "test_name": "Single agent max concurrency",
        "concurrency": concurrency,
        "total_time_seconds": round(elapsed_total, 2),
        "success_count": success_count,
        "error_count": error_count,
        "success_rate": round(success_count / len(results) * 100, 1) if results else 0,
        "latency_ms": {
            "min": round(min_lat, 1),
            "p50": round(p50, 1),
            "p95": round(p95, 1),
            "p99": round(p99, 1),
            "max": round(max_lat, 1),
            "avg": round(avg, 1),
        },
        "errors_sample": errors[:5],
    }
    logger.info(f"  Success: {success_count}/{len(results)} ({result['success_rate']}%)")
    logger.info(f"  P50: {p50:.0f}ms, P95: {p95:.0f}ms, P99: {p99:.0f}ms")
    logger.info(f"  Total time: {elapsed_total:.1f}s")
    return result

# ---------------------------------------------------------------------------
# P-02: Max concurrent agents
# ---------------------------------------------------------------------------

def test_P02_multi_agent_concurrency(agent_ids: List[str], total_requests: int = 200) -> Dict:
    """Send concurrent requests to different agents and measure system-wide performance."""
    logger.info(f"=== P-02: Multi-agent concurrency ({total_requests} requests across {len(agent_ids)} agents) ===")

    latencies: List[float] = []
    status_codes: List[int] = []
    errors: List[Dict] = []
    lock = threading.Lock()

    def send_request(agent_id: str):
        status, resp, elapsed = api_request("POST", "/agent/run", {
            "agent_id": agent_id,
            "message": "Hello from performance test.",
        }, timeout=120)
        with lock:
            latencies.append(elapsed)
            status_codes.append(status)
            if status >= 400 or status == 0:
                errors.append({"agent_id": agent_id, "status": status, "detail": str(resp)[:100]})
        return status

    # Distribute requests across agents
    request_plan = []
    for i in range(total_requests):
        agent_id = agent_ids[i % len(agent_ids)]
        request_plan.append(agent_id)

    concurrency = min(200, total_requests)
    start = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(send_request, aid) for aid in request_plan]
        [f.result() for f in as_completed(futures)]
    elapsed_total = time.time() - start

    success_count = sum(1 for s in status_codes if 200 <= s < 400)
    error_count = len(status_codes) - success_count
    rate_429 = sum(1 for s in status_codes if s == 429)

    if latencies:
        sorted_lat = sorted(latencies)
        p50 = sorted_lat[len(sorted_lat) // 2]
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)]
        avg = statistics.mean(sorted_lat)
    else:
        p50 = p95 = avg = 0

    result = {
        "test_id": "P-02",
        "test_name": "Max concurrent agents",
        "total_requests": total_requests,
        "unique_agents": len(agent_ids),
        "concurrency": concurrency,
        "total_time_seconds": round(elapsed_total, 2),
        "requests_per_second": round(total_requests / elapsed_total, 1) if elapsed_total > 0 else 0,
        "success_count": success_count,
        "error_count": error_count,
        "rate_limit_429_count": rate_429,
        "success_rate": round(success_count / len(status_codes) * 100, 1) if status_codes else 0,
        "latency_ms": {
            "p50": round(p50, 1),
            "p95": round(p95, 1),
            "avg": round(avg, 1),
        },
        "status_code_distribution": {
            "2xx": sum(1 for s in status_codes if 200 <= s < 300),
            "4xx": sum(1 for s in status_codes if 400 <= s < 500),
            "5xx": sum(1 for s in status_codes if 500 <= s < 600),
            "0": sum(1 for s in status_codes if s == 0),
        },
        "errors_sample": errors[:5],
    }
    logger.info(f"  Success: {success_count}/{len(status_codes)} ({result['success_rate']}%)")
    logger.info(f"  429 Rate Limited: {rate_429}")
    logger.info(f"  Requests/sec: {result['requests_per_second']}")
    logger.info(f"  P50: {p50:.0f}ms, P95: {p95:.0f}ms")
    return result


# ---------------------------------------------------------------------------
# P-03: API rate limit detection
# ---------------------------------------------------------------------------

def test_P03_rate_limit(agent_id: str, duration_sec: int = 60, interval: float = 0.1) -> Dict:
    """Send sustained requests to detect API rate limit thresholds."""
    logger.info(f"=== P-03: API rate limit detection ({duration_sec}s) ===")

    latencies: List[float] = []
    status_codes: List[int] = []
    lock = threading.Lock()
    stop_event = threading.Event()

    def sustained_requests():
        while not stop_event.is_set():
            status, resp, elapsed = api_request("POST", "/agent/run", {
                "agent_id": agent_id,
                "message": "Rate limit test.",
            }, timeout=60)
            with lock:
                latencies.append(elapsed)
                status_codes.append(status)
            stop_event.wait(interval)

    metrics = SystemMetrics(interval=1.0)
    metrics.start()

    start = time.time()
    thread = threading.Thread(target=sustained_requests, daemon=True)
    thread.start()

    # Let it run for the specified duration
    time.sleep(duration_sec)
    stop_event.set()
    thread.join(timeout=5)

    elapsed_total = time.time() - start
    metrics.stop()

    total_requests = len(status_codes)
    rate_429 = sum(1 for s in status_codes if s == 429)
    rate_2xx = sum(1 for s in status_codes if 200 <= s < 300)

    if latencies:
        sorted_lat = sorted(latencies)
        p50 = sorted_lat[len(sorted_lat) // 2]
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)]
        avg = statistics.mean(sorted_lat)
    else:
        p50 = p95 = avg = 0

    result = {
        "test_id": "P-03",
        "test_name": "API rate limit detection",
        "duration_seconds": duration_sec,
        "total_requests": total_requests,
        "requests_per_minute": round(total_requests / elapsed_total * 60, 1) if elapsed_total > 0 else 0,
        "requests_per_second": round(total_requests / elapsed_total, 1) if elapsed_total > 0 else 0,
        "success_count": rate_2xx,
        "rate_limit_429_count": rate_429,
        "rate_limit_triggered": rate_429 > 0,
        "success_rate": round(rate_2xx / total_requests * 100, 1) if total_requests > 0 else 0,
        "latency_ms": {
            "p50": round(p50, 1),
            "p95": round(p95, 1),
            "avg": round(avg, 1),
        },
        "system_metrics": metrics.get_summary(),
    }
    logger.info(f"  Total requests: {total_requests}")
    logger.info(f"  RPM: {result['requests_per_minute']}")
    logger.info(f"  429 Rate Limited: {rate_429}")
    logger.info(f"  Rate limit triggered: {rate_429 > 0}")
    return result

# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Nexent performance benchmark tests")
    parser.add_argument("--agents", type=int, default=200, help="Number of test agents to create")
    parser.add_argument("--concurrency", type=int, default=50, help="P-01 concurrency level")
    parser.add_argument("--p02-requests", type=int, default=200, help="P-02 total requests")
    parser.add_argument("--p03-duration", type=int, default=60, help="P-03 duration in seconds")
    parser.add_argument("--skip-setup", action="store_true", help="Skip agent setup (use existing)")
    parser.add_argument("--base-url", default=BASE_URL, help="Nexent API base URL")
    parser.add_argument("--token", default=ADMIN_TOKEN, help="Admin auth token")
    args = parser.parse_args()

    global BASE_URL, ADMIN_TOKEN
    BASE_URL = args.base_url
    ADMIN_TOKEN = args.token

    logger.info(f"Nexent Performance Benchmark")
    logger.info(f"Base URL: {BASE_URL}")
    logger.info(f"Parameters: P01_concurrency={args.concurrency}, P02_requests={args.p02_requests}, P03_duration={args.p03_duration}")

    system_metrics = SystemMetrics(interval=1.0)

    # Setup
    agent_ids = []
    if not args.skip_setup:
        setup = setup_test_environment(agent_count=max(args.agents, args.concurrency))
        agent_ids = setup["agent_ids"]
    else:
        # Try to find existing test agents
        logger.info("Skipping setup, using existing agents...")
        status, resp, _ = api_request("GET", "/agent/list")
        if status == 200 and isinstance(resp, dict):
            agent_list = resp.get("agents", [])
            agent_ids = [a.get("agent_id") for a in agent_list if a.get("agent_id")]
            logger.info(f"  Found {len(agent_ids)} existing agents")

    if len(agent_ids) < 2:
        logger.error("Need at least 2 agents for performance tests. Run without --skip-setup.")
        sys.exit(1)

    results = []
    system_metrics.start()

    try:
        # P-01: Single agent concurrency
        p01_agent_id = agent_ids[0]
        result_p01 = test_P01_single_agent_concurrency(p01_agent_id, args.concurrency)
        results.append(result_p01)

        # P-02: Multi-agent concurrency
        result_p02 = test_P02_multi_agent_concurrency(agent_ids, args.p02_requests)
        results.append(result_p02)

        # P-03: Rate limit detection
        result_p03 = test_P03_rate_limit(p01_agent_id, args.p03_duration)
        results.append(result_p03)

    finally:
        system_metrics.stop()

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("PERFORMANCE TEST SUMMARY")
    logger.info(f"{'='*60}")
    for r in results:
        logger.info(f"\n  {r['test_id']}: {r['test_name']}")
        if "success_rate" in r:
            logger.info(f"    Success rate: {r['success_rate']}%")
        if "latency_ms" in r:
            lat = r["latency_ms"]
            logger.info(f"    Latency: P50={lat.get('p50', 'N/A')}ms P95={lat.get('p95', 'N/A')}ms")
        if "requests_per_second" in r:
            logger.info(f"    Throughput: {r['requests_per_second']} req/s")
        if "rate_limit_triggered" in r:
            logger.info(f"    Rate limit triggered: {r['rate_limit_triggered']}")

    # System metrics
    sys_summary = system_metrics.get_summary()
    if sys_summary.get("cpu", {}).get("avg") is not None:
        logger.info(f"\n  System CPU avg: {sys_summary['cpu']['avg']}%")
    if sys_summary.get("memory", {}).get("avg") is not None:
        logger.info(f"  System MEM avg: {sys_summary['memory']['avg']}%")

    # Save results
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "p01_concurrency": args.concurrency,
            "p02_requests": args.p02_requests,
            "p03_duration": args.p03_duration,
        },
        "system_metrics": sys_summary,
        "results": results,
    }
    output_path = "perf_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    logger.info(f"\nResults saved to {output_path}")
    logger.info("REMEMBER: Run rollback_test_data.py to clean up test data!")


if __name__ == "__main__":
    main()
