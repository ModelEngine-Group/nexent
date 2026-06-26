"""
Admin Password Reset Script

Resets one or more user passwords via the backend internal API using admin
privileges. The script reads specs from a JSON config file (or inline JSON)
and sends them to the running backend server.

Usage:
    # Via config file (recommended):
    python scripts/reset_user_password.py --config passwords.json

    # Via inline JSON:
    python scripts/reset_user_password.py --json "{\"internal_key\":\"...\",\"backend_url\":\"...\",\"resets\":[{\"user_id\":\"...\",\"new_password\":\"...\"}]}"

JSON config format:
    {
      "internal_key": "your-service-role-key-here",
      "backend_url": "http://localhost:5013",
      "resets": [
        {
          "user_id": "supabase-user-id-uuid",
          "new_password": "NewSecurePass123"
        }
      ]
    }
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import httpx


def main():
    parser = argparse.ArgumentParser(
        description="Reset user passwords via backend internal API using admin privileges",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--config", type=Path,
        help="Path to JSON config file")
    group.add_argument(
        "--json", type=str,
        help="Inline JSON config string")
    args = parser.parse_args()

    # Load config
    if args.config:
        config: Dict[str, Any] = json.loads(args.config.read_text(encoding="utf-8"))
    else:
        config = json.loads(args.json)

    internal_key = config.get("internal_key", "").strip()
    backend_url = config.get("backend_url", "http://localhost:5013").rstrip("/")
    resets: List[Dict[str, Any]] = config.get("resets", [])

    if not internal_key:
        print("Error: 'internal_key' is required in JSON config.")
        sys.exit(1)
    if not resets:
        print("Error: 'resets' array is empty or missing.")
        sys.exit(1)

    print(f"\nResetting passwords for {len(resets)} user(s) via {backend_url} ...")
    print(f"Backend URL: {backend_url}")
    print(f"Reset count: {len(resets)}")
    print()

    succeeded = 0
    failed = 0

    for spec in resets:
        user_id = spec.get("user_id", "").strip()
        new_password = spec.get("new_password", "")

        if not user_id:
            print("[FAIL] user_id is missing")
            failed += 1
            continue

        if not new_password:
            print(f"[FAIL] new_password is missing for user_id={user_id}")
            failed += 1
            continue

        url = f"{backend_url}/api/nb/v1/internal/users/{user_id}/password"
        headers = {
            "Content-Type": "application/json",
            "X-Internal-Key": internal_key,
        }
        body = {"new_password": new_password}

        try:
            response = httpx.post(url, headers=headers, json=body, timeout=60.0)
        except httpx.ConnectError as e:
            print(f"[FAIL] Could not connect to backend at {backend_url}")
            print(f"       {e}")
            failed += 1
            continue
        except httpx.TimeoutException:
            print(f"[FAIL] Request timed out after 60s for user_id={user_id}")
            failed += 1
            continue
        except Exception as e:
            print(f"[FAIL] Unexpected error for user_id={user_id}: {e}")
            failed += 1
            continue

        if response.status_code == 401:
            print("[FAIL] Invalid internal key.")
            failed += 1
            continue

        if response.status_code != 200:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            print(f"[FAIL] user_id={user_id} -- {detail}")
            failed += 1
            continue

        data = response.json().get("data", {})
        print(f"[OK]   user_id={user_id} ({data.get('email', '?')})")
        succeeded += 1

    print()
    print("=" * 60)
    print(f"Results: {succeeded} succeeded, {failed} failed")
    print("=" * 60)
    print()

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
