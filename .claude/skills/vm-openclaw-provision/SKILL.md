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
  - 从 Nexent 同步模型配置到 VM 的 openclaw.json
  
  核心功能:
  - 自动 Token 管理(每次会话前自动登录获取)
  - 异步任务处理(10 分钟超时,POST|PUT|DELETE 操作需等待任务完成)
  - 基于模板的虚拟机创建与自定义配置
  - 基于 CSV 状态文件的 IP 自动分配,防止并发冲突
  - 支持批量创建虚拟机，自动确保 IP 不冲突
  - SSH/SCP 配置传输,等待虚拟机 SSH 就绪后自动传输配置文件
  - 模型配置同步,从 Nexent API 获取模型配置并更新到 VM
---

# 虚拟机发放技能

FusionCompute 平台上管理虚拟机，每个功能由独立的可执行脚本实现。

## ⚠️ 重要约束

- **创建虚拟机会自动等待完成并传输配置**，无需手动指定 `--wait` 或 `--transfer-config`
- **单次任务中 `create.py` 只允许执行一次**。如果在本次任务中已经成功执行过 `create.py`（无论单个还是批量），禁止再次调用。需要创建多个虚拟机时，使用 `--names` 一次性批量创建
- 不同的任务（不同的用户请求）之间可以分别执行 `create.py`

**用法：**
```bash
python scripts/create.py --name my-vm
```

## 脚本结构

```
scripts/
├── _common.py         # 共享代码（不直接运行）
├── create.py          # 创建虚拟机
├── delete.py          # 删除虚拟机
├── list.py            # 列出资源（站点/虚拟机/IP分配）
├── start.py           # 启动虚拟机
├── stop.py            # 停止虚拟机
├── hibernate.py       # 休眠虚拟机
├── modify.py          # 修改虚拟机配置
├── status.py          # 查询任务状态
└── transfer_config.py # 传输配置到虚拟机
```

## 获取必需参数

以下参数在多数脚本中是必需的，可以通过以下方式获取：

### site-id 获取方式

**从配置文件读取**：
   ```bash
   # 优先级：/mnt/nexent/vm-config.yaml > config/config.yaml
   cat /mnt/nexent/vm-config.yaml | grep site_id
   # 或
   cat config/config.yaml | grep site_id
   ```

### vm-id 获取方式

**从 IP 分配记录查询**：
   ```bash
   # CSV 文件位置：/mnt/nexent/.ip_allocations.csv 或 config/.ip_allocations.csv
   # CSV 字段：ip, status, task_id, vm_id, site_id, name, gateway, netmask, created_at, updated_at
   
   # 通过虚拟机名称查询 vm-id
   grep "<vm-name>" /mnt/nexent/.ip_allocations.csv
   # 或
   grep "<vm-name>" config/.ip_allocations.csv
   ```

### task-id 获取方式

**从 IP 分配记录查询**：
   ```bash
   # CSV 文件位置：/mnt/nexent/.ip_allocations.csv 或 config/.ip_allocations.csv
   # CSV 字段：ip, status, task_id, vm_id, site_id, name, gateway, netmask, created_at, updated_at
   
   # 通过虚拟机名称查询 task_id
   grep "<vm-name>" /mnt/nexent/.ip_allocations.csv
   # 或
   grep "<vm-name>" config/.ip_allocations.csv
   ```

## 通用参数

所有脚本支持以下通用参数：

| 参数 | 说明 |
|------|------|
| `--config, -c` | 配置文件路径（默认: /mnt/nexent/vm-config.yaml 或 config/config.yaml）|
| `--site-id, -s` | 站点 ID（覆盖配置文件）|
| `--fc-ip` | FusionCompute IP（覆盖配置文件）|
| `--username, -u` | 用户名（覆盖配置文件）|
| `--password, -p` | 密码（覆盖配置文件）|

## 脚本使用

### create.py - 创建虚拟机

```bash
# 创建单个虚拟机（自动等待完成 + 传输配置）
python scripts/create.py --name my-vm

# 创建单个虚拟机（指定 IP）
python scripts/create.py --name my-vm --ip 192.168.1.100

# 批量创建虚拟机
python scripts/create.py --names "vm-1,vm-2,vm-3"

# 指定资源配置
python scripts/create.py --name my-vm --cpu 8 --memory 16384
```

**注意：**
- `--wait` 和 `--transfer-config` 已内置为默认行为，无需手动指定
- 同名虚拟机只能创建一次，重复执行会报错（通过 `.create_lock` 文件控制）

**参数说明：**

| 参数 | 说明 |
|------|------|
| `--name, -n` | 虚拟机名称（单个）|
| `--names` | 虚拟机名称列表，逗号分隔（批量）|
| `--vm-id` | 模板虚拟机 ID |
| `--ip` | 指定 IP 地址（不指定则自动分配）|
| `--gateway` | 网关 |
| `--netmask` | 子网掩码 |
| `--cpu` | CPU 核数 |
| `--memory` | 内存（MB）|
| `--hostname` | 主机名|
| `--description, -d` | 描述 |
| `--json` | JSON 格式输出 |

