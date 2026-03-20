#!/usr/bin/env python3
"""Modify VM configuration (CPU, memory)."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import add_common_args, get_client_with_args


def main():
    parser = argparse.ArgumentParser(description="Modify VM configuration")
    add_common_args(parser)

    parser.add_argument("--vm-id", "-v", required=True, help="VM ID to modify")
    parser.add_argument("--cpu", type=int, help="New CPU cores")
    parser.add_argument("--memory", type=int, help="New memory in MB")
    parser.add_argument("--wait", "-w", action="store_true", help="Wait for task completion")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if not args.cpu and not args.memory:
        print("Error: At least one of --cpu or --memory is required")
        parser.print_help()
        sys.exit(1)

    client, cfg = get_client_with_args(args)
    client.login()

    site_id = args.site_id or cfg.site_id
    if not site_id:
        print("Error: site-id is required")
        sys.exit(1)

    result = {"success": True, "vm_id": args.vm_id}

    try:
        if args.cpu:
            print(f"Setting CPU to {args.cpu} cores...")
            task_id = client.modify_vm_cpu(site_id, args.vm_id, args.cpu)
            result["cpu"] = args.cpu
            result["cpu_task_id"] = task_id
            print(f"CPU modify task started, task_id: {task_id}")

            if args.wait:
                client.wait_for_task(site_id, task_id)
                result["cpu_modified"] = True
                print(f"CPU modified successfully")

        if args.memory:
            print(f"Setting memory to {args.memory} MB...")
            task_id = client.modify_vm_memory(site_id, args.vm_id, args.memory)
            result["memory"] = args.memory
            result["memory_task_id"] = task_id
            print(f"Memory modify task started, task_id: {task_id}")

            if args.wait:
                client.wait_for_task(site_id, task_id)
                result["memory_modified"] = True
                print(f"Memory modified successfully")

        if args.json:
            print(json.dumps(result, indent=2))

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()