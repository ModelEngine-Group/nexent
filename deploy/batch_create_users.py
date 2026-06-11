"""
Batch User Creation Script

Creates multiple users by reading from a CSV file via the Northbound API.
Uses Access Key authentication (Bearer token).

Usage:
    python batch_create_users.py --csv users.csv --token <access_key>

CSV Format:
    email,password,role
    user1@example.com,password123,USER
    user2@example.com,password456,DEV
    admin@example.com,adminpass,ADMIN

Roles: USER, DEV, ADMIN
"""

import argparse
import asyncio
import csv
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx


@dataclass
class BatchUserConfig:
    base_url: str = "http://localhost:5013/api/nb/v1"
    csv_path: str = ""
    token: str = ""
    concurrency: int = 5
    retry_count: int = 2
    retry_delay: float = 1.0


@dataclass
class UserCreateResult:
    email: str
    success: bool
    status_code: int
    message: str
    retry: int = 0


@dataclass
class BatchUserStats:
    total: int = 0
    created: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list = field(default_factory=list)
    results: list = field(default_factory=list)

    def add_result(self, result: UserCreateResult):
        self.results.append(result)
        if result.success:
            self.created += 1
        elif result.message == "EMAIL_ALREADY_EXISTS":
            self.skipped += 1
        else:
            self.failed += 1
            self.errors.append(f"{result.email}: {result.message}")


class BatchUserCreator:
    def __init__(self, config: BatchUserConfig):
        self.config = config
        self.stats = BatchUserStats()
        self._semaphore: Optional[asyncio.Semaphore] = None

    def get_headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.token}",
        }

    def load_csv_users(self) -> list[dict]:
        users = []
        path = Path(self.config.csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {self.config.csv_path}")

        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                email = row.get("email", "").strip()
                password = row.get("password", "").strip()
                role = row.get("role", "USER").strip().upper()

                if not email:
                    continue
                if role not in ("USER", "DEV", "ADMIN"):
                    role = "USER"

                users.append({"email": email, "password": password, "role": role})

        return users

    async def create_user(
        self,
        client: httpx.AsyncClient,
        email: str,
        password: str,
        role: str,
    ) -> UserCreateResult:
        url = f"{self.config.base_url}/users"
        payload = {"email": email, "password": password, "role": role}
        headers = self.get_headers()

        try:
            response = await client.post(
                url, json=payload, headers=headers, timeout=30.0
            )

            if response.status_code == 200:
                return UserCreateResult(
                    email=email, success=True, status_code=200, message="Created"
                )
            elif response.status_code == 409:
                data = response.json()
                detail = data.get("detail", "")
                return UserCreateResult(
                    email=email,
                    success=False,
                    status_code=409,
                    message="EMAIL_ALREADY_EXISTS" if "EMAIL_ALREADY_EXISTS" in detail else detail,
                )
            else:
                data = response.json()
                detail = data.get("detail", str(response.status_code))
                return UserCreateResult(
                    email=email,
                    success=False,
                    status_code=response.status_code,
                    message=detail,
                )

        except httpx.TimeoutException:
            return UserCreateResult(
                email=email, success=False, status_code=0, message="Timeout"
            )
        except Exception as e:
            return UserCreateResult(
                email=email, success=False, status_code=0, message=str(e)
            )

    async def create_user_with_retry(
        self, client: httpx.AsyncClient, email: str, password: str, role: str
    ) -> UserCreateResult:
        for attempt in range(self.config.retry_count + 1):
            result = await self.create_user(client, email, password, role)
            result.retry = attempt

            if result.success:
                return result

            # Don't retry for conflicts (email exists)
            if result.message == "EMAIL_ALREADY_EXISTS":
                return result

            # Don't retry for auth errors
            if result.status_code in (401, 403):
                return result

            if attempt < self.config.retry_count:
                await asyncio.sleep(self.config.retry_delay * (attempt + 1))

        return result

    async def worker(
        self,
        worker_id: int,
        client: httpx.AsyncClient,
        users: list[dict],
    ):
        for user in users:
            async with self._semaphore:
                result = await self.create_user_with_retry(
                    client, user["email"], user["password"], user["role"]
                )
                self.stats.add_result(result)

                status_icon = "[OK]" if result.success else "[FAIL]"
                retry_info = f" (retry {result.retry})" if result.retry > 0 else ""
                print(f"  {status_icon} {result.email}: {result.message}{retry_info}")

    async def run(self):
        users = self.load_csv_users()
        self.stats.total = len(users)

        print(f"\n{'='*60}")
        print(f"Batch User Creation")
        print(f"{'='*60}")
        print(f"Target URL:     {self.config.base_url}/users")
        print(f"CSV File:      {self.config.csv_path}")
        print(f"Total Users:   {len(users)}")
        print(f"Concurrency:   {self.config.concurrency}")
        print(f"Retries:       {self.config.retry_count}")
        print(f"{'='*60}\n")

        if not users:
            print("No users found in CSV file.")
            return

        self._semaphore = asyncio.Semaphore(self.config.concurrency)

        limits = httpx.Limits(
            max_keepalive_connections=self.config.concurrency,
            max_connections=self.config.concurrency * 2,
        )

        async with httpx.AsyncClient(limits=limits, follow_redirects=True) as client:
            tasks = []
            batch_size = max(1, len(users) // self.config.concurrency)

            for i in range(0, len(users), batch_size):
                batch = users[i : i + batch_size]
                worker_id = i // batch_size
                task = asyncio.create_task(self.worker(worker_id, client, batch))
                tasks.append(task)

            start_time = time.time()
            await asyncio.gather(*tasks)
            elapsed = time.time() - start_time

        self.stats.errors  # already populated
        return elapsed

    def print_results(self, elapsed: float):
        print(f"\n{'='*60}")
        print(f"Batch User Creation Results")
        print(f"{'='*60}")
        print(f"Total:      {self.stats.total}")
        print(f"Created:    {self.stats.created}")
        print(f"Skipped:    {self.stats.skipped} (email already exists)")
        print(f"Failed:     {self.stats.failed}")
        print(f"Duration:   {elapsed:.2f}s")
        print(f"{'='*60}")

        if self.stats.failed > 0:
            print(f"\nFailed Users:")
            for err in self.stats.errors[:10]:
                print(f"  - {err}")
            if len(self.stats.errors) > 10:
                print(f"  ... and {len(self.stats.errors) - 10} more")

        if self.stats.skipped > 0:
            print(f"\nSkipped Users (already exist):")
            for r in self.stats.results:
                if r.message == "EMAIL_ALREADY_EXISTS":
                    print(f"  - {r.email}")

        print(f"\n{'='*60}\n")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Batch User Creation Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:5013/api/nb/v1",
        help="Base URL of the API (default: http://localhost:5013/api/nb/v1)",
    )
    parser.add_argument(
        "--csv",
        required=True,
        help="Path to CSV file containing users",
    )
    parser.add_argument(
        "--token",
        required=True,
        help="Access Key for authentication (Bearer token)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Number of concurrent requests (default: 5)",
    )
    parser.add_argument(
        "--retry",
        type=int,
        default=2,
        help="Number of retries on failure (default: 2)",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    config = BatchUserConfig(
        base_url=args.base_url.rstrip("/"),
        csv_path=args.csv,
        token=args.token,
        concurrency=args.concurrency,
        retry_count=args.retry,
    )

    try:
        creator = BatchUserCreator(config)
        elapsed = await creator.run()
        creator.print_results(elapsed)

        if creator.stats.failed > 0:
            sys.exit(1)

    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
