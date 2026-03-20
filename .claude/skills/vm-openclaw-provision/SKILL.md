---
name: vm-openclaw-provision
description: |
  FusionCompute 平台虚拟机发放与生命周期管理技能。
  
  适用场景：
  - 从模板创建单个或多个虚拟机（批量创建）
  - 管理虚拟机生命周期（启动、停止、休眠、修改、删除）
  - 查询虚拟机模板和站点信息
  - 操作 FusionCompute API 接口
  - 通过 CSV 状态文件自动分配可用 IP，防止并发冲突
  - 自动传输配置文件到虚拟机（SCP）
  
  核心功能:
  - 自动 Token 管理(每次会话前自动登录获取)
  - 异步任务处理(10 分钟超时,POST|PUT|DELETE 操作需等待任务完成)
  - 基于模板的虚拟机创建与自定义配置
  - 基于 CSV 状态文件的 IP 自动分配,防止并发冲突
  - 支持批量创建虚拟机，自动确保 IP 不冲突
  - SSH/SCP 配置传输,等待虚拟机 SSH 就绪后自动传输配置文件
  - 自动清理超时 15 分钟的 allocating 记录
  
  创建虚拟机时的必要技能调用:
  - 创建虚拟机后必须调用配置传输功能（transfer_config）
  - 将环境 IP 和 Kafka 凭证传输到新创建的虚拟机
---

# 虚拟机发放技能

FusionCompute 平台上管理虚拟机，支持自动 Token 处理、异步任务管理和基于 CSV 状态文件的 IP 自动分配。
## 关键要求
### 1. 必须先登录
在执行任何操作之前,必须调用登录接口获取 `X-Auth-Token`：
```
POST /service/session
Headers:
  Accept: application/json;version=8.1;charset=UTF-8
  X-Auth-User: <用户名>
  X-Auth-Key: <密码>
  X-Auth-UserType: 2
  X-ENCRYPT-ALGORITHM: 1

Response Headers:
  X-Auth-Token: <token>
```

### 2. 处理异步任务(10 分钟超时)
所有 POST|PUT|DELETE 操作都会返回 `task_id`。必须:
1. 从响应中提取 `task_id`
2. 轮询任务状态接口直到成功
3. 任务完成后才能继续下一步操作
```
GET /service/sites/<site_id>/tasks/<task_id>
Headers:
  X-Auth-Token: <token>

超时时间: 600 秒(10 分钟)
```

