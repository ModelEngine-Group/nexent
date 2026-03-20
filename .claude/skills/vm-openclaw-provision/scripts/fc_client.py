#!/usr/bin/env python3
"""
FusionCompute VM Provisioning Helper

This script provides helper functions for common VM operations on FusionCompute platform.
Uses CSV state file to track IP allocations and prevent race conditions.
Includes SSH/SCP config transfer functionality.
"""

import csv
import ipaddress
import os
import socket
import requests
import time
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any

import paramiko

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
    """Manages IP allocations via CSV file."""

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
        now = datetime.now()

        for r in records:
            if not self._ip_in_subnet(r["ip"], gateway, netmask):
                continue

            status = r.get("status", "")
            if status == "allocated" or status == "allocating":
                allocated.add(r["ip"])

        return allocated

    def allocate_ip(
        self,
        ip: str,
        task_id: str,
        site_id: str,
        name: str,
        gateway: str,
        netmask: str,
    ) -> None:
        now = datetime.now().isoformat()
        record = {
            "ip": ip,
            "status": "allocating",
            "task_id": task_id,
            "vm_id": "",
            "site_id": site_id,
            "name": name,
            "gateway": gateway,
            "netmask": netmask,
            "created_at": now,
            "updated_at": now,
        }
        self._append(record)

    def mark_allocated(self, ip: str, vm_id: str) -> None:
        records = self._read_all()
        for r in records:
            if r["ip"] == ip and r["status"] == "allocating":
                r["status"] = "allocated"
                r["vm_id"] = vm_id
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

    def list_by_vm(self, vm_id: str) -> List[Dict[str, Any]]:
        records = self._read_all()
        return [r for r in records if r.get("vm_id") == vm_id]


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


def wait_for_ssh_ready(
    host: str,
    port: int = 22,
    timeout: int = 300,
    initial_delay: float = 5.0,
    backoff_factor: float = 1.5,
    max_delay: float = 30.0,
) -> bool:
    delay = initial_delay
    start_time = time.time()
    attempt = 0

    while time.time() - start_time < timeout:
        attempt += 1

        if not is_port_open(host, port, timeout=5):
            time.sleep(delay)
            delay = min(delay * backoff_factor, max_delay)
            continue

        try:
            transport = paramiko.Transport((host, port))
            transport.banner_timeout = 5
            transport.connect()
            transport.close()
            elapsed = time.time() - start_time
            print(f"SSH ready after {elapsed:.1f}s ({attempt} attempts)")
            return True
        except paramiko.SSHException:
            elapsed = time.time() - start_time
            print(f"SSH ready after {elapsed:.1f}s ({attempt} attempts)")
            return True
        except Exception:
            pass

        time.sleep(delay)
        delay = min(delay * backoff_factor, max_delay)

    raise TimeoutError(f"SSH not ready after {timeout}s ({attempt} attempts)")


def create_ssh_client(
    host: str,
    username: str,
    password: str,
    port: int = 22,
    timeout: int = 30,
) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=username,
        password=password,
        timeout=timeout,
    )
    return client


def transfer_config_via_scp(
    ssh_client: paramiko.SSHClient,
    config_content: str,
    remote_path: str,
    chmod: int = 0o600,
) -> bool:
    """Transfer config content to remote VM via SSH exec_command (SCP-like)."""
    remote_dir = os.path.dirname(remote_path)

    if remote_dir:
        stdin, stdout, stderr = ssh_client.exec_command(f"mkdir -p '{remote_dir}'")
        stdout.channel.recv_exit_status()

    cat_cmd = f"cat > '{remote_path}' << 'EOFCONFIG'\n{config_content}\nEOFCONFIG"
    stdin, stdout, stderr = ssh_client.exec_command(cat_cmd)
    exit_status = stdout.channel.recv_exit_status()

    if exit_status != 0:
        err_output = stderr.read().decode()
        raise Exception(
            f"SCP transfer failed with exit code {exit_status}: {err_output}"
        )

    stdin, stdout, stderr = ssh_client.exec_command(
        f"chmod {oct(chmod)[2:]} '{remote_path}'"
    )
    stdout.channel.recv_exit_status()

    print(f"Config transferred via SCP: {remote_path}")
    return True


