# 数据分析对话问数 - 方案包实现总结

> 实现日期：2026-07-29
> 方案名称：data_analyst（数据分析对话问数）

---

## 1. 方案概述

业务人员上传 CSV/Excel 文件，用自然语言提问（如"按月份统计销售额"），Agent 自动：
- 读取数据文件
- 编写 Python 脚本（pandas/matplotlib）
- 执行数据清洗、聚合、可视化
- 生成图表 PNG + 自然语言洞察

## 2. 文件清单

| 文件 | 用途 |
|------|------|
| `backend/resources/solutions/data_analyst/solution.json` | 方案清单（name, display_name, type, icon, members, start_agent_id） |
| `backend/resources/solutions/data_analyst/agents/data_analyst.md` | Agent 定义（YAML frontmatter + duty_prompt） |
| `backend/resources/solutions/data_analyst/recipe/variables.json` | Recipe 变量定义（model_name, output_language） |

## 3. Agent 配置

### 工具
| 工具名 | 用途 |
|--------|------|
| `terminal` | SSH 沙箱执行 Python 脚本（pandas/matplotlib/openpyxl） |
| `read_file` | 读取上传的 CSV/Excel 文件内容 |
| `create_file` | 生成分析报告文件 |
| `list_directory` | 列出工作区文件 |

### Recipe 变量
| 变量 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `model_name` | model | 是 | - | 数据分析使用的 LLM 模型 |
| `output_language` | select | 是 | 中文 | 分析结果输出语言（中文/English） |

## 4. 关键设计决策

### start_agent_id 机制
- **问题**：`ai_daily_report` 已占用 `agent_id=1`，`data_analyst` 默认也分配 `agent_id=1`，导致 DB 唯一约束冲突
- **方案**：`solution.json` 新增 `start_agent_id` 字段，parser 支持从指定值起分配 agent_id
- **改动文件**：`backend/services/solution_package_parser.py`（第 212-216 行）
- **设置值**：`start_agent_id: 2` → data_analyst 获得 `agent_id=2`

### 不使用 MCP 连接器
- `terminal` 工具通过 SSH 直连 `nexent-openssh-server` 沙箱容器
- 不需要额外的 MCP 连接器配置
- 用户配置项更少（只需选模型和语言）

## 5. 验证结果

- ✅ Docker 镜像重建成功（nexent/nexent:latest + nexent/nexent-web:latest）
- ✅ Seeder 日志："Seeded official solution 'data_analyst' from data_analyst"
- ✅ 数据库确认：`ag_agent_repository_t` 中存在 agent_id=2, name='data_analyst' 记录
- ✅ 前端 market-v2 页面 HTTP 200
