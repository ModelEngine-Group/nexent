# Nexent 借鉴 DeepSeek Harness 本地执行能力的分析

**日期**：2026-10-29
**类型**：技术架构对比 / 能力规划参考

---

## 📌 TL;DR

- **核心差异**：DeepSeek Harness 的设计哲学是「**本机即执行域**」——shell、文件、终端、电脑操作都以插件形式注册在**用户本机进程**上，靠 OS 级沙箱（Linux bwrap/Landlock、macOS Seatbelt、Windows ACL restricted-token）做文件级约束；Nexent 的设计哲学是「**容器即执行域**」——所有 Agent 逻辑跑在 Docker 里，唯一接近"执行命令"的 `TerminalTool` 是 **SSH 到另一个容器**，从架构上就够不到宿主机。
- **Nexent 现状**：`SandboxLevel` 有 LOCAL/DOCKER/WASM 三档，但 LOCAL 只是 `smolagents.LocalPythonExecutor`（AST 级受限 Python 解释器，无 shell 能力）；DOCKER 档是 Jupyter 内核容器，shell 默认 DISABLED。**"控制本机"这条路径上，Nexent 是零**。
- **最值得抄的 4 个设计**：① 能力 seam（Service Definition/Provider/Consumer 三段式）② 文件级沙箱分级 + 被拒后的一次性升级审批 ③ per-call 沙箱策略（策略随调用走，不锁在 provider 上）④ 拒绝是"可报告的事实"而非静默失败。
- **落地建议**：Nexent 短期先做「Desktop/边缘客户端 + 本地执行通道」，不要动 Docker 主架构——两条路线并不冲突，是同一套能力 seam 的两个 provider。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 推荐方案 | 为 Nexent 引入「本地执行 provider」：新客户端形态 + 本机工具通道，沿用现有 MCP 工具接入层 |
| 优先级 | P1（产品差异化关键，但非现有部署形态的 P0 缺陷） |
| 预期影响 | 补齐"控制本机"叙事，与 Claude Code/dsh 同台竞争；对企业部署不产生回归 |
| 资源需求 | 客户端壳 1-2 人月；本地执行通道 + 审批流 2-3 人月 |
| 风险等级 | 中（安全面扩大：本机执行 = 攻击面从容器转移到用户桌面） |

---

## 1. 两边的执行架构对比（先摆事实）

### 1.1 DeepSeek Harness：本机即执行域

```
模型 → tools(bash/pwsh) → ctx.shell → 本机子进程
                                  ↘ ctx.sandbox → OS 级约束
```

| 层 | dsh 做法 | 关键点 |
|---|---|---|
| 执行器 | `bash-local` / `pwsh-local`：`bash -c` / `pwsh -Command` 直接跑在本机 | 每个平台恰好挂一个执行器，挂两个会在加载期报错 |
| 沙箱 | `sandbox-local`：Linux bwrap→Landlock 链、macOS Seatbelt、Windows ACL restricted-token | **同世界约束**：共享宿主内核与文件系统，只是限制文件效果 |
| 模式 | `read-only` / `workspace-write` / `danger-full-access` 三档 | 前两档可送 provider，第三档直接绕过沙箱 |
| 升级 | 被拒 → 模型带 `sandbox_permissions` + `justification` 重试一次 → 审批服务问人 | **窄到宽的梯子**是全局唯一词汇表，bash 和 fs 家族不会漂移 |
| 报告 | enforcement 是 `full`/`partial` 的**事实**，Windows ACL 明说 partial（hard-link、AppContainer 边界） | "拒绝也是事实"，不是静默吞掉 |

**核心机制是"capability seam"三段式**：Service Definition（`ctx.shell`/`ctx.sandbox`）+ Provider（local 各平台）+ Consumer（模型可见的 bash/pwsh 工具）。换一个 provider（比如 SSH 到远程），bash/终端/LSP 跟着走，**消费者不用改**——这就是 dsh 的 `ssh/` 包族做到的事：同一套 fs/subprocess/sandbox 接口，把执行域从本机切到远端。

### 1.2 Nexent：容器即执行域

```
模型 → Agent(smolagents) → python_executor → 容器内 Jupyter 内核
                         ↘ TerminalTool → SSH → nexent-openssh-server 容器
```