### 3. 仅支持单虚拟机操作
此技能每次只处理一台虚拟机
- 每次请求创建一台虚拟机
- 每次修改一台虚拟机
- 每次启动/停止/休眠/删除一台虚拟机
## 配置文件
### config/config.yaml 结构
从 `config/config.yaml` 加载凭据和网络配置
```yaml
# FusionCompute 配置
fc_ip: 100.199.5.10
cpu: 4
memory: 8192  # 单位:MB
X-Auth-User: test
X-Auth-Key: Huawei@4321
site_id: ABCDE
vm_id: i00001
gateway: "192.168.1.1"
netmask: "255.255.255.0"
task_timeout: 600  # 任务超时时间(秒)
```
### 配置项说明
| 配置项 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| fc_ip | string | 是 | FusionCompute 服务器 IP |
| cpu | int | 否 | 默认 CPU 核数,默认 4 |
| memory | int | 否 | 默认内存大小（MB)，默认 8192 |
| X-Auth-User | string | 是 | 登录用户名 |
| X-Auth-Key | string | 是 | 登录密码 |
| site_id | string | 是 | 站点 ID |
| vm_id | string | 是 | 模板虚拟机 ID |
| gateway | string | 是 | 网关地址 |
| netmask | string | 是 | 子网掩码 |
| task_timeout | int | 否 | 任务超时时间(秒)，默认 600 |
## IP 自动分配
### 基于 CSV 状态文件
IP 分配通过 CSV 状态文件实现并发安全。
文件位置: `config/.ip_allocations.csv`
#### CSV 结构
| 字段 | 说明 |
|------|------|
| ip | IP 地址 |
| status | `allocating` / `allocated` / `failed` |
| task_id | 异步任务 ID |
| vm_id | 虚拟机 ID（创建成功后写入) |
| site_id | 站点 ID |
| name | 虚拟机名称 |
| gateway | 网关地址 |
| netmask | 子网掩码 |
| created_at | 创建时间 |
| updated_at | 更新时间 |
**状态说明:**
- `allocating`: IP 已预占用，正在创建中，异步任务等待
- `allocated`: 创建成功, VM 已运行
- `failed`: 创建失败, 可手动标记为 failed (allocating 超时 15 分钟)
### 并发安全
- 读取 CSV 跳过所有 `allocating` / `allocated` 状态的 IP
- 装载网关/子网不匹配的 IP 也跳过
- 选择第一个未在 CSV 中出现的 IP
- 写入 CSV (状态=allocating) 预占用
- 调用 clone_vm API
- 等待任务完成
- 更新 CSV (状态=allocated, vm_id)
- 自动清理超过 15 分钟的 `allocating` 记录
### 工作流程
#### 批量创建虚拟机(自动分配 IP)
1. **加载配置** → 读取 config/config.yaml
2. **创建客户端** → 使用凭据初始化
3. **登录** → 获取 token
4. **批量克隆** → 逐个分配 IP 并克隆虚拟机
5. **等待任务** → 轮询所有任务直到完成
6. **传输配置** → **必须**通过 SCP 传输配置文件到虚拟机
7. **报告结果** → 返回所有虚拟机的创建结果
#### 创建虚拟机(自动分配 IP)
1. **加载配置** → 读取 config/config.yaml
2. **创建客户端** → 使用凭据初始化
3. **登录** → 获取 token
4. **克隆虚拟机** → 通过 CSV 状态文件自动分配可用 IP
5. **轮询任务** → 轮询直到任务完成
6. **传输配置** → **必须**通过 SCP 传输配置文件到虚拟机
7. **报告结果** → 返回虚拟机详情和分配的 IP
#### 使用指定 IP 创建虚拟机
1. **登录** → 获取 token
2. **获取站点** → 找到目标 site_id
3. **列出虚拟机** → 找到模板 vm_id
4. **克隆虚拟机** → 使用指定 IP
5. **轮询任务** → 轮询直到任务完成
6. **传输配置** → **必须**通过 SCP 传输配置文件到虚拟机
## API 参考
完整接口文档请参阅 [references/api_reference.md](references/api_reference.md)
## 使用示例
### 创建虚拟机(自动分配 IP)
```python
from fc_client import create_client_from_config

client = create_client_from_config("config/config.yaml")
token = client.login()
print(f"登录成功, token: {token[:20]}...")

task_id, ip = client.clone_vm_auto_ip(
    site_id="ABCDE",
    vm_id="i00001",
    name="my-new-vm",
    gateway="192.168.1.1",
    netmask="255.255.255.0",
    cpu=4,
    memory=8192
)
print(f"正在创建虚拟机,分配的 IP: {ip}")

# 必须启用配置传输
client.wait_for_task_and_update_ip(
    site_id="ABCDE",
    task_id=task_id,
    ip=ip,
    transfer_config=True  # 必须传输配置
)
print(f"虚拟机创建成功, IP: {ip}")
```
### 批量创建虚拟机
```python
from fc_client import create_client_from_config

client = create_client_from_config("config/config.yaml")
token = client.login()

vm_configs = [
    {
        "name": "vm-1",
        "gateway": "192.168.1.1",
        "netmask": "255.255.255.0",
        "cpu": 4,
        "memory": 8192,
    },
    {
        "name": "vm-2",
        "gateway": "192.168.1.1",
        "netmask": "255.255.255.0",
        "cpu": 2,
        "memory": 4096,
    },
    {
        "name": "vm-3",
        "gateway": "192.168.1.1",
        "netmask": "255.255.255.0",
    },
]

results = client.clone_vms_batch(
    site_id="ABCDE",
    vm_id="i00001",
    vm_configs=vm_configs,
)

for result in results:
    if result["success"]:
        print(f"✅ {result['name']}: IP={result['ip']}, task_id={result['task_id']}")
    else:
        print(f"❌ {result['name']}: {result['error']}")

# 等待所有任务完成并传输配置
task_results = client.wait_for_tasks_batch(
    site_id="ABCDE",
    tasks=results,
    transfer_config=True,
)

for result in task_results:
    name = result.get("name", "")
    if result.get("task_completed"):
        print(f"✅ {name}: 任务完成")
    else:
        error = result.get("error", "Unknown error")
        print(f"❌ {name}: {error}")
```
### 创建虚拟机(指定 IP)
```python
from fc_client import create_client_from_config

client = create_client_from_config("config/config.yaml")
client.login()

task_id, ip = client.clone_vm(
    site_id="ABCDE",
    vm_id="i00001",
    name="my-specific-ip-vm",
    ip="192.168.1.150",
    gateway="192.168.1.1",
    netmask="255.255.255.0"
)

# 必须传输配置
client.wait_for_task(site_id="ABCDE", task_id=task_id)
client._transfer_config_to_vm("192.168.1.150")
```
### 查看已分配的 IP
```python
client.ip_manager.get_allocated_ips("192.168.1.1", "255.255.255.0")
```
### 查看特定 IP 的分配信息
```python
allocation = client.ip_manager.get_allocation("192.168.1.100")
print(f"VM ID: {allocation.get('vm_id')}")
```
### 清理超时记录
```python
cleaned = client.ip_manager.cleanup_stale()
print(f"Cleaned {cleaned} stale records")
```
## 配置传输到虚拟机

