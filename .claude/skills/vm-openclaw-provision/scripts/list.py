#!/usr/bin/env python3
"""List sites, VMs, or IP allocations."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import add_common_args, get_client_with_args


def list_vms(client, cfg, args):
    site_id = cfg.site_id
    if not site_id:
        print("Error: site-id is required for listing VMs")
        sys.exit(1)

    vms = client.get_vms(site_id)
    if args.json:
        print(json.dumps(vms, indent=2))
    else:
        print(f"Found {len(vms)} VM(s) in site {site_id}:")
        for vm in vms:
            if isinstance(vm, dict):
                name = vm.get("name", "N/A")
                vm_id = vm.get("id") or vm.get("vm_id") or vm.get("urn", "N/A")
                status = vm.get("status", "N/A")
                print(f"  - {name} ({vm_id}): {status}")

def get_vm(client, cfg, args):
    site_id = cfg.site_id
    vm_id = args.vm_id
    if not site_id or not vm_id:
        print("Error: site-id/vm_id is required for get VM")
        sys.exit(1)

    vm = client.get_vm(site_id, vm_id)
    if args.json:
        print(json.dumps(vm, indent=2))
    else:
        if isinstance(vm, dict):
            name = vm.get("name", "N/A")
            vm_id = vm.get("id") or vm.get("vm_id") or vm.get("urn", "N/A")
            status = vm.get("status", "N/A")
            print(f"  - {name} ({vm_id}): {status}")


def main():
    parser = argparse.ArgumentParser(description="List sites, VMs, or IP allocations")
    add_common_args(parser)

    subparsers = parser.add_subparsers(dest="resource", help="Resource to list")

    vms_parser = subparsers.add_parser("vms", help="List VMs")
    vms_parser.add_argument("--json", action="store_true", help="Output as JSON")

    vm_parser = subparsers.add_parser("vm", help="List VM BY Id")
    vm_parser.add_argument("--vm-id", "-v", help="VM ID")
    vm_parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if not args.resource:
        parser.print_help()
        sys.exit(1)

    client, cfg = get_client_with_args(args)

    client.login()

    if args.resource == "vms":
        list_vms(client, cfg, args)
    elif args.resource == "vm":
        get_vm(client, cfg, args)


if __name__ == "__main__":
    main()