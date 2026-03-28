#!/usr/bin/env python3
"""Transfer Kafka and model config to VM via SSH."""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import (
    add_common_args,
    create_ssh_client,
    fetch_models_from_db,
    generate_vm_config_yaml,
    get_client_with_args,
    setup_crontab,
    sync_model_config_to_vm,
    transfer_config_via_scp,
    transfer_file_via_sftp,
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
        user_id = cfg.user_id
        description = cfg.vm_description

        if kafka_config or user_id or description:
            config_content = generate_vm_config_yaml(
                vm_ip,
                kafka_config,
                {},
                include_vm=False,
                include_ssh=False,
                user_id=user_id,
                description=description,
            )
            full_path = f"{remote_path}/{config_filename}"

            print(f"Transferring config to {full_path}...")
            if user_id:
                print(f"  user_id: {user_id}")
            if description:
                print(f"  description: {description}")
            transfer_config_via_scp(ssh_client, config_content, full_path)
            print("Config transferred successfully!")

        local_report_script = os.path.join(os.path.dirname(__file__), "report_info.py")
        remote_report_path = "/opt/nexent/report_info.py"
        cron_entry = (
            f"* * * * * /usr/bin/python3 {remote_report_path} "
            f">> /var/log/kafka_status.log 2>&1"
        )

        if os.path.exists(local_report_script):
            print(f"Transferring report_info.py to {remote_report_path}...")
            transfer_file_via_sftp(ssh_client, local_report_script, remote_report_path)
            print("report_info.py transferred successfully!")

            print("Setting up crontab for report_info.py...")
            setup_crontab(ssh_client, remote_report_path, cron_entry)
            print("Crontab entry added successfully!")
        else:
            print(
                f"Warning: report_info.py not found at {local_report_script}, skipping"
            )

        postgres_config = cfg.postgres_config
        pg_host = postgres_config.get("host", "nexent-postgresql")
        pg_port = postgres_config.get("port", 5432)
        pg_user = postgres_config.get("user", "root")
        pg_password = postgres_config.get("password") or os.getenv(
            "NEXENT_POSTGRES_PASSWORD", ""
        )
        pg_database = postgres_config.get("database", "nexent")

        model_sync_config = cfg.model_sync
        openclaw_path = model_sync_config.get(
            "openclaw_config_path", "/root/.openclaw/openclaw.json"
        )
        model_types = model_sync_config.get("model_types", ["llm"])

        models = []
        if not pg_password:
            print("Warning: Postgres password not configured, skipping model sync")
        else:
            print(f"Fetching model config from database {pg_host}:{pg_port}...")
            try:
                models = fetch_models_from_db(
                    host=pg_host,
                    password=pg_password,
                    model_types=model_types,
                    database=pg_database,
                    user=pg_user,
                    port=pg_port,
                )
                print(f"Found {len(models)} model(s) to sync")
            except Exception as e:
                print(f"Warning: Failed to fetch model config: {e}")

        try:
            if models:
                print(f"Syncing model config to {openclaw_path}...")
            else:
                print(f"Updating gateway config to {openclaw_path}...")
            sync_model_config_to_vm(
                ssh_client,
                models,
                openclaw_path,
                vm_ip=vm_ip,
                merge=True,
            )
            if models:
                print("Model config synced successfully!")
            print(f"Set gateway.controlUi.allowedOrigins = http://{vm_ip}:18789")
        except Exception as e:
            print(f"Warning: Failed to sync config to VM: {e}")

    finally:
        ssh_client.close()


def main():
    parser = argparse.ArgumentParser(
        description="Transfer Kafka and model config to VM via SSH"
    )
    add_common_args(parser)

    parser.add_argument("--ip", required=True, help="VM IP address")
    parser.add_argument("--user-id", required=True, help="User ID to include in config")
    parser.add_argument("--description", "-d", help="Description to include in config")
    parser.add_argument("--ssh-username", help="SSH username (overrides config)")
    parser.add_argument("--ssh-password", help="SSH password (overrides config)")
    parser.add_argument("--ssh-port", type=int, help="SSH port (overrides config)")
    parser.add_argument(
        "--no-include-kafka", action="store_true", help="Skip Kafka config"
    )
    parser.add_argument(
        "--no-include-model", action="store_true", help="Skip model config sync"
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

    if args.user_id:
        cfg.set("user_id", args.user_id)
    if args.description:
        cfg.set("vm_description", args.description)
    if args.ssh_username:
        cfg.set_nested("ssh", "username", value=args.ssh_username)
    if args.ssh_password:
        cfg.set_nested("ssh", "password", value=args.ssh_password)
    if args.ssh_port:
        cfg.set_nested("ssh", "port", value=args.ssh_port)
    if args.no_include_kafka:
        cfg.set("kafka", {})
    if args.model_types:
        cfg.set_nested("model_sync", "model_types", value=args.model_types)
    if args.openclaw_config_path:
        cfg.set_nested(
            "model_sync",
            "openclaw_config_path",
            value=args.openclaw_config_path,
        )
    if args.no_include_model:
        cfg.set("model_sync", {})

    run_transfer(args.ip, cfg)


if __name__ == "__main__":
    main()
