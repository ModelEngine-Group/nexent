#!/usr/bin/env python3
"""Shared code for VM provisioning scripts."""

import argparse
import csv
import ipaddress
import json
import os
import socket
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import paramiko
import psycopg2
import requests
import yaml

CSV_COLUMNS = [
    "ip",
    "status",
    "task_id",
    "vm_id",
    "site_id",
    "name",
    "gateway",
    "netmask",
    "created_at",
    "updated_at",
]
ALLOCATING_TIMEOUT_MINUTES = 15


class IPAllocationManager:
    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self._ensure_file()

    def _ensure_file(self) -> None:
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()

    def _read_all(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.csv_path):
            return []
        with open(self.csv_path, "r", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)

    def _write_all(self, records: List[Dict[str, Any]]) -> None:
        with open(self.csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(records)

    def _append(self, record: Dict[str, Any]) -> None:
        with open(self.csv_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writerow(record)

    def _ip_in_subnet(self, ip: str, gateway: str, netmask: str) -> bool:
        try:
            network = ipaddress.IPv4Network(f"{gateway}/{netmask}", strict=False)
            return ipaddress.IPv4Address(ip) in network
        except ValueError:
            return False

    def get_allocated_ips(self, gateway: str, netmask: str) -> set:
        records = self._read_all()
        allocated: set = set()
        for r in records:
            if not self._ip_in_subnet(r["ip"], gateway, netmask):
                continue
            status = r.get("status", "")
            if status in ("allocated", "allocating"):
                allocated.add(r["ip"])
        return allocated

    def allocate_ip(
        self,
        ip: str,
        task_id: str,
        site_id: str,
        vm_id: str,
        name: str,
        gateway: str,
        netmask: str,
    ) -> None:
        now = datetime.now().isoformat()
        record = {
            "ip": ip,
            "status": "allocating",
            "task_id": task_id,
            "vm_id": vm_id,
            "site_id": site_id,
            "name": name,
            "gateway": gateway,
            "netmask": netmask,
            "created_at": now,
            "updated_at": now,
        }
        self._append(record)

    def mark_allocated(self, ip: str) -> None:
        records = self._read_all()
        for r in records:
            if r["ip"] == ip and r["status"] == "allocating":
                r["status"] = "allocated"
                r["updated_at"] = datetime.now().isoformat()
                break
        self._write_all(records)

    def mark_failed(self, ip: str) -> None:
        records = self._read_all()
        for r in records:
            if r["ip"] == ip and r["status"] == "allocating":
                r["status"] = "failed"
                r["updated_at"] = datetime.now().isoformat()
                break
        self._write_all(records)

    def get_allocation(self, ip: str) -> Optional[Dict[str, Any]]:
        records = self._read_all()
        for r in records:
            if r["ip"] == ip:
                return r
        return None

    def list_allocations(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        records = self._read_all()
        if status:
            return [r for r in records if r.get("status") == status]
        return records

    def cleanup_stale(self) -> int:
        records = self._read_all()
        now = datetime.now()
        cleaned = 0
        for r in records:
            if r["status"] == "allocating":
                created = datetime.fromisoformat(r["created_at"])
                if now - created > timedelta(minutes=ALLOCATING_TIMEOUT_MINUTES):
                    r["status"] = "failed"
                    r["updated_at"] = now.isoformat()
                    cleaned += 1
        self._write_all(records)
        return cleaned

    def release_ip(self, ip: str) -> bool:
        records = self._read_all()
        found = False
        for r in records:
            if r["ip"] == ip and r["status"] in ("allocated", "allocating"):
                r["status"] = "released"
                r["updated_at"] = datetime.now().isoformat()
                found = True
                break
        if found:
            self._write_all(records)
        return found


def calculate_ip_range_from_subnet(gateway: str, netmask: str) -> Tuple[str, str]:
    network = ipaddress.IPv4Network(f"{gateway}/{netmask}", strict=False)
    hosts = list(network.hosts())
    if not hosts:
        raise ValueError(f"No usable IPs in network {network}")
    return (str(hosts[0]), str(hosts[-1]))


def get_available_ip(
    ip_manager: IPAllocationManager,
    gateway: str,
    netmask: str,
    exclude_ips: Optional[List[str]] = None,
) -> Optional[str]:
    allocated = ip_manager.get_allocated_ips(gateway, netmask)
    exclude: set = {gateway}
    exclude.update(allocated)
    if exclude_ips:
        exclude.update(exclude_ips)
    first_ip, last_ip = calculate_ip_range_from_subnet(gateway, netmask)
    start = ipaddress.IPv4Address(first_ip)
    end = ipaddress.IPv4Address(last_ip)
    for ip_int in range(int(start), int(end) + 1):
        ip = str(ipaddress.IPv4Address(ip_int))
        if ip not in exclude:
            return ip
    return None


def extract_id_from_urn(task_urn: str) -> str:
    if not task_urn:
        return ""
    parts = task_urn.split(":")
    return parts[-1] if parts else ""


def load_config(config_path: str | None = None) -> dict:
    primary_config = "/mnt/nexent/vm-config.yaml"
    fallback_config = os.path.join(
        os.path.dirname(__file__), "..", "config", "config.yaml"
    )

    if config_path and os.path.exists(config_path):
        with open(config_path, "r") as f:
            return yaml.safe_load(f) or {}

    if os.path.exists(primary_config):
        with open(primary_config, "r") as f:
            return yaml.safe_load(f) or {}

    if os.path.exists(fallback_config):
        with open(fallback_config, "r") as f:
            return yaml.safe_load(f) or {}

    return {}


class Config:
    def __init__(self, config_dict: dict):
        self._raw = config_dict

    def _get(self, *keys, default=None):
        for key in keys:
            if key in self._raw:
                return self._raw[key]
        return default

    def set(self, key: str, value) -> None:
        self._raw[key] = value

    def set_nested(self, *keys, value) -> None:
        d = self._raw
        for k in keys[:-1]:
            if k not in d or not isinstance(d[k], dict):
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value

    @property
    def fc_ip(self) -> str:
        return self._get("fc_ip", "FC_IP") or ""

    @property
    def username(self) -> str:
        return (
            self._get("X-Auth-User", "x_auth_user", "username", default="admin")
            or "admin"
        )

    @property
    def password(self) -> str:
        return self._get("X-Auth-Key", "x_auth_key", "password", default="") or ""

    @property
    def site_id(self) -> Optional[str]:
        return self._get("site_id", "SITE_ID")

    @property
    def vm_id(self) -> Optional[str]:
        return self._get("vm_id", "VM_ID")

    @property
    def cpu(self) -> int:
        val = self._get("cpu", "CPU", default=4)
        return val if isinstance(val, int) else 4

    @property
    def memory(self) -> int:
        val = self._get("memory", "MEMORY", default=8192)
        return val if isinstance(val, int) else 8192

    @property
    def gateway(self) -> Optional[str]:
        return self._get("gateway", "GATEWAY")

    @property
    def netmask(self) -> Optional[str]:
        return self._get("netmask", "NETMASK") or "255.255.255.0"

    @property
    def task_timeout(self) -> int:
        val = self._get("task_timeout", "TASK_TIMEOUT", default=600)
        return val if isinstance(val, int) else 600

    @property
    def ssh_config(self) -> Dict[str, Any]:
        return self._get("ssh", default={})

    @property
    def kafka_config(self) -> Dict[str, Any]:
        return self._get("kafka", default={})

    @property
    def config_transfer(self) -> Dict[str, Any]:
        return self._get("config_transfer", default={})

    @property
    def model_sync(self) -> Dict[str, Any]:
        return self._get("model_sync", default={})

    @property
    def postgres_config(self) -> Dict[str, Any]:
        return self._get("postgres", default={})

    @property
    def user_id(self) -> Optional[str]:
        return self._get("user_id")

    @property
    def vm_description(self) -> Optional[str]:
        return self._get("vm_description")


def get_csv_path(config_path: str | None = None) -> Path:
    primary_config_path = "/mnt/nexent/vm-config.yaml"
    fallback_config_path = os.path.join(
        os.path.dirname(__file__), "..", "config", "config.yaml"
    )

    if config_path and os.path.exists(config_path):
        return Path(config_path).parent / ".ip_allocations.csv"
    elif os.path.exists(primary_config_path):
        return Path(primary_config_path).parent / ".ip_allocations.csv"
    else:
        return Path(fallback_config_path).parent / ".ip_allocations.csv"


class FusionComputeClient:
    def __init__(
        self,
        fc_ip: str,
        username: str,
        password: str,
        timeout: int = 600,
        ip_manager: Optional[IPAllocationManager] = None,
        ssh_config: Optional[Dict[str, Any]] = None,
        kafka_config: Optional[Dict[str, Any]] = None,
        config_transfer: Optional[Dict[str, Any]] = None,
    ):
        self.fc_ip = fc_ip
        self.username = username
        self.password = password
        self.token: Optional[str] = None
        self.base_url = f"https://{fc_ip}:7443"
        self.timeout = timeout
        self.config: Optional[Config] = None
        self.ip_manager = ip_manager
        self.ssh_config = ssh_config
        self.kafka_config = kafka_config
        self.config_transfer = config_transfer

    def login(self) -> str:
        url = f"{self.base_url}/service/session"
        headers = {
            "Accept": "application/json;version=8.1;charset=UTF-8",
            "X-Auth-User": self.username,
            "X-Auth-Key": self.password,
            "X-Auth-UserType": "2",
            "X-ENCRYPT-ALGORITHM": "1",
        }
        response = requests.post(url, headers=headers, verify=False)
        response.raise_for_status()
        self.token = response.headers.get("X-Auth-Token")
        if not self.token:
            raise ValueError("Login failed: No token received")
        return self.token

    def _get_headers(self) -> Dict[str, str]:
        if not self.token:
            raise ValueError("Not logged in. Call login() first.")
        return {
            "Accept": "application/json;version=8.1;charset=UTF-8",
            "Content-Type": "application/json;charset=UTF-8",
            "X-Auth-Token": self.token,
        }

    def get_sites(self) -> list:
        url = f"{self.base_url}/service/sites"
        response = requests.get(url, headers=self._get_headers(), verify=False)
        response.raise_for_status()
        return response.json()

    def get_vms(self, site_id: str) -> list:
        url = f"{self.base_url}/service/sites/{site_id}/vms"
        response = requests.get(url, headers=self._get_headers(), verify=False)
        response.raise_for_status()
        return response.json()

    def get_vm(self, site_id: str, vm_id: str) -> dict:
        url = f"{self.base_url}/service/sites/{site_id}/vms/{vm_id}"
        response = requests.get(url, headers=self._get_headers(), verify=False)
        response.raise_for_status()
        return response.json()

    def get_task(self, site_id: str, task_id: str) -> dict:
        url = f"{self.base_url}/service/sites/{site_id}/tasks/{task_id}"
        response = requests.get(url, headers=self._get_headers(), verify=False)
        response.raise_for_status()
        return response.json()

    def wait_for_task(
        self, site_id: str, task_id: str, timeout: Optional[int] = None
    ) -> bool:
        if timeout is None:
            timeout = self.timeout
        start_time = time.time()
        delay = 1.0
        while time.time() - start_time < timeout:
            task = self.get_task(site_id, task_id)
            status = task.get("status", "").lower()
            if status in ("success", "complete", "completed"):
                return True
            if status in ("failed", "error"):
                error_msg = task.get("error", {}).get("message", "Unknown error")
                raise RuntimeError(f"Task failed: {error_msg}")
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
        raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")

    def clone_vm(
        self,
        site_id: str,
        vm_id: str,
        name: str,
        cpu: int = 4,
        memory: int = 8192,
        ip: str = "",
        gateway: str = "",
        netmask: str = "255.255.255.0",
        hostname: str = "",
        description: str = "",
        port_group: str = "",
    ) -> Tuple[str, str]:
        if ip and gateway and netmask and self.ip_manager:
            allocated = self.ip_manager.get_allocated_ips(gateway, netmask)
            if ip in allocated:
                raise ValueError(f"IP {ip} is already allocated or being allocated.")

        url = f"{self.base_url}/service/sites/{site_id}/vms/{vm_id}/action/clone"
        nic_config = {
            "ip": ip,
            "gateway": gateway,
            "netmask": netmask,
            "sequenceNum": 1,
            "ipVersion": 4,
        }
        if port_group:
            nic_config["portGroup"] = port_group

        body = {
            "name": name,
            "description": description,
            "vmConfig": {
                "cpu": {
                    "quantity": cpu,
                    "cpuHotPlug": 1,
                    "cpuThreadPolicy": "prefer",
                    "cpuPolicy": "shared",
                    "cpuBindType": "nobind",
                },
                "memory": {"quantityMB": memory, "memHotPlug": 1},
                "properties": {"recoverByHost": True},
            },
            "osOptions": {"osType": "Linux", "osVersion": 10088},
            "autoBoot": True,
            "isLinkClone": False,
            "vmCustomization": {
                "hostname": hostname or name,
                "osType": "Linux",
                "nicSpecification": [nic_config],
            },
            "customProperties": {},
        }

        response = requests.post(
            url, headers=self._get_headers(), json=body, verify=False
        )
        response.raise_for_status()
        task_urn = response.json().get("taskUrn", "")
        task_id = extract_id_from_urn(task_urn)
        vm_urn = response.json().get("urn", "")
        vm_id = extract_id_from_urn(vm_urn)
        return (task_id, vm_id)

    def start_vm(self, site_id: str, vm_id: str) -> str:
        url = f"{self.base_url}/service/sites/{site_id}/vms/{vm_id}/action/start"
        response = requests.post(url, headers=self._get_headers(), verify=False)
        response.raise_for_status()
        return extract_id_from_urn(response.json().get("taskUrn", ""))

    def stop_vm(self, site_id: str, vm_id: str) -> str:
        url = f"{self.base_url}/service/sites/{site_id}/vms/{vm_id}/action/stop"
        response = requests.post(url, headers=self._get_headers(), verify=False)
        response.raise_for_status()
        return extract_id_from_urn(response.json().get("taskUrn", ""))

    def hibernate_vm(self, site_id: str, vm_id: str) -> str:
        url = f"{self.base_url}/service/sites/{site_id}/vms/{vm_id}/action/hibernate"
        response = requests.post(url, headers=self._get_headers(), verify=False)
        response.raise_for_status()
        return extract_id_from_urn(response.json().get("taskUrn", ""))

    def delete_vm(self, site_id: str, vm_id: str) -> str:
        url = f"{self.base_url}/service/sites/{site_id}/vms/{vm_id}"
        response = requests.delete(url, headers=self._get_headers(), verify=False)
        response.raise_for_status()
        return extract_id_from_urn(response.json().get("taskUrn", ""))

    def modify_vm_cpu(self, site_id: str, vm_id: str, cpu: int) -> str:
        url = f"{self.base_url}/service/sites/{site_id}/vms/{vm_id}"
        body = {"cpu": {"quantity": cpu}}
        response = requests.put(
            url, headers=self._get_headers(), json=body, verify=False
        )
        response.raise_for_status()
        return extract_id_from_urn(response.json().get("taskUrn", ""))

    def modify_vm_memory(self, site_id: str, vm_id: str, memory_mb: int) -> str:
        url = f"{self.base_url}/service/sites/{site_id}/vms/{vm_id}"
        body = {"memory": {"quantityMB": memory_mb}}
        response = requests.put(
            url, headers=self._get_headers(), json=body, verify=False
        )
        response.raise_for_status()
        return extract_id_from_urn(response.json().get("taskUrn", ""))


def is_port_open(host: str, port: int, timeout: float = 5.0) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True
    except (socket.timeout, socket.error, OSError):
        return False
    finally:
        sock.close()


def wait_for_ssh_ready(host: str, port: int = 22, timeout: int = 300) -> bool:
    delay = 5.0
    start_time = time.time()
    while time.time() - start_time < timeout:
        if is_port_open(host, port, timeout=5):
            try:
                transport = paramiko.Transport((host, port))
                transport.banner_timeout = 5
                transport.connect()
                transport.close()
                return True
            except Exception:
                pass
        time.sleep(delay)
        delay = min(delay * 1.5, 30.0)
    raise TimeoutError(f"SSH not ready after {timeout}s")


def create_ssh_client(
    host: str, username: str, password: str, port: int = 22, timeout: int = 30
) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host, port=port, username=username, password=password, timeout=timeout
    )
    return client


def transfer_file_via_sftp(
    ssh_client: paramiko.SSHClient, local_path: str, remote_path: str
) -> bool:
    """Transfer a local file to remote host via SFTP."""
    remote_dir = os.path.dirname(remote_path)
    if remote_dir:
        ssh_client.exec_command(f"mkdir -p '{remote_dir}'")[
            1
        ].channel.recv_exit_status()

    sftp = ssh_client.open_sftp()
    try:
        sftp.put(local_path, remote_path)
        return True
    finally:
        sftp.close()


def setup_crontab(
    ssh_client: paramiko.SSHClient, script_path: str, cron_entry: str
) -> bool:
    """Add a crontab entry if it doesn't already exist. Idempotent."""
    check_cmd = f"crontab -l 2>/dev/null | grep -qF '{script_path}'"
    stdin, stdout, stderr = ssh_client.exec_command(check_cmd)
    exit_status = stdout.channel.recv_exit_status()
    if exit_status == 0:
        print(f"Crontab entry already exists, skipping")
        return True

    add_cmd = f"(crontab -l 2>/dev/null; printf '\\n{cron_entry}\\n') | crontab -"
    stdin, stdout, stderr = ssh_client.exec_command(add_cmd)
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        raise Exception(f"Failed to setup crontab: {stderr.read().decode()}")
    return True


def transfer_config_via_scp(
    ssh_client: paramiko.SSHClient, config_content: str, remote_path: str
) -> bool:
    remote_dir = os.path.dirname(remote_path)
    if remote_dir:
        ssh_client.exec_command(f"mkdir -p '{remote_dir}'")[
            1
        ].channel.recv_exit_status()

    cat_cmd = f"cat > '{remote_path}' << 'EOFCONFIG'\n{config_content}\nEOFCONFIG"
    stdin, stdout, stderr = ssh_client.exec_command(cat_cmd)
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        raise Exception(f"SCP transfer failed: {stderr.read().decode()}")
    return True


def generate_vm_config_yaml(
    vm_ip: str,
    kafka_config: Dict[str, Any],
    ssh_config: Dict[str, Any],
    include_ssh: bool = True,
    user_id: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    config = {}
    if vm_ip:
        config["ip"] = vm_ip
    if kafka_config:
        config["kafka"] = kafka_config.copy()
    if include_ssh and ssh_config:
        ssh_copy = ssh_config.copy()
        ssh_copy.pop("password", None)
        config["ssh"] = ssh_copy
    if user_id:
        config["user_id"] = user_id
    if description:
        config["description"] = description
    return yaml.dump(config, default_flow_style=False)


def fetch_nexent_model_config(
    base_url: str, token: Optional[str] = None, model_types: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Fetch model configurations from Nexent Config Service API.

    Args:
        base_url: Nexent Config Service base URL (e.g., http://nexent-config:5010)
        token: Optional JWT token for authentication
        model_types: List of model types to filter (e.g., ["llm"]). If None, returns all.

    Returns:
        List of model configurations
    """
    url = f"{base_url.rstrip('/')}/model/list"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    data = response.json()
    models = data.get("data", [])

    if model_types:
        models = [m for m in models if m.get("model_type") in model_types]

    return models


def fetch_models_from_db(
    host: str,
    password: str,
    model_types: Optional[List[str]] = None,
    database: str = "nexent",
    user: str = "root",
    port: int = 5432,
) -> List[Dict[str, Any]]:
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=database,
            user=user,
            password=password,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to connect to database at {host}:{port}: {e}")

    try:
        with conn.cursor() as cur:
            query = (
                "SELECT model_name, model_factory, model_type, api_key, "
                "base_url, max_tokens, display_name "
                "FROM nexent.model_record_t "
                "WHERE delete_flag = 'N'"
            )
            params: List[Any] = []
            if model_types:
                placeholders = ",".join(["%s"] * len(model_types))
                query += f" AND model_type IN ({placeholders})"
                params = list(model_types)

            cur.execute(query, params)
            desc = cur.description
            if not desc:
                return []
            columns = [d[0] for d in desc]
            rows = cur.fetchall()
            return [dict(zip(columns, row)) for row in rows]
    finally:
        conn.close()


def read_remote_json(
    ssh_client: paramiko.SSHClient, remote_path: str
) -> Optional[Dict[str, Any]]:
    """Read a JSON file from remote host via SSH."""
    stdin, stdout, stderr = ssh_client.exec_command(f"cat '{remote_path}' 2>/dev/null")
    content = stdout.read().decode()
    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def write_remote_json(
    ssh_client: paramiko.SSHClient, remote_path: str, data: Dict[str, Any]
) -> bool:
    """Write a JSON file to remote host via SSH."""
    remote_dir = os.path.dirname(remote_path)
    if remote_dir:
        ssh_client.exec_command(f"mkdir -p '{remote_dir}'")[
            1
        ].channel.recv_exit_status()

    json_content = json.dumps(data, indent=2, ensure_ascii=False)
    cat_cmd = f"cat > '{remote_path}' << 'EOFCONFIG'\n{json_content}\nEOFCONFIG"
    stdin, stdout, stderr = ssh_client.exec_command(cat_cmd)
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        raise Exception(f"Failed to write JSON: {stderr.read().decode()}")
    return True


def transform_nexent_to_openclaw(nexent_models: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Transform Nexent model config format to openclaw format.

    Nexent model -> openclaw provider format:
    {
      "models": {
        "mode": "merge",
        "providers": {
          "<provider_name>": {
            "baseUrl": "...",
            "apiKey": "...",
            "api": "openai-completions",
            "models": [{"id": "provider/model-name", ...}]
          }
        }
      }
    }
    """
    if not nexent_models:
        return {}

    providers: Dict[str, Dict[str, Any]] = {}

    for model in nexent_models:
        model_factory = model.get("model_factory", "openai").lower()
        provider_name = model_factory

        if provider_name not in providers:
            providers[provider_name] = {
                "baseUrl": model.get("base_url", ""),
                "apiKey": model.get("api_key", ""),
                "api": "openai-completions",
                "models": [],
            }

        model_id = f"{provider_name}/{model.get('model_name', 'unknown')}"
        model_entry: Dict[str, Any] = {"id": model_id}

        display_name = model.get("display_name") or model.get("model_name")
        if display_name:
            model_entry["name"] = display_name

        if model.get("max_tokens"):
            model_entry["maxTokens"] = model["max_tokens"]

        providers[provider_name]["models"].append(model_entry)

    return {"models": {"mode": "merge", "providers": providers}}


def sync_model_config_to_vm(
    ssh_client: paramiko.SSHClient,
    nexent_models: List[Dict[str, Any]],
    remote_path: str,
    vm_ip: Optional[str] = None,
    merge: bool = True,
) -> Dict[str, Any]:
    """
    Sync Nexent model config to VM's openclaw.json.

    Args:
        ssh_client: Connected SSH client
        nexent_models: List of model configs from Nexent API
        remote_path: Path to openclaw.json on VM
        vm_ip: VM IP address (used for gateway.controlUi.allowedOrigins)
        merge: If True, merge with existing config; if False, replace

    Returns:
        The final config that was written
    """
    if merge:
        existing_config = read_remote_json(ssh_client, remote_path)
        if existing_config is None:
            existing_config = {}
    else:
        existing_config = {}

    new_model_config = transform_nexent_to_openclaw(nexent_models)

    if "models" not in existing_config:
        existing_config["models"] = {}
    if "providers" not in existing_config["models"]:
        existing_config["models"]["providers"] = {}

    existing_config["models"]["mode"] = new_model_config["models"].get("mode", "merge")

    for provider_name, provider_config in new_model_config["models"][
        "providers"
    ].items():
        existing_config["models"]["providers"][provider_name] = provider_config

    if vm_ip:
        if "gateway" not in existing_config:
            existing_config["gateway"] = {}
        if "controlUi" not in existing_config["gateway"]:
            existing_config["gateway"]["controlUi"] = {}
        if "allowedOrigins" not in existing_config["gateway"]["controlUi"]:
            existing_config["gateway"]["controlUi"]["allowedOrigins"] = []
        new_origin = f"http://{vm_ip}:18789"
        origins = existing_config["gateway"]["controlUi"]["allowedOrigins"]
        if new_origin not in origins:
            origins.append(new_origin)
        existing_config["gateway"]["controlUi"]["dangerouslyDisableDeviceAuth"] = True

    write_remote_json(ssh_client, remote_path, existing_config)

    return existing_config


def create_client_from_config(config_path: str | None = None) -> FusionComputeClient:
    config = load_config(config_path)
    cfg = Config(config)
    csv_path = get_csv_path(config_path)
    ip_manager = IPAllocationManager(str(csv_path))

    client = FusionComputeClient(
        fc_ip=cfg.fc_ip,
        username=cfg.username,
        password=cfg.password,
        timeout=cfg.task_timeout,
        ip_manager=ip_manager,
        ssh_config=cfg.ssh_config,
        kafka_config=cfg.kafka_config,
        config_transfer=cfg.config_transfer,
    )
    client.config = cfg
    return client


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        "-c",
        help="Path to config file (default: /mnt/nexent/vm-config.yaml or config/config.yaml)",
    )
    parser.add_argument("--site-id", "-s", help="Site ID (overrides config)")
    parser.add_argument("--fc-ip", help="FusionCompute IP (overrides config)")
    parser.add_argument("--username", "-u", help="Username (overrides config)")
    parser.add_argument("--password", "-p", help="Password (overrides config)")


def get_client_with_args(args) -> Tuple[FusionComputeClient, Config]:
    client = create_client_from_config(args.config)
    cfg = client.config

    if args.fc_ip:
        client.fc_ip = args.fc_ip
        client.base_url = f"https://{args.fc_ip}:7443"
    if args.username:
        client.username = args.username
    if args.password:
        client.password = args.password

    return client, cfg