### 功能说明

**重要：创建虚拟机后必须调用配置传输功能。**

虚拟机创建完成后，必须通过 SSH/SCP 自动传输配置文件到虚拟机。配置文件包含：
- 虚拟机 IP 地址
- 当前环境 IP
- Kafka 连接配置（用户名、密码等）

### 配置设置

在 `config/config.yaml` 中添加以下配置：

```yaml
# SSH 配置（用于连接虚拟机传输配置）
ssh:
  username: "root"
  password: "VM_PASSWORD"
  port: 22
  connect_timeout: 30
  ready_timeout: 300

# Kafka 配置（将传输到虚拟机）
kafka:
  bootstrap_servers: "192.168.1.100:9092"
  sasl_username: "kafka_user"
  sasl_password: "kafka_password"
  security_protocol: "SASL_PLAINTEXT"
  sasl_mechanism: "PLAIN"

# 配置文件传输设置
config_transfer:
  enabled: true
  remote_path: "/opt/nexent/config"
  config_filename: "agent_config.yaml"
```

### 配置项说明

| 配置项 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| ssh.username | string | 是 | SSH 用户名 |
| ssh.password | string | 是 | SSH 密码 |
| ssh.port | int | 否 | SSH 端口，默认 22 |
| ssh.connect_timeout | int | 否 | SSH 连接超时（秒），默认 30 |
| ssh.ready_timeout | int | 否 | 等待 SSH 就绪超时（秒），默认 300 |
| kafka.bootstrap_servers | string | 是 | Kafka 服务器地址 |
| kafka.sasl_username | string | 否 | Kafka SASL 用户名 |
| kafka.sasl_password | string | 否 | Kafka SASL 密码 |
| kafka.security_protocol | string | 否 | 安全协议，默认 SASL_PLAINTEXT |
| kafka.sasl_mechanism | string | 否 | SASL 机制，默认 PLAIN |
| config_transfer.enabled | bool | 否 | 是否启用配置传输，默认 false |
| config_transfer.remote_path | string | 否 | 远程目录，默认 /opt/nexent/config |
| config_transfer.config_filename | string | 否 | 配置文件名，默认 agent_config.yaml |

### 工作流程

1. **创建虚拟机** → 克隆虚拟机并等待任务完成
2. **等待 SSH 就绪** → 轮询检测 SSH 服务可用性（指数退避）
3. **连接虚拟机** → 使用 SSH 用户名/密码连接
4. **传输配置** → 通过 SCP 传输配置文件（使用 SSH exec_command）
5. **验证成功** → 确认文件传输成功

### 使用示例

```python
from fc_client import create_client_from_config

client = create_client_from_config("config/config.yaml")
token = client.login()

# 克隆虚拟机
task_id, ip = client.clone_vm_auto_ip(
    site_id="ABCDE",
    vm_id="i00001",
    name="my-new-vm",
    gateway="192.168.1.1",
    netmask="255.255.255.0",
)

# 等待任务完成并传输配置（transfer_config=True 是必须的）
client.wait_for_task_and_update_ip(
    site_id="ABCDE",
    task_id=task_id,
    ip=ip,
    transfer_config=True  # 必须启用配置传输
)

print(f"虚拟机创建成功，配置已传输: {ip}")
```

### 生成的配置文件示例

```yaml
vm:
  ip: 192.168.1.100

kafka:
  bootstrap_servers: "192.168.1.100:9092"
  sasl_username: "kafka_user"
  sasl_password: "kafka_password"
  security_protocol: "SASL_PLAINTEXT"
  sasl_mechanism: "PLAIN"

ssh:
  username: "root"
  port: 22
```

## 辅助脚本
`scripts/fc_client.py` 提供:
- `FusionComputeClient` - 主要客户端类
- `IPAllocationManager` - CSV 状态文件管理
- `clone_vm_auto_ip()` - 创建单个虚拟机（自动分配 IP）
- `clone_vms_batch()` - 批量创建虚拟机（防止 IP 冲突）
- `wait_for_task_and_update_ip()` - 等待单个任务完成并更新 IP
- `wait_for_tasks_batch()` - 等待批量任务完成并更新 IP
- `get_available_ip()` - 获取可用 IP
- `Config` - 配置加载类
- `create_client_from_config()` - 工厂函数
## 任务超时
所有异步操作的默认超时时间为 **600 秒(10 分钟)
可以在配置文件中通过 `task_timeout` 修改
