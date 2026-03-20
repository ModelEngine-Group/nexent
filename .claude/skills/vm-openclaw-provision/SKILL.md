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
---

# 虚拟机发放技能

FusionCompute 平台上管理虚拟机，每个功能由独立的可执行脚本实现。

## ⚠️ 重要提醒：创建虚拟机后必须传输配置

**创建虚拟机完成后，必须执行配置传输操作！**

新创建的虚拟机需要接收以下配置才能正常工作：
- 虚拟机自身的 IP 地址
- 环境服务器 IP 地址
- Kafka 连接凭证

**正确用法：**
```bash
# 方式一：创建时自动传输配置（推荐）
python scripts/create.py --name my-vm --wait --transfer-config

# 方式二：创建后手动传输配置
python scripts/create.py --name my-vm --wait
python scripts/transfer_config.py --ip 192.168.1.100
```

**如果跳过配置传输，环境将无法监管虚拟机！**

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

1. **从配置文件读取**（推荐）：
   ```bash
   # 优先级：/mnt/nexent/vm-config.yaml > config/config.yaml
   cat /mnt/nexent/vm-config.yaml | grep site_id
   # 或
   cat config/config.yaml | grep site_id
   ```

2. **查询所有站点**：
   ```bash
   python scripts/list.py sites
   ```

### vm-id 获取方式

1. **从 IP 分配记录查询**（推荐）：
   ```bash
   # CSV 文件位置：/mnt/nexent/.ip_allocations.csv 或 config/.ip_allocations.csv
   # CSV 字段：ip, status, task_urn, vm_id, site_id, name, gateway, netmask, created_at, updated_at
   
   # 通过虚拟机名称查询 vm-id
   grep "<vm-name>" /mnt/nexent/.ip_allocations.csv
   # 或
   grep "<vm-name>" config/.ip_allocations.csv
   ```

2. **查询所有虚拟机并筛选**：
   ```bash
   python scripts/list.py vms --site-id <site-id>
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
# 创建单个虚拟机（自动分配 IP）
python scripts/create.py --name my-vm --wait

# 创建单个虚拟机（指定 IP）
python scripts/create.py --name my-vm --ip 192.168.1.100 --wait

# 批量创建虚拟机
python scripts/create.py --names "vm-1,vm-2,vm-3" --wait

# 创建后传输配置
python scripts/create.py --name my-vm --wait --transfer-config

# 指定资源配置
python scripts/create.py --name my-vm --cpu 8 --memory 16384 --wait
```

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
| `--wait, -w` | 等待任务完成 |
| `--transfer-config` | **必须**：创建后传输配置（推荐）|
| `--skip-config-warning` | 跳过配置传输警告（不推荐）|
| `--json` | JSON 格式输出 |

### delete.py - 删除虚拟机

```bash
python scripts/delete.py --vm-id <vm-id> --wait
```

### list.py - 列出资源

```bash
# 列出站点
python scripts/list.py sites

# 列出虚拟机
python scripts/list.py vms --site-id <site-id>

# 列出 IP 分配
python scripts/list.py ips

# 按状态过滤
python scripts/list.py ips --status allocated
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
# 1234: 传输完整配置（默认：VM + Kafka + SSH）
python scripts/transfer_config.py --ip 192.168.1.100

# 只传输 Kafka 配置
python scripts/transfer_config.py --ip 192.168.1.100 --no-include-vm --no-include-ssh

# 只传输 VM 配置
python scripts/transfer_config.py --ip 192.168.1.100 --no-include-kafka --no-include-ssh

# 只传输 SSH 配置
python scripts/transfer_config.py --ip 192.168.1.100 --no-include-vm --no-include-kafka

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
| `--include-vm` | 包含 VM 配置（默认 True）|
| `--no-include-vm` | 不包含 VM 配置 |
| `--include-kafka` | 包含 Kafka 配置（默认 True）|
| `--no-include-kafka` | 不包含 Kafka 配置 |
| `--include-ssh` | 包含 SSH 配置（默认 True）|
| `--no-include-ssh` | 不包含 SSH 配置 |
| `--json` | JSON 格式输出 |
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