| 层 | Nexent 做法 | 关键点 |
|---|---|---|
| 代码执行 | `SandboxLevel.LOCAL` = `smolagents.LocalPythonExecutor`（**AST 受限 Python 解释器**，非 shell）；`DOCKER` = Jupyter 内核容器 | LOCAL 档连 `subprocess`/`os` 调用都在 AST 解析期拦截（`ShellPolicy.DISABLED`） |
| 沙箱 | Docker 容器：内存/CPU 限额、网络禁用、session/system 两种作用域 | 隔离靠"换世界"（容器），不是"约束世界"（同世界沙箱） |
| Terminal 工具 | `TerminalTool` 用 paramiko SSH 连 `nexent-openssh-server` **容器**（deploy profile `terminal`） | 即使启用，命令也只落在容器里，宿主机永远够不到 |
| 部署形态 | 全家桶 12+ 容器：backend/runtime/config/mcp/openssh/elasticsearch/redis/minio/supabase… | 执行域=容器网络内部，与用户本机物理隔离 |

**结论：Nexent 无法控制本机不是功能缺失，是架构选择。** 它的服务端多租户定位（企业部署、租户隔离、RBAC/DAC 权限体系）天然要求执行域收敛在容器内。"控制本机"在这个形态下甚至是**安全反模式**——服务器上一个 Agent 能 SSH 到用户桌面，等于开了远程入侵通道。

## 2. dsh 真正值得抄的 4 个设计

### 2.1 能力 seam：让"本地执行"成为可插拔的一档

dsh 最聪明的地方不是"能控制本机"，而是把"在哪执行"抽象成了 seam。`ssh/` 包族证明了这一点：同一套 `ctx.fs`/`ctx.subprocess`/`ctx.sandbox` 接口，provider 换成 SSH 远端，Bash/PTY/LSP 全部跟着迁移。

**Nexent 对应物**：MCP 工具接入层。Nexent 已经有 `mcp_service.py` 和 Docker socket 管理 MCP 容器——这其实就是雏形。缺的是把"执行类工具"从 Agent 内置工具升级为**带 provider 概力的能力**：同一套工具接口，provider 可以是"Docker 容器"也可以是"本地桌面客户端"。

### 2.2 文件级沙箱 + 升级审批：安全感的来源

dsh 敢让模型跑本机命令，靠的不是胆子大，是这套闭环：

```
workspace-write 被拒 → 报告拒绝事实 + 升级提示
  → 模型重试时带 sandbox_permissions(更宽档) + justification
  → 审批服务弹给用户 → 一次性放行，仅当次调用有效
```

**Nexent 现状**：`backend/permissions/` 有 RBAC/DAC（人→功能权限），但**没有"模型动作→人审批"的工具级确认流**。做本地执行，这个环节不可省。

### 2.3 per-call 策略：策略随调用走

dsh 的 `SandboxPolicy` 是**每次调用携带**的，不是锁在 provider 配置上的：两个消费者可以在同一瞬间以不同策略约束各自的调用，升级重试就是"带更宽策略的一次新调用"。

Nexent 的 `SandboxConfig` 是**每 Agent 一份**（`create_single_agent` 时构建）。如果 Nexent 要做本地执行，建议直接按 per-call 设计，避免日后"Agent 级策略"和"调用级例外"两套并存。

### 2.4 拒绝是可报告的事实

dsh 的拒绝会带结构化标记（`[sandbox: file access denied under <mode> mode]`）+ enforcement 完整度（`full`/`partial`）。模型能理解拒绝原因并决定是放弃还是申请升级。**静默失败是 Agent 系统的大敌**——模型会编造成功。

## 3. Nexent 落地路径建议

### 3.1 不要做的事

- ❌ **不要在服务端形态里加"宿主机执行"**。多租户服务端 + 宿主机执行 = 严重安全漏洞，这是架构红线。
- ❌ **不要把 Docker 沙箱推倒重来**。它对服务端形态是对的，问题只在于"没有另一档"。
- ❌ **不要先做 computer-use（控制屏幕/键盘）**。那是攻击面最大、信任要求最高的一层，先从 CLI 执行层建立用户信任。

### 3.2 建议的路径（三步）

| 阶段 | 做什么 | 对应 dsh 参照 |
|---|---|---|
| **Step 1：桌面客户端形态** | 做一个跑在用户本机的轻客户端（Electron/Tauri），内嵌 Agent runtime，复用 Nexent 的前端与服务端页面 | `apps/desktop`（Electron 包完整 dsh runtime，自带 Node/Python/pnpm，不污染系统） |
| **Step 2：本地执行通道** | 客户端注册"本地执行 provider"：bash/PowerShell 工具 + 文件读写工具，策略默认 `workspace-write` | `shell/` 家族 + `sandbox-local`（Windows 用 ACL restricted-token——用户主战场就是 Windows） |
| **Step 3：审批与升级流** | 工具调用前弹出确认卡（命令内容 + 理由），被拒后允许模型带理由申请更宽权限，一次性有效 | `interaction/user-approval` + sandbox escalation 梯子 |

### 3.3 架构图景（目标状态）

