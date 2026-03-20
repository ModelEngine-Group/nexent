#!/usr/bin/env python3
"""Delete VM(s)."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import add_common_args, get_client_with_args


def main():
    parser = argparse.ArgumentParser(description="Delete VM(s)")
    add_common_args(parser)

    parser.add_argument("--vm-id", "-v", required=True, help="VM ID to delete")
    parser.add_argument("--wait", "-w", action="store_true", help="Wait for task completion")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    client, cfg = get_client_with_args(args)
    client.login()

    site_id = args.site_id or cfg.site_id
    if not site_id:
        print("Error: site-id is required")
        sys.exit(1)

    print(f"Deleting VM {args.vm_id}...")

    try:
        task_id = client.delete_vm(site_id, args.vm_id)
        print(f"Delete task started, task_id: {task_id}")

        result = {"success": True, "vm_id": args.vm_id, "task_id": task_id}

        if args.wait:
            print(f"Waiting for deletion to complete...")
            client.wait_for_task(site_id, task_id)
            result["deleted"] = True
            print(f"VM {args.vm_id} deleted successfully")

        if args.json:
            print(json.dumps(result, indent=2))

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()