### delete.py - 删除虚拟机

```bash
python scripts/delete.py --vm-id <vm-id> --wait
```

### list.py - 列出资源

```bash
# 列出虚拟机
python scripts/list.py vms

# 列出指定虚拟机
python scripts/list.py vm --vm-id <vm-id>
```

### start.py - 启动虚拟机

```bash
python scripts/start.py --vm-id <vm-id> --wait
```

### stop.py - 停止虚拟机

```bash
python scripts/stop.py --vm-id <vm-id> --wait
```

### hibernate.py - 休眠虚拟机

```bash
python scripts/hibernate.py --vm-id <vm-id> --wait
```

### modify.py - 修改虚拟机配置

```bash
# 修改 CPU
python scripts/modify.py --vm-id <vm-id> --cpu 8 --wait

# 修改内存
python scripts/modify.py --vm-id <vm-id> --memory 16384 --wait

# 同时修改
python scripts/modify.py --vm-id <vm-id> --cpu 8 --memory 16384 --wait
```

### status.py - 查询任务状态

```bash
# 查询状态
python scripts/status.py --task-id <task-id>

# 等待完成
python scripts/status.py --task-id <task-id> --wait
```


### transfer_config.py - 传输配置

```bash
# 传输完整配置（默认：Kafka + 模型配置）
python scripts/transfer_config.py --ip 192.168.1.100

# 只传输 Kafka 配置
python scripts/transfer_config.py --ip 192.168.1.100 --no-include-model

# 只同步模型配置
python scripts/transfer_config.py --ip 192.168.1.100 --no-include-kafka

# 指定 Nexent API 地址
python scripts/transfer_config.py --ip 192.168.1.100 --nexent-api-url http://nexent-config:5010

# 指定要同步的模型类型
python scripts/transfer_config.py --ip 192.168.1.100 --model-types llm embedding

```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `--ip` | 虚拟机 IP 地址 |
| `--ssh-username` | SSH 用户名 |
| `--ssh-password` | SSH 密码 |
| `--ssh-port` | SSH 端口（默认 22）|
| `--remote-path` | 远程目录（默认 /opt/nexent/config）|
| `--filename` | 配置文件名（默认 agent_config.yaml）|
| `--timeout` | SSH 就绪超时（秒，默认 300）|
| `--include-kafka` | 包含 Kafka 配置（默认 True）|
| `--no-include-kafka` | 不包含 Kafka 配置 |
| `--include-model` | 从 Nexent 同步模型配置到 openclaw.json（默认 True）|
| `--no-include-model` | 不同步模型配置 |
| `--openclaw-config-path` | VM 上 openclaw.json 路径（默认 /root/.openclaw/openclaw.json）|
| `--nexent-api-url` | Nexent API 地址（覆盖配置文件）|
| `--nexent-api-token` | Nexent API Token（覆盖配置文件）|
| `--model-types` | 要同步的模型类型（默认 llm），如 `llm embedding vlm` |
| `--json` | JSON 格式输出 |


## 模型配置同步

`transfer_config.py` 支持从 Nexent Config Service 获取模型配置并同步到 VM 的 openclaw.json。

### 配置 Nexent API

在 `vm-config.yaml` 中添加：

```yaml
nexent_api:
  base_url: "http://nexent-config:5010"
  token: ""  # 可选，某些环境需要 JWT Token
  model_sync:
    enabled: true
    openclaw_config_path: "/root/.openclaw/openclaw.json"
    model_types:
      - "llm"
```

### 同步流程

1. 从 Nexent API (`/model/list`) 获取模型配置
2. 转换为 openclaw 格式（`models.providers` 结构）
3. 与 VM 上现有 openclaw.json 合并（保留其他配置）
4. 写入 VM

### openclaw.json 结构示例

同步后的 `openclaw.json` 结构：

```json
{
  "models": {
    "mode": "merge",
    "providers": {
      "openai": {
        "baseUrl": "https://api.openai.com/v1",
        "apiKey": "sk-xxx",
        "api": "openai-completions",
        "models": [
          {"id": "openai/gpt-4o", "name": "GPT-4o", "maxTokens": 128000}
        ]
      }
    }
  },
  "gateway": {
    "controlUi": {
      "allowedOrigins": ["http://192.168.1.100:18789"]
    }
  }
}
```

**注意**：`gateway.controlUi.allowedOrigins` 会自动设置为 `http://<VM_IP>:18789`
## IP 自动分配

IP 分配通过 CSV 状态文件实现并发安全：
- 文件位置: `/mnt/nexent/.ip_allocations.csv` 或 `config/.ip_allocations.csv`
- 状态: `allocating` / `allocated` / `failed` / `released`
- 超时清理: 15 分钟

### IP 重复使用约束

**禁止使用相同 IP 地址多次调用创建接口。**

`create.py` 在调用 API 前会检查指定的 IP 是否已在 CSV 状态文件中处于 `allocating` 或 `allocated` 状态。如果 IP 已被占用，将报错退出。

## 任务超时

所有异步操作的默认超时时间为 **600 秒（10 分钟）**
可以在配置文件中通过 `task_timeout` 修改