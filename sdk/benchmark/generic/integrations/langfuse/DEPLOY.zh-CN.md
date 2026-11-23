# Webhook 公网部署指南

将本地 webhook server（`localhost:8090`）暴露到公网，供 Langfuse UI 触发实验。Langfuse 限制 webhook URL 只允许 80/443 端口。

## 方案对比

| | ngrok | frp + Caddy |
|---|---|---|
| 复杂度 | 低，一条命令 | 高，需要云服务器 + 配置 |
| 成本 | 免费版可用（URL 每次重启变化） | 需要一台公网服务器 |
| 稳定性 | 免费版 URL 不固定，重启后变 | URL 固定，长期稳定 |
| HTTPS | 自带（`https://xxx.ngrok-free.dev`） | 需额外配置 |
| 适用场景 | 临时调试、快速验证 | 长期使用、团队协作 |

---

## 方案 A：ngrok（快速上手）

### 架构

```
Langfuse UI
    │
    ▼
https://sanded-wired-sturdy.ngrok-free.dev/webhook
    │
    ▼  ngrok tunnel
ngrok (本机)
    │
    ▼
webhook_server.py (localhost:8090)
```

### A.1 安装 ngrok

```bash
# Linux
curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt update && sudo apt install ngrok

# 或直接用 snap
sudo snap install ngrok
```

### A.2 注册并配置 authtoken

免费注册 https://dashboard.ngrok.com/signup ，获取 authtoken：

```bash
ngrok config add-authtoken your-authtoken-here
```

### A.3 启动隧道

```bash
ngrok http 8090
```

输出类似：

```
Forwarding  https://sanded-wired-sturdy.ngrok-free.dev → http://localhost:8090
```

### A.4 Langfuse UI 配置

| 配置项 | 值 |
|--------|-----|
| **URL** | `https://<你的ngrok域名>.ngrok-free.dev/webhook` |
| **Default config** | `{"mode": "run", "evaluators": ["numeric_answer"], "max_steps": 15, "run_name": "webhook-test"}` |

### A.5 注意事项

- **免费版每次重启 ngrok，URL 会变**，需要重新在 Langfuse UI 更新 webhook URL
- 付费版（$8/月）可以固定域名：`ngrok http --domain=your-fixed-domain.ngrok-free.app 8090`
- ngrok 免费版有请求频率限制（约 40 次/分钟），大批量数据集实验可能触发限流
- 访问日志：`http://127.0.0.1:4040`（ngrok 内置 Web UI）

---

## 方案 B：frp + Caddy（长期稳定）

### 架构

```
Langfuse UI
    │
    ▼
http://47.116.185.156/webhook  (公网 IP:80)
    │
    ▼
Caddy (Windows Server 2022)
    │  反向代理 /webhook → 127.0.0.1:8090
    │  其他路径 → basicauth → 110.126.0.52:5173
    ▼
frps (服务端, 端口 7000 通信 + 8090 转发)
    │
    ▼  frp tunnel
frpc (本机 Linux)
    │
    ▼
webhook_server.py (localhost:8090)
```

### B.1 服务端（阿里云 Windows Server 2022）

#### B.1.1 安装 frp

下载 Windows amd64 版本：https://github.com/fatedier/frp/releases

解压到 `C:\frp\`，只需要 `frps.exe` 和 `frps.toml`。

#### B.1.2 配置 frps.toml

```toml
bindPort = 7000
auth.token = "your-strong-secret-here"
```

如果不需要持久化运行，直接 `.\frps.exe -c frps.toml` 即可。

#### B.1.3 注册为 Windows 服务（WinSW）

下载 [WinSW](https://github.com/winsw/winsw/releases) 的 `WinSW-x64.exe`，放到 `C:\frp\` 并重命名为 `frps-service.exe`。

创建 `C:\frp\frps-service.xml`：

```xml
<service>
  <id>frps</id>
  <name>frp Server</name>
  <description>frp reverse proxy server</description>
  <executable>C:\frp\frps.exe</executable>
  <arguments>-c C:\frp\frps.toml</arguments>
  <log mode="roll-by-size">
    <sizeThreshold>10240</sizeThreshold>
    <keepFiles>3</keepFiles>
  </log>