```
服务端部署（现有，不动）：
  用户 → Web → nexent backend → Agent → Docker 沙箱执行     ← 企业/多租户

桌面客户端（新增）：
  用户 → 客户端 UI → 内嵌 Agent → 本地执行 provider
                                    ├─ bash/pwsh（workspace-write 约束）
                                    ├─ 文件读写（限定工作区）
                                    └─ 敏感操作 → 审批弹窗（一次性放行）
                                  ↘ 可选：连回服务端拿知识库/记忆/RAG
```

两条路线共享：同一套 SDK（`nexent` core agents）、同一个工具接口规范、同一个前端组件库。差异只在 provider：服务端挂 Docker provider，客户端挂本地 provider。**这正是 dsh 用 seam 证明可行的结构。**

## 4. 差异化机会（为什么值得做）

| 竞品 | 本机执行 | 形态 |
|---|---|---|
| Claude Code / dsh | ✅ 强（OS 沙箱） | CLI/桌面，单机 |
| Dify | ❌（容器执行） | 服务端平台 |
| Coze/扣子 | ❌（插件沙箱） | SaaS |
| Open Interpreter | ✅（但安全粗放） | 单机脚本 |

**空白点**：没有一个产品同时拥有「服务端多租户 Agent 平台（Nexent 已有）+ 可信本机执行（dsh 有）」。Nexent 若补上客户端形态的本地执行，就是"既能企业部署、又能贴身控制本机"的双形态产品——这在与 Dify 的同质化竞争中是实打实的差异点。

## 5. 风险与前置条件

1. **安全责任转移**：本机执行把安全边界从"运维管容器"移到"用户管桌面"。审批流（3.2 Step 3）必须是 P0，不能后补。
2. **Windows 优先**：用户主战场是 Windows，ACL restricted-token 沙箱是最难啃的部分（dsh 文档自陈 enforcement 是 partial：hard-link、未受限读、AppContainer 边界）。要么接受 partial + 审批兜底，要么初期只开 `read-only` + 白名单命令。
3. **维护两套 provider 的成本**：dsh 用 seam 把这个成本压到"每 provider 一个包"；Nexent 用 MCP 接入层也能做到，但要约束工具接口规范不漂移。
4. **不要复刻 dsh 的全部**：dsh 的 terminal/LSP/PTY/computer-use 是完整开发者工具链，Nexent 不需要全要。最小集 = shell + 文件 + 审批。

---

## ✅ 行动清单

| # | 行动 | 负责方 | 时间窗 |
|---|------|--------|--------|
| 1 | 决策：是否立项桌面客户端形态（含本地执行） | 产品 | 本月 |
| 2 | 若立项：先做技术验证——Windows ACL restricted-token 沙箱 PoC | 工程 | 2 周 |
| 3 | 定义"执行类工具"的 provider 接口规范（对齐现有 MCP 工具层） | 工程 | 1 周 |
| 4 | 设计工具级审批流（命令确认卡 + 一次性升级） | 产品+设计 | 2 周 |
| 5 | 客户端壳选型（Electron vs Tauri）与 runtime 打包方案 | 工程 | 1 周 |

---

## ⚠️ 待确认 / 假设 / Non-goals

- **假设**：分析基于两仓库当前 master/develop 静态走读；Nexent 的 `TerminalTool` 虽导出但未见产品主链路实例化（deploy 里 openssh-server 是独立 profile），判断为"接近可用但未默认开启"。
- **待确认**：Nexent 是否已有桌面客户端规划（本次分析未见相关代码）；产品定位权重（企业服务端 vs 个人效率工具）决定本建议的优先级。
- **Non-goals**：不评估 dsh 的 computer-use/browser-use 细节实现；不建议 Nexent 在服务端形态加宿主机执行；不覆盖 macOS/Linux 沙箱方案细节。

---

## 📚 数据来源 & 成员产出索引

- 主理人（本报告为跨仓库架构走读，未触发多成员工作流）：
  - dsh：`packages/shell/README.md`、`packages/sandbox/README.md`、`docs/subsystems/sandbox.md`（模式/升级/enforcement 事实）、`packages/ssh/README.md`（远端执行同接口证明）、`packages/interaction/README.md`（审批流）、`packages/computer-use/`、`apps/desktop`（客户端形态）
  - Nexent：`sdk/nexent/core/tools/terminal_tool.py`（SSH 到容器）、`sdk/nexent/core/agents/sandbox.py`（SandboxLevel/ShellPolicy/build_python_executor）、`backend/runtime/adapters/nexent/sandbox.py`、`deploy/docker/compose/docker-compose.yml`（openssh-server profile、docker.sock）、`backend/permissions/`（RBAC 无工具级审批）

---

> 本报告由 AI 辅助分析生成，产品立项与安全边界决策请结合业务数据与安全评审审定。
