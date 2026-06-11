"""
Tenant Provisioning Script

Provisions one or more tenants with admin users and optional members via the
backend internal API. The script reads tenant specs from a JSON config file
(or inline JSON) and sends them to the running backend server.

Usage:
    # Via config file (recommended):
    python scripts/provision_tenant.py --config tenants.json

    # Via inline JSON:
    python scripts/provision_tenant.py --json '{"internal_key":"...","tenants":[...]}'

JSON config format:
    {
      "internal_key": "your-service-role-key-here",
      "backend_url": "http://localhost:5013",
      "tenants": [
        {
          "tenant_name": "Acme Corp",
          "admin_email": "admin@acme.com",
          "admin_password": "SecurePass123",
          "users": [
            { "email": "alice@acme.com", "password": "Pass1", "role": "USER" },
            { "email": "bob@acme.com",   "password": "Pass2", "role": "DEV" }
          ]
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
        description="Provision tenants with admin users and optional members via backend API",
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
    tenants: List[Dict[str, Any]] = config.get("tenants", [])

    if not internal_key:
        print("Error: 'internal_key' is required in JSON config.")
        sys.exit(1)
    if not tenants:
        print("Error: 'tenants' array is empty or missing.")
        sys.exit(1)

    url = f"{backend_url}/api/nb/v1/internal/provision"
    headers = {
        "Content-Type": "application/json",
        "X-Internal-Key": internal_key,
    }
    body = {"tenants": tenants}

    print(f"\nProvisioning {len(tenants)} tenant(s) via {url} ...")
    print(f"Backend URL:  {backend_url}")
    print(f"Tenant count: {len(tenants)}")
    print()

    try:
        response = httpx.post(url, headers=headers, json=body, timeout=60.0)
    except httpx.ConnectError as e:
        print(f"Error: Could not connect to backend at {backend_url}")
        print(f"  {e}")
        sys.exit(1)
    except httpx.TimeoutException:
        print(f"Error: Request timed out after 60s")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    if response.status_code == 401:
        print("Error: Invalid internal key. Check 'internal_key' in your JSON config.")
        sys.exit(1)

    if response.status_code != 200:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        print(f"Error: Backend returned {response.status_code}")
        print(f"  {detail}")
        sys.exit(1)

    data = response.json()
    results: List[Dict[str, Any]] = data.get("data", [])

    print("=" * 60)
    print(f"Provisioning Results ({len(results)} tenant(s))")
    print("=" * 60)

    succeeded = 0
    failed = 0

    for result in results:
        print()
        print(f"  Tenant:   {result.get('tenant_name', '?')}")
        print(f"  Tenant ID: {result.get('tenant_id', '?')}")
        admin = result.get("admin", {})
        print(f"  Admin:    {admin.get('email', '?')}")
        print(f"  Access Key: {admin.get('access_key', '?')}")

        users = result.get("users", [])
        if users:
            print(f"  Users:    {len(users)}")
            for u in users:
                icon = {"created": "[OK]", "skipped": "[SKIP]", "failed": "[FAIL]"}.get(u.get("status"), "[??]")
                reason = f" — {u.get('reason')}" if u.get("reason") else ""
                print(f"    {icon} {u.get('email', '?')} ({u.get('role', '?')}){reason}")

        if result.get("tenant_id"):
            succeeded += 1
        else:
            failed += 1

    print()
    print("=" * 60)
    print(f"  Succeeded: {succeeded}")
    print(f"  Failed:    {failed}")
    print("=" * 60)
    print()
    print("IMPORTANT: Save each Access Key. They are NOT stored anywhere else.")
    print()

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