</service>
```

注册并启动：

```powershell
cd C:\frp
.\frps-service.exe install
.\frps-service.exe start
```

#### B.1.4 阿里云安全组

控制台 → ECS → 安全组 → 入方向规则：

| 协议 | 端口 | 授权对象 | 说明 |
|------|------|----------|------|
| TCP | 7000 | 0.0.0.0/0 | frp 通信 |
| TCP | 80 | 0.0.0.0/0 | Caddy 反向代理 |

#### B.1.5 Windows 防火墙

```powershell
New-NetFirewallRule -DisplayName "frp server" -Direction Inbound -Protocol TCP -LocalPort 7000 -Action Allow
New-NetFirewallRule -DisplayName "caddy http" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow
```

#### B.1.6 配置 Caddy

Caddy 已安装在 `C:\Software\`，Caddyfile 内容：

```caddyfile
{
        admin localhost:2019
}

:80 {
        encode gzip zstd

        handle /webhook* {
                reverse_proxy 127.0.0.1:8090
        }

        @protected not path /webhook*
        basicauth @protected {
                admin $2a$14$vp36SFI88sG/uCtXQtGxQ.iESYE1A5LdEc7henuFQgClmxYXLz/bC
        }

        handle @protected {
                reverse_proxy 110.126.0.52:5173 {
                        header_up Host 110.126.0.52:5173
                        header_up X-Real-IP {remote_host}
                }

                header {
                        X-Content-Type-Options "nosniff"
                        X-Frame-Options "SAMEORIGIN"
                        Referrer-Policy "no-referrer"
                        Permissions-Policy "geolocation=(), microphone=(), camera=()"
                        -Server
                }
        }

        log {
                output file C:/Software/caddy/logs/access.log {
                        roll_size 50MiB
                        roll_keep 10
                        roll_keep_for 720h
                }
                format json
        }
}
```

**关键点：**

- `handle /webhook*` 必须放在 `basicauth` 之前，webhook 请求不经过认证
- `@protected not path /webhook*` 确保只有非 webhook 路径需要 basicauth
- `basicauth` 是旧语法（Caddy v2.8+ 建议用 `basic_auth`），功能正常但有 WARN

**Caddy 管理命令：**

```powershell
# 启动（后台运行 + 开启 admin API）
.\caddy.exe start --config Caddyfile

# 热更新配置（不中断服务）
.\caddy.exe reload --config Caddyfile

# 停止
.\caddy.exe stop --config Caddyfile

# 格式化 Caddyfile
.\caddy.exe fmt --overwrite --config Caddyfile
```

> **注意：** `caddy start` 和 `caddy run` 的区别：
> - `start` = 后台运行，开启 admin API（之后 reload/stop 才能用）
> - `run` = 前台运行（Ctrl+C 停止），不开 admin API
> - `reload` 需要 admin API，如果之前用 `run` 启动的会报错

### B.2 客户端（本机 Linux）

#### B.2.1 安装 frp

```bash
wget https://github.com/fatedier/frp/releases/download/v0.61.1/frp_0.61.1_linux_amd64.tar.gz
tar -xzf frp_0.61.1_linux_amd64.tar.gz
sudo mkdir -p /opt/frp
sudo cp frp_0.61.1_linux_amd64/frpc /opt/frp/
sudo cp frp_0.61.1_linux_amd64/frpc.toml /opt/frp/
```

#### B.2.2 配置 frpc.toml

```toml
serverAddr = "47.116.185.156"
serverPort = 7000
auth.token = "your-strong-secret-here"

