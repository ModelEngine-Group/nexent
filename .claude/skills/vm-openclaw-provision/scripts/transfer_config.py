#!/usr/bin/env python3
"""Transfer Kafka and model config to VM via SSH."""

import argparse
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
    Config,
)


def run_transfer(vm_ip, cfg: Config):
    ssh_config = cfg.ssh_config
    ssh_password = ssh_config.get("password", "")
    if not ssh_password:
        print("Error: SSH password not configured")
        return

    ssh_username = ssh_config.get("username", "root")
    ssh_port = ssh_config.get("port", 22)
    timeout = ssh_config.get("ready_timeout", 300)
    kafka_config = cfg.kafka_config
    nexent_api_config = cfg.nexent_api
    config_transfer = cfg.config_transfer
    remote_path = config_transfer.get("remote_path", "/opt/nexent/config")
    config_filename = config_transfer.get("config_filename", "agent_config.yaml")

    print(f"Waiting for SSH on {vm_ip}:{ssh_port}...")
    wait_for_ssh_ready(vm_ip, ssh_port, timeout=timeout)
    print("SSH is ready")

    print(f"Connecting to {vm_ip}...")
    ssh_client = create_ssh_client(vm_ip, ssh_username, ssh_password, ssh_port)

    try:
        kafka_config = cfg.kafka_config
        user_name = cfg.user_name

        if kafka_config or user_name:
            config_content = generate_vm_config_yaml(
                vm_ip,
                kafka_config,
                {},
                include_vm=False,
                include_ssh=False,
                user_name=user_name,
            )
            full_path = f"{remote_path}/{config_filename}"

            print(f"Transferring config to {full_path}...")
            if user_name:
                print(f"  user_name: {user_name}")
            transfer_config_via_scp(ssh_client, config_content, full_path)
            print("Config transferred successfully!")

        nexent_url = nexent_api_config.get("base_url")
        nexent_token = nexent_api_config.get("token")
        model_sync_config = nexent_api_config.get("model_sync", {})
        openclaw_path = model_sync_config.get(
            "openclaw_config_path", "/root/.openclaw/openclaw.json"
        )
        model_types = model_sync_config.get("model_types", ["llm"])

        if not nexent_url:
            print("Warning: Nexent API URL not configured, skipping model sync")
        else:
            print(f"Fetching model config from {nexent_url}...")
            try:
                models = fetch_nexent_model_config(
                    base_url=nexent_url,
                    token=nexent_token,
                    model_types=model_types,
                )
                print(f"Found {len(models)} model(s) to sync")

                if models:
                    print(f"Syncing model config to {openclaw_path}...")
                    sync_model_config_to_vm(
                        ssh_client,
                        models,
                        openclaw_path,
                        vm_ip=vm_ip,
                        merge=True,
                    )
                    print("Model config synced successfully!")
                    print(
                        f"Set gateway.controlUi.allowedOrigins = http://{vm_ip}:18789"
                    )
            except Exception as e:
                print(f"Warning: Failed to sync model config: {e}")

    finally:
        ssh_client.close()


def main():
    parser = argparse.ArgumentParser(
        description="Transfer Kafka and model config to VM via SSH"
    )
    add_common_args(parser)

    parser.add_argument("--ip", required=True, help="VM IP address")
    parser.add_argument("--user-name", help="User name to include in config")
    parser.add_argument("--ssh-username", help="SSH username (overrides config)")
    parser.add_argument("--ssh-password", help="SSH password (overrides config)")
    parser.add_argument("--ssh-port", type=int, help="SSH port (overrides config)")
    parser.add_argument(
        "--no-include-kafka", action="store_true", help="Skip Kafka config"
    )
    parser.add_argument(
        "--no-include-model", action="store_true", help="Skip model config sync"
    )
    parser.add_argument("--nexent-api-url", help="Nexent API URL (overrides config)")
    parser.add_argument(
        "--nexent-api-token", help="Nexent API token (overrides config)"
    )
    parser.add_argument(
        "--model-types", nargs="+", help="Model types to sync (overrides config)"
    )
    parser.add_argument(
        "--openclaw-config-path", help="Path to openclaw.json on VM (overrides config)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    _, cfg = get_client_with_args(args)

    if args.user_name:
        cfg.set("user_name", args.user_name)
    if args.ssh_username:
        cfg.set_nested("ssh", "username", value=args.ssh_username)
    if args.ssh_password:
        cfg.set_nested("ssh", "password", value=args.ssh_password)
    if args.ssh_port:
        cfg.set_nested("ssh", "port", value=args.ssh_port)
    if args.no_include_kafka:
        cfg.set("kafka", {})
    if args.nexent_api_url:
        cfg.set_nested("nexent_api", "base_url", value=args.nexent_api_url)
    if args.nexent_api_token:
        cfg.set_nested("nexent_api", "token", value=args.nexent_api_token)
    if args.model_types:
        cfg.set_nested(
            "nexent_api", "model_sync", "model_types", value=args.model_types
        )
    if args.openclaw_config_path:
        cfg.set_nested(
            "nexent_api",
            "model_sync",
            "openclaw_config_path",
            value=args.openclaw_config_path,
        )
    if args.no_include_model:
        cfg.set("nexent_api", {})

    run_transfer(args.ip, cfg)


if __name__ == "__main__":
    main()