def generate_vm_config_yaml(
    vm_ip: str,
    kafka_config: Optional[Dict[str, Any]],
    ssh_config: Optional[Dict[str, Any]],
) -> str:
    config: Dict[str, Any] = {
        "vm": {
            "ip": vm_ip,
        }
    }

    if kafka_config:
        config["kafka"] = kafka_config.copy()

    if ssh_config:
        ssh_copy = ssh_config.copy()
        ssh_copy.pop("password", None)
        config["ssh"] = ssh_copy

    return yaml.dump(config, default_flow_style=False)


class FusionComputeClient:
    """Client for FusionCompute API operations."""

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
            "customProperties": {"user": "test"},
        }

        response = requests.post(
            url, headers=self._get_headers(), json=body, verify=False
        )
        response.raise_for_status()
        task_id = response.json().get("task_id")

        return (task_id, ip)

    def clone_vm_auto_ip(
        self,
        site_id: str,
        vm_id: str,
        name: str,
        gateway: str,
        netmask: str,
        cpu: int = 4,
        memory: int = 8192,
        hostname: str = "",
        description: str = "",
        exclude_ips: Optional[List[str]] = None,
    ) -> Tuple[str, str]:
        if not self.ip_manager:
            raise RuntimeError("IP manager not configured")

        ip = get_available_ip(self.ip_manager, gateway, netmask, exclude_ips)

        if not ip:
            raise RuntimeError(
                f"No available IP addresses found in subnet {gateway}/{netmask}"
            )

        task_id, _ = self.clone_vm(
            site_id=site_id,
            vm_id=vm_id,
            name=name,
            cpu=cpu,
            memory=memory,
            ip=ip,
            gateway=gateway,
            netmask=netmask,
            hostname=hostname,
            description=description,
        )

        self.ip_manager.allocate_ip(ip, task_id, site_id, name, gateway, netmask)

        return (task_id, ip)

    def wait_for_task_and_update_ip(
        self,
        site_id: str,
        task_id: str,
        ip: str,
        timeout: Optional[int] = None,
        transfer_config: bool = False,
    ) -> bool:
        if not self.ip_manager:
            return self.wait_for_task(site_id, task_id, timeout)

        try:
            result = self.wait_for_task(site_id, task_id, timeout)
            if result:
                allocation = self.ip_manager.get_allocation(ip)
                vm_name = allocation.get("name") if allocation else ""

                vms = self.get_vms(site_id)
                vm_id = None
                for vm in vms:
                    if isinstance(vm, dict):
                        if vm.get("name") == vm_name:
                            vm_id = (
                                vm.get("id")
                                or vm.get("vm_id")
                                or vm.get("urn", "").split(":")[-1]
                            )
                            break

                if transfer_config:
                    self._transfer_config_to_vm(ip)

                self.ip_manager.mark_allocated(ip, vm_id or "")
            return result
        except Exception:
            self.ip_manager.mark_failed(ip)
            raise

    def clone_vms_batch(
        self,
        site_id: str,
        vm_id: str,
        vm_configs: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Batch create VMs with IP conflict prevention.

        Args:
            site_id: Site ID
            vm_id: Template VM ID
            vm_configs: List of VM config dicts, each containing:
                - name: VM name
                - cpu: CPU cores (optional, default 4)
                - memory: Memory in MB (optional, default 8192)
                - gateway: Gateway address
                - netmask: Netmask
                - hostname: Hostname (optional)
                - description: Description (optional)

        Returns:
            List of results, each containing:
                - name: VM name
                - success: bool
                - task_id: str | None
                - ip: str | None
                - error: str | None
        """
        if not self.ip_manager:
            raise RuntimeError("IP manager not configured")

        results = []
        allocated_ips = []

        for config in vm_configs:
            name = config.get("name", "")
            gateway = config.get("gateway", "")
            netmask = config.get("netmask", "")
            cpu = config.get("cpu", 4)
            memory = config.get("memory", 8192)
            hostname = config.get("hostname", "")
            description = config.get("description", "")

            result = {
                "name": name,
                "success": False,
                "task_id": None,
                "ip": None,
                "error": None,
            }

            try:
                ip = get_available_ip(
                    self.ip_manager, gateway, netmask, exclude_ips=allocated_ips
                )

                if not ip:
                    result["error"] = f"No available IP in subnet {gateway}/{netmask}"
                    results.append(result)
                    continue

                allocated_ips.append(ip)
                task_id, _ = self.clone_vm(
                    site_id=site_id,
                    vm_id=vm_id,
                    name=name,
                    cpu=cpu,
                    memory=memory,
                    ip=ip,
                    gateway=gateway,
                    netmask=netmask,
                    hostname=hostname,
                    description=description,
                )

                self.ip_manager.allocate_ip(
                    ip, task_id, site_id, name, gateway, netmask
                )

                result["success"] = True
                result["task_id"] = task_id
                result["ip"] = ip

            except Exception as e:
                result["error"] = str(e)

            results.append(result)

        return results

    def wait_for_tasks_batch(
        self,
        site_id: str,
        tasks: List[Dict[str, Any]],
        timeout: Optional[int] = None,
        transfer_config: bool = False,
    ) -> List[Dict[str, Any]]:
        """Wait for batch tasks and update IP status.

        Args:
            site_id: Site ID
            tasks: List of task results from clone_vms_batch
            timeout: Timeout in seconds (optional)
            transfer_config: Whether to transfer config after success

        Returns:
            List of updated results with task completion status
        """
        if not self.ip_manager:
            return tasks

        results = []

        for task in tasks:
            name = task.get("name", "")
            task_id = task.get("task_id")
            ip = task.get("ip")

            result = task.copy()

            try:
                if task_id and ip:
                    wait_result = self.wait_for_task_and_update_ip(
                        site_id=site_id,
                        task_id=task_id,
                        ip=ip,
                        timeout=timeout,
                        transfer_config=transfer_config,
                    )

                    result["task_completed"] = wait_result
                else:
                    result["task_completed"] = False
                    result["error"] = "No task_id or IP"

            except Exception as e:
                result["task_completed"] = False
                result["error"] = str(e)

            results.append(result)

        return results

    def _transfer_config_to_vm(self, vm_ip: str) -> bool:
        if not self.config_transfer or not self.config_transfer.get("enabled", False):
            print("Config transfer disabled, skipping...")
            return False

        if not self.ssh_config:
            print("SSH config not provided, skipping config transfer...")
            return False

        ssh_username = self.ssh_config.get("username", "root")
        ssh_password = self.ssh_config.get("password", "")
        ssh_port = self.ssh_config.get("port", 22)
        ssh_ready_timeout = self.ssh_config.get("ready_timeout", 300)

        remote_path = self.config_transfer.get("remote_path", "/opt/nexent/config")
        config_filename = self.config_transfer.get(
            "config_filename", "agent_config.yaml"
        )
        full_remote_path = f"{remote_path}/{config_filename}"

        print(f"Waiting for SSH ready on {vm_ip}:{ssh_port}...")
        wait_for_ssh_ready(vm_ip, ssh_port, timeout=ssh_ready_timeout)

        print(f"Connecting to {vm_ip} via SSH...")
        ssh_client = create_ssh_client(vm_ip, ssh_username, ssh_password, ssh_port)

        try:
            config_content = generate_vm_config_yaml(
                vm_ip, self.kafka_config, self.ssh_config
            )
            print(f"Transferring config to {full_remote_path}...")
            return transfer_config_via_scp(ssh_client, config_content, full_remote_path)
        finally:
            ssh_client.close()

    def start_vm(self, site_id: str, vm_id: str) -> str:
        url = f"{self.base_url}/service/sites/{site_id}/vms/{vm_id}/action/start"
        response = requests.post(url, headers=self._get_headers(), verify=False)
        response.raise_for_status()
        return response.json().get("task_id")

    def stop_vm(self, site_id: str, vm_id: str) -> str:
        url = f"{self.base_url}/service/sites/{site_id}/vms/{vm_id}/action/stop"
        response = requests.post(url, headers=self._get_headers(), verify=False)
        response.raise_for_status()
        return response.json().get("task_id")

    def hibernate_vm(self, site_id: str, vm_id: str) -> str:
        url = f"{self.base_url}/service/sites/{site_id}/vms/{vm_id}/action/hibernate"
        response = requests.post(url, headers=self._get_headers(), verify=False)
        response.raise_for_status()
        return response.json().get("task_id")

    def modify_vm_cpu(self, site_id: str, vm_id: str, cpu: int) -> str:
        url = f"{self.base_url}/service/sites/{site_id}/vms/{vm_id}"
        body = {"cpu": {"quantity": cpu}}
        response = requests.put(
            url, headers=self._get_headers(), json=body, verify=False
        )
        response.raise_for_status()
        return response.json().get("task_id")

    def modify_vm_memory(self, site_id: str, vm_id: str, memory_mb: int) -> str:
        url = f"{self.base_url}/service/sites/{site_id}/vms/{vm_id}"
        body = {"memory": {"quantityMB": memory_mb}}
        response = requests.put(
            url, headers=self._get_headers(), json=body, verify=False
        )
        response.raise_for_status()
        return response.json().get("task_id")

    def delete_vm(self, site_id: str, vm_id: str) -> str:
        url = f"{self.base_url}/service/sites/{site_id}/vms/{vm_id}"
        response = requests.delete(url, headers=self._get_headers(), verify=False)
        response.raise_for_status()
        return response.json().get("task_id")

    def get_task(self, site_id: str, task_id: str) -> dict:
        url = f"{self.base_url}/service/sites/{site_id}/tasks/{task_id}"
        response = requests.get(url, headers=self._get_headers(), verify=False)
        response.raise_for_status()
        return response.json()

    def wait_for_task(
        self,
        site_id: str,
        task_id: str,
        timeout: Optional[int] = None,
        initial_delay: float = 1.0,
        max_delay: float = 30.0,
        progress_callback=None,
    ) -> bool:
        if timeout is None:
            timeout = self.timeout

        start_time = time.time()
        delay = initial_delay
        attempt = 0

        while time.time() - start_time < timeout:
            task = self.get_task(site_id, task_id)
            status = task.get("status", "").lower()
            elapsed = time.time() - start_time
            attempt += 1

            if progress_callback:
                progress_callback(status, elapsed)

            if status in ("success", "complete", "completed"):
                return True

            if status in ("failed", "error"):
                error_msg = task.get("error", {}).get("message", "Unknown error")
                raise RuntimeError(f"Task failed after {elapsed:.1f}s: {error_msg}")

            if attempt % 5 == 0:
                print(f"Task {task_id}: status={status}, elapsed={elapsed:.1f}s")

            time.sleep(delay)
            delay = min(delay * 2, max_delay)

        raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")


def load_config(config_path: str = "config/config.yaml") -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


class Config:
    def __init__(self, config_dict: dict):
        self._raw = config_dict

    def _get(self, *keys, default=None):
        for key in keys:
            if key in self._raw:
                return self._raw[key]
        return default

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
        return self._get("netmask", "NETMASK")

    @property
    def task_timeout(self) -> int:
        val = self._get("task_timeout", "TASK_TIMEOUT", default=600)
        return val if isinstance(val, int) else 600

    @property
    def ssh_config(self) -> Optional[Dict[str, Any]]:
        return self._get("ssh", {})

    @property
    def kafka_config(self) -> Optional[Dict[str, Any]]:
        return self._get("kafka", {})

    @property
    def config_transfer(self) -> Optional[Dict[str, Any]]:
        return self._get("config_transfer", {})


def create_client_from_config(
    config_path: str = "config/config.yaml",
) -> FusionComputeClient:
    config = load_config(config_path)
    cfg = Config(config)

    config_dir = Path(config_path).parent
    csv_path = config_dir / ".ip_allocations.csv"
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


if __name__ == "__main__":
    client = create_client_from_config("config/config.yaml")
    cfg = client.config

    if cfg:
        print(f"FC IP: {cfg.fc_ip}")
        print(f"Site ID: {cfg.site_id}")
        print(f"VM ID: {cfg.vm_id}")
        print(f"Gateway: {cfg.gateway}")
        print(f"Netmask: {cfg.netmask}")
        print(f"Timeout: {cfg.task_timeout}s")
        if cfg.ssh_config:
            print(
                f"SSH: {cfg.ssh_config.get('username')}@port:{cfg.ssh_config.get('port')}"
            )
        if cfg.config_transfer:
            print(f"Config Transfer: enabled={cfg.config_transfer.get('enabled')}")

    token = client.login()
    print(f"Logged in, token: {token[:20]}...")

    sites = client.get_sites()
    print(f"Found {len(sites)} sites")

    if cfg and cfg.gateway and cfg.netmask and client.ip_manager:
        allocated = client.ip_manager.get_allocated_ips(cfg.gateway, cfg.netmask)
        print(f"Allocated IPs: {allocated}")

        ip = get_available_ip(client.ip_manager, cfg.gateway, cfg.netmask)
        if ip:
            print(f"Available IP: {ip}")
        else:
            print("No available IP found")
