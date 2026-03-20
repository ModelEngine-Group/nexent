#!/usr/bin/env python3
"""Transfer config to VM via SSH/SCP."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import (
    add_common_args,
    create_ssh_client,
    generate_vm_config_yaml,
    get_client_with_args,
    transfer_config_via_scp,
    wait_for_ssh_ready,
)


def main():
    parser = argparse.ArgumentParser(description="Transfer config to VM via SSH/SCP")
    add_common_args(parser)

    parser.add_argument("--ip", required=True, help="VM IP address")
    parser.add_argument("--ssh-username", default="root", help="SSH username")
    parser.add_argument("--ssh-password", help="SSH password")
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH port")
    parser.add_argument(
        "--remote-path",
        default="/opt/nexent/config",
    )
    parser.add_argument(
        "--filename", default="agent_config.yaml", help="Config filename"
    )
    parser.add_argument(
        "--timeout", type=int, default=300, help="SSH ready timeout (seconds)"
    )
    parser.add_argument(
        "--include-vm",
        action="store_true",
        default=True,
        help="Include VM config in transfer",
    )
    parser.add_argument(
        "--no-include-vm",
        action="store_false",
        dest="include_vm",
        help="Exclude VM config from transfer",
    )
    parser.add_argument(
        "--include-kafka",
        action="store_true",
        default=True,
        help="Include Kafka config in transfer",
    )
    parser.add_argument(
        "--no-include-kafka",
        action="store_false",
        dest="include_kafka",
        help="Exclude Kafka config from transfer",
    )
    parser.add_argument(
        "--include-ssh",
        action="store_true",
        default=True,
        help="Include SSH config in transfer",
    )
    parser.add_argument(
        "--no-include-ssh",
        action="store_false",
        dest="include_ssh",
        help="Exclude SSH config from transfer",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    client, cfg = get_client_with_args(args)

    ssh_password = args.ssh_password or cfg.ssh_config.get("password")
    if not ssh_password:
        print(
            "Error: SSH password is required (use --ssh-password or configure in config file)"
        )
        sys.exit(1)

    kafka_config = cfg.kafka_config if args.include_kafka else {}
    ssh_config = cfg.ssh_config if args.include_ssh else {}

    try:
        print(f"Waiting for SSH on {args.ip}:{args.ssh_port}...")
        wait_for_ssh_ready(args.ip, args.ssh_port, timeout=args.timeout)
        print("SSH is ready")

        print(f"Connecting to {args.ip}...")
        ssh_client = create_ssh_client(
            args.ip, args.ssh_username, ssh_password, args.ssh_port
        )

        try:
            config_content = generate_vm_config_yaml(
                args.ip,
                kafka_config,
                ssh_config,
                include_vm=args.include_vm,
                include_ssh=args.include_ssh,
            )
            full_path = f"{args.remote_path}/{args.filename}"

            print(f"Transferring config to {full_path}...")
            transfer_config_via_scp(ssh_client, config_content, full_path)
            print(f"Config transferred successfully!")

            if args.json:
                result = {"success": True, "ip": args.ip, "remote_path": full_path}
                print(json.dumps(result, indent=2))

        finally:
            ssh_client.close()

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
