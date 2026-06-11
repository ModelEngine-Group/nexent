"""
Northbound API Load Test Script

This script performs concurrent load testing on the Northbound API endpoints.
Tests 100 concurrent requests to measure performance under load.

Usage:
    python load_test.py [--base-url URL] [--access-key KEY] [--concurrency N]
                       [--duration SECONDS] [--endpoint ENDPOINT]

Examples:
    # Test health endpoint with 100 concurrent requests
    python load_test.py --endpoint health --concurrency 100

    # Test chat/run endpoint with 100 concurrent requests
    python load_test.py --endpoint chat --concurrency 100

    # Run for 60 seconds with 100 concurrent requests
    python load_test.py --duration 60 --concurrency 100

    # Custom target
    python load_test.py --base-url http://localhost:5013/api --concurrency 100
"""

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx


@dataclass
class LoadTestConfig:
    base_url: str = "http://localhost:5013/api"
    access_key: str = "nexent-1bd1cef12a6c18b2d33496f9"
    concurrency: int = 100
    duration: Optional[int] = None
    endpoint: str = "health"
    warmup_requests: int = 5


@dataclass
class RequestResult:
    success: bool
    status_code: int
    response_time_ms: float
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class LoadTestStats:
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    response_times: list = field(default_factory=list)
    status_codes: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)

    def add_result(self, result: RequestResult):
        self.total_requests += 1
        if result.success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
            if result.error:
                self.errors.append(result.error)
        self.response_times.append(result.response_time_ms)
        self.status_codes[result.status_code] = self.status_codes.get(result.status_code, 0) + 1

    def get_summary(self) -> dict:
        if not self.response_times:
            return {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "success_rate": "0%",
                "avg_response_time_ms": 0,
                "min_response_time_ms": 0,
                "max_response_time_ms": 0,
            }

        sorted_times = sorted(self.response_times)
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": f"{(self.successful_requests / self.total_requests * 100):.2f}%",
            "avg_response_time_ms": round(statistics.mean(self.response_times), 2),
            "min_response_time_ms": round(min(self.response_times), 2),
            "max_response_time_ms": round(max(self.response_times), 2),
            "p50_response_time_ms": round(sorted_times[len(sorted_times) // 2], 2),
            "p90_response_time_ms": round(sorted_times[int(len(sorted_times) * 0.9)], 2),
            "p95_response_time_ms": round(sorted_times[int(len(sorted_times) * 0.95)], 2),
            "p99_response_time_ms": round(sorted_times[int(len(sorted_times) * 0.99)], 2),
            "requests_per_second": round(self.total_requests / (max(self.response_times) / 1000), 2),
        }


class NorthboundLoadTester:
    def __init__(self, config: LoadTestConfig):
        self.config = config
        self.stats = LoadTestStats()
        self.stats_lock = asyncio.Lock()
        self._running = True

    def get_headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "X-Request-Id": str(uuid.uuid4()),
        }
        if self.config.access_key:
            headers["Authorization"] = f"Bearer {self.config.access_key}"
        return headers

    def get_endpoint_path(self) -> str:
        endpoints = {
            "health": "/nb/v1/health",
            "agents": "/nb/v1/agents",
            "conversations": "/nb/v1/conversations",
            "chat": "/nb/v1/chat/run",
        }
        return endpoints.get(self.config.endpoint, "/nb/v1/health")

    def get_chat_payload(self) -> dict:
        return {
            "query": "Hello, this is a load test message.",
            "agent_name": "default",
            "conversation_id": None,
            "meta_data": {"source": "load_test", "test_id": str(uuid.uuid4())},
        }

    async def make_request(
        self, client: httpx.AsyncClient, endpoint_path: str
    ) -> RequestResult:
        url = f"{self.config.base_url}{endpoint_path}"
        headers = self.get_headers()
        start_time = time.time()

        try:
            if self.config.endpoint == "chat":
                response = await client.post(
                    url, json=self.get_chat_payload(), headers=headers, timeout=120.0
                )
            else:
                response = await client.get(url, headers=headers, timeout=30.0)

            response_time_ms = (time.time() - start_time) * 1000
            success = 200 <= response.status_code < 300

            return RequestResult(
                success=success,
                status_code=response.status_code,
                response_time_ms=response_time_ms,
            )
        except httpx.TimeoutException:
            return RequestResult(
                success=False,
                status_code=0,
                response_time_ms=(time.time() - start_time) * 1000,
                error="Timeout",
            )
        except Exception as e:
            return RequestResult(
                success=False,
                status_code=0,
                response_time_ms=(time.time() - start_time) * 1000,
                error=str(e),
            )

    async def worker(
        self,
        worker_id: int,
        client: httpx.AsyncClient,
        endpoint_path: str,
        request_count: int,
    ):
        for i in range(request_count):
            if not self._running:
                break
            result = await self.make_request(client, endpoint_path)
            async with self.stats_lock:
                self.stats.add_result(result)

            if (worker_id + i) % 10 == 0:
                await asyncio.sleep(0.01)

    async def warmup(self, client: httpx.AsyncClient, endpoint_path: str):
        print("Warming up...")
        for _ in range(self.config.warmup_requests):
            await self.make_request(client, endpoint_path)
        print("Warmup complete.")

    async def run_load_test(self):
        endpoint_path = self.get_endpoint_path()
        print(f"\n{'='*60}")
        print(f"Northbound API Load Test")
        print(f"{'='*60}")
        print(f"Target URL:      {self.config.base_url}{endpoint_path}")
        print(f"Concurrency:     {self.config.concurrency}")
        print(f"Duration:        {self.config.duration or 'N/A'}")
        print(f"Endpoint:        {self.config.endpoint}")
        print(f"{'='*60}\n")

        limits = httpx.Limits(max_keepalive_connections=self.config.concurrency, max_connections=self.config.concurrency * 2)
        async with httpx.AsyncClient(limits=limits, follow_redirects=True) as client:
            await self.warmup(client, endpoint_path)

            self._running = True
            start_time = time.time()

            if self.config.duration:
                tasks = []
                requests_per_worker = self.config.duration
                for i in range(self.config.concurrency):
                    task = asyncio.create_task(
                        self.worker(i, client, endpoint_path, requests_per_worker)
                    )
                    tasks.append(task)
                await asyncio.gather(*tasks)
            else:
                tasks = []
                for i in range(self.config.concurrency):
                    task = asyncio.create_task(
                        self.worker(i, client, endpoint_path, 1)
                    )
                    tasks.append(task)
                await asyncio.gather(*tasks)

            elapsed_time = time.time() - start_time

            summary = self.stats.get_summary()
            summary["elapsed_time_seconds"] = round(elapsed_time, 2)
            summary["throughput_rps"] = round(self.stats.total_requests / elapsed_time, 2)

            self._running = False
            return summary

    def print_results(self, summary: dict):
        print(f"\n{'='*60}")
        print(f"Load Test Results")
        print(f"{'='*60}")
        print(f"Total Requests:       {summary['total_requests']}")
        print(f"Successful:            {summary['successful_requests']}")
        print(f"Failed:                {summary['failed_requests']}")
        print(f"Success Rate:          {summary['success_rate']}")
        print(f"Duration:               {summary['elapsed_time_seconds']}s")
        print(f"Throughput:            {summary['throughput_rps']} req/s")
        print(f"\nResponse Times:")
        print(f"  Average:             {summary['avg_response_time_ms']:.2f} ms")
        print(f"  Min:                 {summary['min_response_time_ms']:.2f} ms")
        print(f"  Max:                 {summary['max_response_time_ms']:.2f} ms")
        print(f"  P50 (Median):         {summary.get('p50_response_time_ms', 'N/A'):.2f} ms")
        print(f"  P90:                  {summary.get('p90_response_time_ms', 'N/A'):.2f} ms")
        print(f"  P95:                  {summary.get('p95_response_time_ms', 'N/A'):.2f} ms")
        print(f"  P99:                  {summary.get('p99_response_time_ms', 'N/A'):.2f} ms")

        if self.stats.status_codes:
            print(f"\nStatus Codes:")
            for code, count in sorted(self.stats.status_codes.items()):
                percentage = count / summary['total_requests'] * 100
                print(f"  {code}: {count} ({percentage:.1f}%)")

        if self.stats.errors:
            print(f"\nErrors (first 5):")
            for error in self.stats.errors[:5]:
                print(f"  - {error}")

        print(f"{'='*60}\n")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Northbound API Load Test Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:5013/api",
        help="Base URL of the API (default: http://localhost:5013/api)",
    )
    parser.add_argument(
        "--access-key",
        default="",
        help="Access key for authentication (Bearer token)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=100,
        help="Number of concurrent requests (default: 100)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Test duration in seconds (default: runs until all requests complete)",
    )
    parser.add_argument(
        "--endpoint",
        choices=["health", "agents", "conversations", "chat"],
        default="health",
        help="Endpoint to test (default: health)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=5,
        help="Number of warmup requests (default: 5)",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    config = LoadTestConfig(
        base_url=args.base_url.rstrip("/"),
        access_key=args.access_key,
        concurrency=args.concurrency,
        duration=args.duration,
        endpoint=args.endpoint,
        warmup_requests=args.warmup,
    )

    tester = NorthboundLoadTester(config)
    summary = await tester.run_load_test()
    tester.print_results(summary)

    if summary["failed_requests"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