[[proxies]]
name = "webhook"
type = "tcp"
localIP = "127.0.0.1"
localPort = 8090
remotePort = 8090
```

#### B.2.3 注册为 systemd 服务

```bash
sudo tee /etc/systemd/system/frpc.service << 'EOF'
[Unit]
Description=frp client
After=network.target

[Service]
Type=simple
ExecStart=/opt/frp/frpc -c /opt/frp/frpc.toml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable --now frpc
```

注册后不需要手动 `./frpc -c frpc.toml`，开机自启、崩溃自动重启。

**管理命令：**

```bash
systemctl status frpc          # 查看状态
journalctl -u frpc -f          # 查看实时日志
sudo systemctl restart frpc    # 重启（改配置后）
sudo systemctl stop frpc       # 停止
```

## Langfuse UI 配置

1. Datasets → 选择数据集 → Start Experiment
2. 点击 ⚡ (Custom Experiment)
3. 填写：

| 配置项 | ngrok 方案 | frp + Caddy 方案 |
|--------|-----------|-----------------|
| **URL** | `https://<ngrok域名>.ngrok-free.dev/webhook` | `http://47.116.185.156/webhook` |
| **Default config** | `{"mode": "run", "evaluators": ["numeric_answer"], "max_steps": 15, "run_name": "webhook-test"}` | 同左 |

4. 点击 Save，之后点 Run 触发

## 验证清单

```bash
# 1. 本机 webhook server 健康检查
curl http://localhost:8090/health

# 2. 本机 frpc 状态（仅 frp 方案）
systemctl status frpc

# 3. 公网全链路测试 — frp + Caddy 方案
curl -X POST http://47.116.185.156/webhook \
  -H "Content-Type: application/json" \
  -d '{"dataset_name":"gsm8k-n10","config":{"mode":"run","evaluators":["numeric_answer"],"max_steps":15,"run_name":"full-chain-test"}}'

# 3. 公网全链路测试 — ngrok 方案（替换为你的 ngrok 域名）
curl -X POST https://<ngrok域名>.ngrok-free.dev/webhook \
  -H "Content-Type: application/json" \
  -d '{"dataset_name":"gsm8k-n10","config":{"mode":"run","evaluators":["numeric_answer"],"max_steps":15,"run_name":"ngrok-test"}}'

# 4. 确认其他路径仍需认证（仅 frp 方案，返回 401）
curl -I http://47.116.185.156/
```

## 踩坑记录

### 通用

| 问题 | 原因 | 解决 |
|------|------|------|
| Langfuse 报 "Only ports 80 and 443 are allowed" | Langfuse 限制 webhook URL 端口 | ngrok 自带 443；frp 方案用 Caddy 监听 80 |
| ngrok 免费版重启后 URL 变了 | 免费版不固定域名 | 每次重启后更新 Langfuse UI 的 webhook URL，或升级付费版 |
| webhook 请求被 Langfuse 发出但本机没收到 | 中间链路某环节断了 | 逐层排查：webhook server → frpc/ngrok → frps/Caddy → 网络 |

### frp + Caddy 方案

| 问题 | 原因 | 解决 |
|------|------|------|
| `/webhook` 返回 401 | `handle /webhook*` 没绕过 basicauth | 加 `@protected not path /webhook*` matcher |
| `caddy reload` 报 admin API 连不上 | 之前用 `caddy run` 启动，没开 admin API | 改用 `caddy start` |
| `caddy stop` 报 admin API 连不上 | Caddy 进程已不存在 | `Stop-Process -Name caddy -Force` 后重新 `start` |
| PowerShell 里 `curl` 语法报错 | PS 的 curl 是 `Invoke-WebRequest` 的别名 | 用 `curl.exe` 或 `Invoke-RestMethod` |
| Caddyfile log 块报 `unrecognized subdirective 'roll'` | `roll size` 写成了空格分隔 | 改回 `roll_size`（下划线） |
| 服务端 frps 和客户端 frpc 版本不一致 | 协议可能不兼容 | 两端使用相同版本 |
