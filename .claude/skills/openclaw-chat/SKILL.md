---
name: openclaw-chat
description: |
  OpenClaw 服务 WebSocket 通信技能，用于向 OpenClaw Agent 发送消息并获取响应。
  
  适用场景：
  - 向 OpenClaw Agent 发送指令或问题
  - 获取 Agent 执行结果
  - 与 Agent 进行交互式对话
  - 执行远程操作（如安装 skills、执行任务等）
  
  触发条件：
  - 用户需要与 OpenClaw 服务通信
  - 用户要求向远程 Agent 发送消息
  - 用户需要执行 OpenClaw 相关操作
---

# OpenClaw Chat

向 OpenClaw 服务发送消息并获取响应。

## 快速开始

```bash
python scripts/chat.py --message "你的消息"
```

## 配置

编辑 `config/config.yaml` 设置默认连接参数：

```yaml
host: "localhost"
port: "18789"
token: "your-token-here"
```

## 使用方式

### 命令行

```bash
# 使用配置文件默认值
python scripts/chat.py --message "列出可用的 skills"

# 覆盖配置参数
python scripts/chat.py --host 192.168.1.100 --port 8080 --token "xxx" --message "安装 skill"
```

### 作为模块导入

```python
import asyncio
from scripts.chat import send_message

async def main():
    result = await send_message(
        host="localhost",
        port="18789",
        token="your-token",
        message="你的消息"
    )
    print(result)

asyncio.run(main())
```

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| --host | WebSocket 服务地址 | config.yaml 中的 host |
| --port | WebSocket 服务端口 | config.yaml 中的 port |
| --token | 认证 token | config.yaml 中的 token |
| --config | 配置文件路径 | ../config/config.yaml |
| --message | 要发送的消息（必填） | - |

## 响应格式

脚本会等待 Agent 返回 `state: final` 的响应，并提取其中的文本内容输出。
