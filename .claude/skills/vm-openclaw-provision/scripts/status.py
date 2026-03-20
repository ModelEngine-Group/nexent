#!/usr/bin/env python3
"""Check task status."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import add_common_args, get_client_with_args


def main():
    parser = argparse.ArgumentParser(description="Check task status")
    add_common_args(parser)

    parser.add_argument("--task-id", "-t", required=True, help="Task ID to check")
    parser.add_argument("--wait", "-w", action="store_true", help="Wait for task completion")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    client, cfg = get_client_with_args(args)
    client.login()

    site_id = args.site_id or cfg.site_id
    if not site_id:
        print("Error: site-id is required")
        sys.exit(1)

    try:
        if args.wait:
            print(f"Waiting for task {args.task_id}...")
            client.wait_for_task(site_id, args.task_id)
            print(f"Task completed successfully")
            task = client.get_task(site_id, args.task_id)
        else:
            task = client.get_task(site_id, args.task_id)

        if args.json:
            print(json.dumps(task, indent=2))
        else:
            status = task.get("status", "N/A")
            progress = task.get("progress", "N/A")
            print(f"Task ID: {args.task_id}")
            print(f"Status: {status}")
            print(f"Progress: {progress}%")

            if "error" in task:
                print(f"Error: {task['error']}")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()