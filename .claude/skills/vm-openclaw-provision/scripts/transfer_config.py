#!/usr/bin/env python3
"""Transfer Kafka and model config to VM via SSH."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import (
    add_common_args,
    create_ssh_client,
    fetch_nexent_model_config,
    generate_vm_config_yaml,
    get_client_with_args,
    sync_model_config_to_vm,
    transfer_config_via_scp,
    wait_for_ssh_ready,
)


def main():
    parser = argparse.ArgumentParser(
        description="Transfer Kafka and model config to VM via SSH"
    )
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
        "--include-kafka",
        action="store_true",
        default=True,
        help="Include Kafka config in transfer (default: True)",
    )
    parser.add_argument(
        "--no-include-kafka",
        action="store_false",
        dest="include_kafka",
        help="Exclude Kafka config from transfer",
    )
    parser.add_argument(
        "--include-model",
        action="store_true",
        default=True,
        help="Sync model config from Nexent to VM's openclaw.json (default: True)",
    )
    parser.add_argument(
        "--no-include-model",
        action="store_false",
        dest="include_model",
        help="Skip model config sync",
    )
    parser.add_argument(
        "--openclaw-config-path",
        default="/root/.openclaw/openclaw.json",
        help="Path to openclaw.json on VM",
    )
    parser.add_argument(
        "--nexent-api-url",
        help="Nexent API URL (overrides config)",
    )
    parser.add_argument(
        "--nexent-api-token",
        help="Nexent API token (overrides config)",
    )
    parser.add_argument(
        "--model-types",
        nargs="+",
        default=["llm"],
        help="Model types to sync (e.g., llm embedding)",
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

    try:
        print(f"Waiting for SSH on {args.ip}:{args.ssh_port}...")
        wait_for_ssh_ready(args.ip, args.ssh_port, timeout=args.timeout)
        print("SSH is ready")

        print(f"Connecting to {args.ip}...")
        ssh_client = create_ssh_client(
            args.ip, args.ssh_username, ssh_password, args.ssh_port
        )

        try:
            if kafka_config:
                config_content = generate_vm_config_yaml(
                    args.ip, kafka_config, {}, include_vm=False, include_ssh=False
                )
                full_path = f"{args.remote_path}/{args.filename}"

                print(f"Transferring Kafka config to {full_path}...")
                transfer_config_via_scp(ssh_client, config_content, full_path)
                print("Kafka config transferred successfully!")

            model_sync_result = None
            if args.include_model:
                nexent_api_config = cfg.nexent_api
                nexent_url = args.nexent_api_url or nexent_api_config.get("base_url")
                nexent_token = args.nexent_api_token or nexent_api_config.get("token")

                if not nexent_url:
                    print("Warning: Nexent API URL not configured, skipping model sync")
                else:
                    print(f"Fetching model config from {nexent_url}...")
                    try:
                        models = fetch_nexent_model_config(
                            base_url=nexent_url,
                            token=nexent_token,
                            model_types=args.model_types,
                        )
                        print(f"Found {len(models)} model(s) to sync")

                        if models:
                            openclaw_path = args.openclaw_config_path
                            print(f"Syncing model config to {openclaw_path}...")
                            model_sync_result = sync_model_config_to_vm(
                                ssh_client,
                                models,
                                openclaw_path,
                                vm_ip=args.ip,
                                merge=True,
                            )
                            print("Model config synced successfully!")
                            print(
                                f"Set gateway.controlUi.allowedOrigins = http://{args.ip}:18789"
                            )
                    except Exception as e:
                        print(f"Warning: Failed to sync model config: {e}")

            if args.json:
                result = {
                    "success": True,
                    "ip": args.ip,
                }
                if kafka_config:
                    result["kafka_config_path"] = f"{args.remote_path}/{args.filename}"
                if model_sync_result:
                    result["model_sync"] = {
                        "openclaw_path": args.openclaw_config_path,
                        "providers": list(
                            model_sync_result.get("models", {})
                            .get("providers", {})
                            .keys()
                        ),
                        "allowed_origins": f"http://{args.ip}:18789",
                    }
                print(json.dumps(result, indent=2))

        finally:
            ssh_client.close()

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
