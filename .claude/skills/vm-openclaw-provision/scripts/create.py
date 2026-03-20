#!/usr/bin/env python3
"""Create VM(s) from template."""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import (
    add_common_args,
    create_ssh_client,
    generate_vm_config_yaml,
    get_available_ip,
    get_client_with_args,
    transfer_config_via_scp,
    wait_for_ssh_ready,
)


def print_config_warning(ips):
    """Print warning about required config transfer."""
    print("\n" + "=" * 60)
    print("⚠️  WARNING: Config transfer is REQUIRED for VM to work!")
    print("=" * 60)
    print("\nThe newly created VM(s) will NOT be able to connect to the")
    print("environment without configuration transfer.")
    print("\nRequired config includes:")
    print("  - VM IP address")
    print("  - Environment server IP")
    print("  - Kafka credentials")
    print(f"\nVM IP(s) needing config: {', '.join(ips)}")
    print("\nTo transfer config, run:")
    for ip in ips:
        print(f"  python scripts/transfer_config.py --ip {ip}")
    print("\nOr use --transfer-config flag when creating VMs:")
    print("  python scripts/create.py --name <vm-name> --wait --transfer-config")
    print("=" * 60 + "\n")


def create_single_vm(client, cfg, args):
    site_id = args.site_id or cfg.site_id
    vm_id = args.vm_id or cfg.vm_id
    gateway = args.gateway or cfg.gateway
    netmask = args.netmask or cfg.netmask
    cpu = args.cpu or cfg.cpu
    memory = args.memory or cfg.memory

    if not all([site_id, vm_id, gateway, netmask]):
        print("Error: Missing required parameters (site-id, vm-id, gateway, netmask)")
        sys.exit(1)

    ip = args.ip
    if not ip and client.ip_manager:
        ip = get_available_ip(client.ip_manager, gateway, netmask)
        if not ip:
            print(f"Error: No available IP in subnet {gateway}/{netmask}")
            sys.exit(1)

    print(f"Creating VM '{args.name}' with IP {ip}...")

    try:
        task_id, vm_id_created = client.clone_vm(
            site_id=site_id,
            vm_id=vm_id,
            name=args.name,
            cpu=cpu,
            memory=memory,
            ip=ip,
            gateway=gateway,
            netmask=netmask,
            hostname=args.hostname or args.name,
            description=args.description or "",
        )

        if client.ip_manager:
            client.ip_manager.allocate_ip(ip, task_id, site_id, vm_id_created, args.name, gateway, netmask)

        print(f"VM creation started, task_id: {task_id}")

        if args.wait:
            print(f"Waiting for task to complete (timeout: {client.timeout}s)...")
            client.wait_for_task(site_id, task_id)

            if client.ip_manager:
                client.ip_manager.mark_allocated(ip)

            print(f"VM created successfully!")
            print(f"  Name: {args.name}")
            print(f"  IP: {ip}")
            print(f"  VM ID: {vm_id_created}")

            if args.transfer_config:
                transfer_config(client, cfg, ip)

        result = {"success": True, "name": args.name, "ip": ip, "task_id": task_id}
        if args.json:
            print(json.dumps(result, indent=2))

    except Exception as e:
        print(f"Error: {e}")
        if client.ip_manager and ip:
            client.ip_manager.mark_failed(ip)
        sys.exit(1)


