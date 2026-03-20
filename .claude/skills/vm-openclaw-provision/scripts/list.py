#!/usr/bin/env python3
"""List sites, VMs, or IP allocations."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import add_common_args, get_client_with_args


def list_sites(client, args):
    sites = client.get_sites()
    if args.json:
        print(json.dumps(sites, indent=2))
    else:
        print(f"Found {len(sites)} site(s):")
        for site in sites:
            if isinstance(site, dict):
                print(f"  - {site.get('name', 'N/A')}: {site.get('id', site.get('urn', 'N/A'))}")
            else:
                print(f"  - {site}")


def list_vms(client, cfg, args):
    site_id = args.site_id or cfg.site_id
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


def list_ips(client, cfg, args):
    if not client.ip_manager:
        print("Error: IP manager not configured")
        sys.exit(1)

    gateway = args.gateway or cfg.gateway
    netmask = args.netmask or cfg.netmask

    if args.status:
        allocations = client.ip_manager.list_allocations(status=args.status)
    else:
        allocations = client.ip_manager.list_allocations()

    if args.json:
        print(json.dumps(allocations, indent=2))
    else:
        print(f"Found {len(allocations)} IP allocation(s):")
        for a in allocations:
            ip = a.get("ip", "N/A")
            status = a.get("status", "N/A")
            name = a.get("name", "N/A")
            vm_id = a.get("vm_id", "N/A")
            print(f"  - {ip}: {status} (name={name}, vm_id={vm_id})")


def main():
    parser = argparse.ArgumentParser(description="List sites, VMs, or IP allocations")
    add_common_args(parser)

    subparsers = parser.add_subparsers(dest="resource", help="Resource to list")

    sites_parser = subparsers.add_parser("sites", help="List sites")
    sites_parser.add_argument("--json", action="store_true", help="Output as JSON")

    vms_parser = subparsers.add_parser("vms", help="List VMs")
    vms_parser.add_argument("--json", action="store_true", help="Output as JSON")

    ips_parser = subparsers.add_parser("ips", help="List IP allocations")
    ips_parser.add_argument("--status", choices=["allocating", "allocated", "failed", "released"], help="Filter by status")
    ips_parser.add_argument("--gateway", help="Filter by gateway")
    ips_parser.add_argument("--netmask", help="Filter by netmask")
    ips_parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if not args.resource:
        parser.print_help()
        sys.exit(1)

    client, cfg = get_client_with_args(args)

    if args.resource != "ips":
        client.login()

    if args.resource == "sites":
        list_sites(client, args)
    elif args.resource == "vms":
        list_vms(client, cfg, args)
    elif args.resource == "ips":
        list_ips(client, cfg, args)


if __name__ == "__main__":
    main()