def create_batch_vms(client, cfg, args):
    site_id = args.site_id or cfg.site_id
    vm_id = args.vm_id or cfg.vm_id
    gateway = args.gateway or cfg.gateway
    netmask = args.netmask or cfg.netmask
    cpu = args.cpu or cfg.cpu
    memory = args.memory or cfg.memory

    if not all([site_id, vm_id, gateway, netmask]):
        print("Error: Missing required parameters (site-id, vm-id, gateway, netmask)")
        sys.exit(1)

    names = args.names.split(",")
    results = []
    allocated_ips = []

    for name in names:
        name = name.strip()
        if not name:
            continue

        ip = None
        try:
            if client.ip_manager:
                ip = get_available_ip(client.ip_manager, gateway, netmask, exclude_ips=allocated_ips)

            if not ip:
                print(f"Error: No available IP for VM '{name}'")
                results.append({"name": name, "success": False, "error": "No available IP"})
                continue

            allocated_ips.append(ip)
            print(f"Creating VM '{name}' with IP {ip}...")

            task_id, vm_id_created = client.clone_vm(
                site_id=site_id,
                vm_id=vm_id,
                name=name,
                cpu=cpu,
                memory=memory,
                ip=ip,
                gateway=gateway,
                netmask=netmask,
                hostname=name,
            )

            if client.ip_manager:
                client.ip_manager.allocate_ip(ip, task_id, site_id, vm_id_created, name, gateway, netmask)

            results.append({"name": name, "success": True, "ip": ip, "task_id": task_id})

        except Exception as e:
            print(f"Error creating VM '{name}': {e}")
            results.append({"name": name, "success": False, "error": str(e)})
            if client.ip_manager and ip:
                client.ip_manager.mark_failed(ip)

    if args.wait:
        print("\nWaiting for all tasks to complete...")
        for r in results:
            if r.get("success") and r.get("task_id"):
                try:
                    client.wait_for_task(site_id, r["task_id"])

                    if client.ip_manager:
                        client.ip_manager.mark_allocated(r["ip"])

                    r["task_completed"] = True
                    print(f"  ✓ {r['name']}: completed")

                except Exception as e:
                    r["task_completed"] = False
                    r["error"] = str(e)
                    print(f"  ✗ {r['name']}: {e}")

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print("\nSummary:")
        for r in results:
            status = "✓" if r.get("success") else "✗"
            print(f"  {status} {r['name']}: {r.get('ip', 'no IP')} {'(completed)' if r.get('task_completed') else ''}")


def transfer_config(client, cfg, vm_ip, include_vm=True, include_kafka=True, include_ssh=True):
    if not cfg.config_transfer.get("enabled"):
        print("Config transfer disabled in config")
        return

    ssh_config = cfg.ssh_config
    if not ssh_config:
        print("No SSH config found")
        return

    ssh_username = ssh_config.get("username", "root")
    ssh_password = ssh_config.get("password", "")
    ssh_port = ssh_config.get("port", 22)
    remote_path = cfg.config_transfer.get("remote_path", "/opt/nexent/config")
    config_filename = cfg.config_transfer.get("config_filename", "agent_config.yaml")

    print(f"Waiting for SSH on {vm_ip}:{ssh_port}...")
    wait_for_ssh_ready(vm_ip, ssh_port, timeout=ssh_config.get("ready_timeout", 300))

    print(f"Connecting to {vm_ip}...")
    ssh_client = create_ssh_client(vm_ip, ssh_username, ssh_password, ssh_port)

    try:
        config_content = generate_vm_config_yaml(vm_ip, cfg.kafka_config if include_kafka else {}, cfg.ssh_config if include_ssh else {})
        full_path = f"{remote_path}/{config_filename}"

        print(f"Transferring config to {full_path}...")
        transfer_config_via_scp(ssh_client, config_content, full_path)
        print(f"Config transferred to {full_path}")
    finally:
        ssh_client.close()


def main():
    parser = argparse.ArgumentParser(description="Create VM(s) from template")
    add_common_args(parser)

    parser.add_argument("--name", "-n", help="VM name (for single VM)")
    parser.add_argument("--names", help="Comma-separated VM names (for batch creation)")
    parser.add_argument("--vm-id", help="Template VM ID")
    parser.add_argument("--ip", help="Specific IP address (auto-assigned if not specified)")
    parser.add_argument("--gateway", help="Gateway IP")
    parser.add_argument("--netmask", help="Subnet mask")
    parser.add_argument("--cpu", type=int, help="CPU cores")
    parser.add_argument("--memory", type=int, help="Memory in MB")
    parser.add_argument("--hostname", help="Hostname (defaults to VM name)")
    parser.add_argument("--description", "-d", help="VM description")
    parser.add_argument("--wait", "-w", action="store_true", help="Wait for task completion")
    parser.add_argument("--transfer-config", action="store_true", help="Transfer config after creation (includes all sections)")
    parser.add_argument("--skip-config-warning", action="store_true", help="Skip config transfer warning")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if not args.name and not args.names:
        print("Error: Either --name or --names is required")
        parser.print_help()
        sys.exit(1)

    client, cfg = get_client_with_args(args)
    client.login()

    if args.names:
        create_batch_vms(client, cfg, args)
    else:
        create_single_vm(client, cfg, args)


if __name__ == "__main__":
    main()
