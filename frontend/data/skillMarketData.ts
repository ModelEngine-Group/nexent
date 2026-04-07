/**
 * Static skill market data
 * Skills are hardcoded and do not persist to database
 */

import { SkillMarketItem, SkillCategory } from "@/types/skillMarket";

export const SKILL_CATEGORIES: SkillCategory[] = [
  {
    id: 9,
    name: "medical",
    display_name: "Medical & Healthcare",
    display_name_zh: "医疗健康",
    description: "Medical diagnosis and healthcare assistance skills",
    description_zh: "医学诊断和健康辅助技能",
    icon: "🏥",
    sort_order: 1,
  },
  {
    id: 1,
    name: "development",
    display_name: "Development",
    display_name_zh: "开发工具",
    description: "Code development and debugging skills",
    description_zh: "代码开发和调试技能",
    icon: "💻",
    sort_order: 2,
  },
  {
    id: 2,
    name: "git",
    display_name: "Git & GitHub",
    display_name_zh: "Git 与 GitHub",
    description: "Version control and collaboration skills",
    description_zh: "版本控制和协作技能",
    icon: "🔀",
    sort_order: 3,
  },
  {
    id: 3,
    name: "documentation",
    display_name: "Documentation",
    display_name_zh: "文档处理",
    description: "Documentation reading and writing skills",
    description_zh: "文档阅读和编写技能",
    icon: "📄",
    sort_order: 4,
  },
  {
    id: 4,
    name: "cloud",
    display_name: "Cloud Services",
    display_name_zh: "云服务",
    description: "Cloud platform integration skills",
    description_zh: "云平台集成技能",
    icon: "☁️",
    sort_order: 5,
  },
  {
    id: 5,
    name: "database",
    display_name: "Database",
    display_name_zh: "数据库",
    description: "Database management and query skills",
    description_zh: "数据库管理和查询技能",
    icon: "🗄️",
    sort_order: 6,
  },
  {
    id: 6,
    name: "security",
    display_name: "Security",
    display_name_zh: "安全工具",
    description: "Security analysis and vulnerability checking",
    description_zh: "安全分析和漏洞检查",
    icon: "🔒",
    sort_order: 7,
  },
  {
    id: 7,
    name: "testing",
    display_name: "Testing",
    display_name_zh: "测试工具",
    description: "Testing and quality assurance skills",
    description_zh: "测试和质量保证技能",
    icon: "🧪",
    sort_order: 8,
  },
  {
    id: 8,
    name: "devops",
    display_name: "DevOps",
    display_name_zh: "运维部署",
    description: "CI/CD and deployment automation",
    description_zh: "持续集成和部署自动化",
    icon: "🚀",
    sort_order: 9,
  },
];

export const STATIC_SKILL_MARKET_DATA: SkillMarketItem[] = [
  {
    id: 1,
    skill_id: "openclaw-ghsa-maintainer",
    name: "GHSA Maintainer",
    display_name: "GitHub 安全公告维护",
    display_name_zh: "GitHub 安全公告维护",
    description: "GitHub 安全公告（GHSA）维护工作流，用于检查、修补、验证和发布仓库安全公告，处理私有分支状态，准备公告 Markdown 或 JSON 内容，处理 GHSA API 特定的发布约束。",
    description_zh: "GitHub 安全公告（GHSA）维护工作流，用于检查、修补、验证和发布仓库安全公告，处理私有分支状态，准备公告 Markdown 或 JSON 内容，处理 GHSA API 特定的发布约束。",
    author: "OpenClaw",
    author_url: "https://github.com/openclaw/openclaw",
    category: SKILL_CATEGORIES[6], // Security
    tags: [
      { id: 1, name: "security", display_name: "安全" },
      { id: 2, name: "github", display_name: "GitHub" },
      { id: 3, name: "maintenance", display_name: "维护" },
    ],
    download_count: 1250,
    is_featured: true,
    content: `## GHSA Maintainer Skill

### 触发条件
当 Codex 需要检查、修补、验证或发布仓库安全公告时激活；验证私有分支状态；准备公告 Markdown 或 JSON 内容；处理 GHSA API 特定的发布约束；确认公告发布成功。

### 工作流程
1. 获取仓库信息并验证安全公告状态
2. 检查现有 GHSA 内容
3. 准备或更新安全公告内容
4. 验证发布前的要求
5. 执行发布操作并确认成功

### 注意事项
- 始终遵循安全公告最佳实践
- 验证所有发布约束条件
- 提供详细的发布报告`,
    content_zh: `## GHSA 维护者技能

### 触发条件
当需要检查、修补、验证或发布仓库安全公告时激活；验证私有分支状态；准备公告 Markdown 或 JSON 内容；处理 GHSA API 特定的发布约束。

### 工作流程
1. 获取仓库信息并验证安全公告状态
2. 检查现有 GHSA 内容
3. 准备或更新安全公告内容
4. 验证发布前的要求
5. 执行发布操作并确认成功

### 注意事项
- 始终遵循安全公告最佳实践
- 验证所有发布约束条件
- 提供详细的发布报告`,
    source_repo: "openclaw/openclaw",
    created_at: "2026-03-19",
    updated_at: "2026-03-19",
  },
  {
    id: 2,
    skill_id: "openclaw-qa-testing",
    name: "QA Testing",
    display_name: "QA 测试执行",
    display_name_zh: "QA 测试执行",
    description: "运行、观察、调试和扩展 OpenClaw QA 测试套件。执行仓库支持的 QA 测试，检查实时 QA 产物，调试失败场景，添加新测试用例，或解释 OpenClaw QA 工作流程。",
    description_zh: "运行、观察、调试和扩展 OpenClaw QA 测试套件。执行仓库支持的 QA 测试，检查实时 QA 产物，调试失败场景，添加新测试用例，或解释 OpenClaw QA 工作流程。",
    author: "OpenClaw",
    author_url: "https://github.com/openclaw/openclaw",
    category: SKILL_CATEGORIES[6], // Security
    tags: [
      { id: 1, name: "testing", display_name: "测试" },
      { id: 2, name: "qa", display_name: "质量保证" },
      { id: 3, name: "debugging", display_name: "调试" },
    ],
    download_count: 2340,
    is_featured: true,
    content: `## QA Testing Skill

### 触发条件
当需要执行仓库支持的 QA 测试套件、检查 QA 产物、调试失败场景、添加新测试场景或解释 OpenClaw QA 工作流程时激活。

### 功能特性
- 运行完整测试套件
- 观察实时测试输出
- 调试失败的测试用例
- 添加新的测试场景
- 生成测试报告

### 推荐配置
- 使用 openai/gpt-5.4 快速模式
- 不使用 gpt-5.4-pro 或 gpt-5.4-mini，除非用户明确覆盖策略`,
    content_zh: `## QA 测试技能

### 触发条件
当需要执行仓库支持的 QA 测试套件、检查 QA 产物、调试失败场景、添加新测试场景或解释 OpenClaw QA 工作流程时激活。

### 功能特性
- 运行完整测试套件
- 观察实时测试输出
- 调试失败的测试用例
- 添加新的测试场景
- 生成测试报告

### 推荐配置
- 使用 openai/gpt-5.4 快速模式
- 不使用 gpt-5.4-pro 或 gpt-5.4-mini，除非用户明确覆盖策略`,
    source_repo: "openclaw/openclaw",
    created_at: "2026-04-06",
    updated_at: "2026-04-06",
  },
  {
    id: 3,
    skill_id: "feishu-doc",
    name: "Feishu Doc",
    display_name: "飞书文档读写",
    display_name_zh: "飞书文档读写",
    description: "飞书云文档的读取和写入操作。当用户提到飞书文档、云文档或 docx 链接时激活。支持创建、编辑、查询和分享飞书文档。",
    description_zh: "飞书云文档的读取和写入操作。当用户提到飞书文档、云文档或 docx 链接时激活。支持创建、编辑、查询和分享飞书文档。",
    author: "OpenClaw",
    author_url: "https://github.com/openclaw/openclaw",
    category: SKILL_CATEGORIES[2], // Documentation
    tags: [
      { id: 1, name: "feishu", display_name: "飞书" },
      { id: 2, name: "document", display_name: "文档" },
      { id: 3, name: "collaboration", display_name: "协作" },
    ],
    download_count: 1890,
    is_featured: true,
    content: `## Feishu Doc Skill

### 触发条件
当用户提到飞书文档、云文档或 docx 链接时激活。

### 支持的操作
- 读取飞书文档内容
- 创建新的飞书文档
- 更新文档内容
- 设置文档权限
- 分享文档链接

### 使用示例
用户：帮我看看这个飞书文档 https://xxx.feishu.cn/docx/xxx
助手：正在读取飞书文档内容...`,
    content_zh: `## 飞书文档技能

### 触发条件
当用户提到飞书文档、云文档或 docx 链接时激活。

### 支持的操作
- 读取飞书文档内容
- 创建新的飞书文档
- 更新文档内容
- 设置文档权限
- 分享文档链接

### 使用示例
用户：帮我看看这个飞书文档 https://xxx.feishu.cn/docx/xxx
助手：正在读取飞书文档内容...`,
    source_repo: "openclaw/openclaw",
    created_at: "2026-02-28",
    updated_at: "2026-02-28",
  },
  {
    id: 4,
    skill_id: "obsidian-vault-maintainer",
    name: "Obsidian Vault",
    display_name: "Obsidian 知识库维护",
    display_name_zh: "Obsidian 知识库维护",
    description: "维护 Obsidian 友好的记忆维基知识库，支持 wikilinks、正向链接和 Obsidian CLI 功能。用于创建和管理个人知识库，支持双向链接和标签管理。",
    description_zh: "维护 Obsidian 友好的记忆维基知识库，支持 wikilinks、正向链接和 Obsidian CLI 功能。用于创建和管理个人知识库，支持双向链接和标签管理。",
    author: "OpenClaw",
    author_url: "https://github.com/openclaw/openclaw",
    category: SKILL_CATEGORIES[2], // Documentation
    tags: [
      { id: 1, name: "knowledge-base", display_name: "知识库" },
      { id: 2, name: "obsidian", display_name: "Obsidian" },
      { id: 3, name: "note-taking", display_name: "笔记" },
    ],
    download_count: 1560,
    is_featured: false,
    content: `## Obsidian Vault Maintainer Skill

### 触发条件
当需要管理 Obsidian 知识库、创建笔记、设置双向链接或使用 Obsidian CLI 时激活。

### 功能特性
- 创建和管理笔记
- 维护 wikilinks 和正向链接
- 管理 frontmatter 元数据
- 使用 Obsidian CLI
- 生成知识图谱`,
    content_zh: `## Obsidian 知识库维护技能

### 触发条件
当需要管理 Obsidian 知识库、创建笔记、设置双向链接或使用 Obsidian CLI 时激活。

### 功能特性
- 创建和管理笔记
- 维护 wikilinks 和正向链接
- 管理 frontmatter 元数据
- 使用 Obsidian CLI
- 生成知识图谱`,
    source_repo: "openclaw/openclaw",
    created_at: "2026-04-06",
    updated_at: "2026-04-06",
  },
  {
    id: 5,
    skill_id: "openclaw-parallels-smoke",
    name: "Parallels Smoke",
    display_name: "Parallels 虚拟机测试",
    display_name_zh: "Parallels 虚拟机测试",
    description: "跨 macOS、Windows 和 Linux 的 Parallels 端到端冒烟测试、升级和重运行工作流。用于运行、重新运行、调试虚拟机安装、入职、网关冒烟测试。",
    description_zh: "跨 macOS、Windows 和 Linux 的 Parallels 端到端冒烟测试、升级和重运行工作流。用于运行、重新运行、调试虚拟机安装、入职、网关冒烟测试。",
    author: "OpenClaw",
    author_url: "https://github.com/openclaw/openclaw",
    category: SKILL_CATEGORIES[6], // Security
    tags: [
      { id: 1, name: "virtualization", display_name: "虚拟化" },
      { id: 2, name: "testing", display_name: "测试" },
      { id: 3, name: "parallels", display_name: "Parallels" },
    ],
    download_count: 890,
    is_featured: false,
    content: `## Parallels Smoke Testing Skill

### 触发条件
当需要运行、重新运行、调试虚拟机安装、入职、网关冒烟测试、最新版本升级检查或 Discord 往返验证时激活。

### 支持的平台
- macOS
- Windows
- Linux

### 工作流程
1. 准备测试环境
2. 执行冒烟测试
3. 收集测试结果
4. 生成测试报告`,
    content_zh: `## Parallels 冒烟测试技能

### 触发条件
当需要运行、重新运行、调试虚拟机安装、入职、网关冒烟测试、最新版本升级检查或 Discord 往返验证时激活。

### 支持的平台
- macOS
- Windows
- Linux

### 工作流程
1. 准备测试环境
2. 执行冒烟测试
3. 收集测试结果
4. 生成测试报告`,
    source_repo: "openclaw/openclaw",
    created_at: "2026-04-06",
    updated_at: "2026-04-06",
  },
  {
    id: 6,
    skill_id: "openclaw-release-maintainer",
    name: "Release Maintainer",
    display_name: "版本发布维护",
    display_name_zh: "版本发布维护",
    description: "OpenClaw 发布、预发布、变更日志发布说明和维护者验证工作流。用于准备或验证稳定版或测试版发布步骤，对齐版本命名，组装发布说明。",
    description_zh: "OpenClaw 发布、预发布、变更日志发布说明和维护者验证工作流。用于准备或验证稳定版或测试版发布步骤，对齐版本命名，组装发布说明。",
    author: "OpenClaw",
    author_url: "https://github.com/openclaw/openclaw",
    category: SKILL_CATEGORIES[8], // DevOps
    tags: [
      { id: 1, name: "release", display_name: "发布" },
      { id: 2, name: "changelog", display_name: "变更日志" },
      { id: 3, name: "devops", display_name: "运维" },
    ],
    download_count: 1680,
    is_featured: false,
    content: `## Release Maintainer Skill

### 触发条件
当需要准备或验证稳定版或测试版发布步骤、对齐版本命名、组装发布说明、检查发布授权要求或验证发布命令时激活。

### 发布类型
- 稳定版 (Stable)
- 测试版 (Beta)
- 预发布 (Pre-release)

### 工作流程
1. 验证版本命名规范
2. 组装变更日志
3. 检查发布授权
4. 执行发布命令
5. 验证发布产物`,
    content_zh: `## 版本发布维护技能

### 触发条件
当需要准备或验证稳定版或测试版发布步骤、对齐版本命名、组装发布说明、检查发布授权要求或验证发布命令时激活。

### 发布类型
- 稳定版 (Stable)
- 测试版 (Beta)
- 预发布 (Pre-release)

### 工作流程
1. 验证版本命名规范
2. 组装变更日志
3. 检查发布授权
4. 执行发布命令
5. 验证发布产物`,
    source_repo: "openclaw/openclaw",
    created_at: "2026-04-02",
    updated_at: "2026-04-02",
  },
  {
    id: 7,
    skill_id: "diffs",
    name: "Diffs Viewer",
    display_name: "代码差异查看",
    display_name_zh: "代码差异查看",
    description: "使用 diffs 工具生成真实可分享的代码差异视图，支持查看器 URL、文件产物或两者同时提供。替代手动编辑摘要。",
    description_zh: "使用 diffs 工具生成真实可分享的代码差异视图，支持查看器 URL、文件产物或两者同时提供。替代手动编辑摘要。",
    author: "OpenClaw",
    author_url: "https://github.com/openclaw/openclaw",
    category: SKILL_CATEGORIES[1], // Development
    tags: [
      { id: 1, name: "diff", display_name: "差异" },
      { id: 2, name: "code-review", display_name: "代码审查" },
      { id: 3, name: "sharing", display_name: "分享" },
    ],
    download_count: 2150,
    is_featured: false,
    content: `## Diffs Viewer Skill

### 触发条件
当需要查看代码差异、生成可分享的代码变更链接或需要代码审查时激活。

### 功能特性
- 生成可分享的差异链接
- 支持 side-by-side 视图
- 支持 unified 视图
- 高亮语法显示
- 支持评论和标注`,
    content_zh: `## 差异查看器技能

### 触发条件
当需要查看代码差异、生成可分享的代码变更链接或需要代码审查时激活。

### 功能特性
- 生成可分享的差异链接
- 支持 side-by-side 视图
- 支持 unified 视图
- 高亮语法显示
- 支持评论和标注`,
    source_repo: "openclaw/openclaw",
    created_at: "2026-04-02",
    updated_at: "2026-04-02",
  },
  {
    id: 8,
    skill_id: "feishu-perm",
    name: "Feishu Permissions",
    display_name: "飞书权限管理",
    display_name_zh: "飞书权限管理",
    description: "飞书文档和文件的权限管理。当用户提到分享、协作者、权限设置时激活。支持设置文档可见范围、管理访问权限。",
    description_zh: "飞书文档和文件的权限管理。当用户提到分享、协作者、权限设置时激活。支持设置文档可见范围、管理访问权限。",
    author: "OpenClaw",
    author_url: "https://github.com/openclaw/openclaw",
    category: SKILL_CATEGORIES[2], // Documentation
    tags: [
      { id: 1, name: "feishu", display_name: "飞书" },
      { id: 2, name: "permissions", display_name: "权限" },
      { id: 3, name: "collaboration", display_name: "协作" },
    ],
    download_count: 1340,
    is_featured: false,
    content: `## Feishu Permissions Skill

### 触发条件
当用户提到分享、协作者、权限设置时激活。

### 支持的操作
- 设置文档访问权限
- 管理协作者列表
- 配置可见范围
- 设置编辑权限
- 批量权限管理`,
    content_zh: `## 飞书权限管理技能

### 触发条件
当用户提到分享、协作者、权限设置时激活。

### 支持的操作
- 设置文档访问权限
- 管理协作者列表
- 配置可见范围
- 设置编辑权限
- 批量权限管理`,
    source_repo: "openclaw/openclaw",
    created_at: "2026-02-06",
    updated_at: "2026-02-06",
  },
  {
    id: 9,
    skill_id: "openclaw-pr-maintainer",
    name: "PR Maintainer",
    display_name: "PR 维护工作流",
    display_name_zh: "PR 维护工作流",
    description: "审查、整理、准备、关闭或合并 OpenClaw 拉取请求及相关问题的维护者工作流。用于验证 bug 修复声明、搜索相关问题或 PR。",
    description_zh: "审查、整理、准备、关闭或合并 OpenClaw 拉取请求及相关问题的维护者工作流。用于验证 bug 修复声明、搜索相关问题或 PR。",
    author: "OpenClaw",
    author_url: "https://github.com/openclaw/openclaw",
    category: SKILL_CATEGORIES[2], // Git & GitHub
    tags: [
      { id: 1, name: "pull-request", display_name: "拉取请求" },
      { id: 2, name: "code-review", display_name: "代码审查" },
      { id: 3, name: "github", display_name: "GitHub" },
    ],
    download_count: 1920,
    is_featured: false,
    content: `## PR Maintainer Skill

### 触发条件
当需要验证 bug 修复声明、搜索相关问题或 PR、应用或推荐关闭/原因标签、准备 GitHub 评论、检查审查线程跟进或执行维护者风格的 PR 决策时激活。

### 工作流程
1. 审查 PR 内容
2. 验证修复声明
3. 检查相关问题
4. 应用标签
5. 生成审查报告`,
    content_zh: `## PR 维护工作流技能

### 触发条件
当需要验证 bug 修复声明、搜索相关问题或 PR、应用或推荐关闭/原因标签、准备 GitHub 评论、检查审查线程跟进或执行维护者风格的 PR 决策时激活。

### 工作流程
1. 审查 PR 内容
2. 验证修复声明
3. 检查相关问题
4. 应用标签
5. 生成审查报告`,
    source_repo: "openclaw/openclaw",
    created_at: "2026-03-19",
    updated_at: "2026-03-19",
  },
  {
    id: 10,
    skill_id: "acp-router",
    name: "ACP Router",
    display_name: "ACP 请求路由",
    display_name_zh: "ACP 请求路由",
    description: "将自然语言请求路由到 OpenClaw ACP 运行时会话或直接 acpx 驱动的会话。支持 Pi、Claude Code、Codex、Cursor、Copilot 等多种 AI 代理。",
    description_zh: "将自然语言请求路由到 OpenClaw ACP 运行时会话或直接 acpx 驱动的会话。支持 Pi、Claude Code、Codex、Cursor、Copilot 等多种 AI 代理。",
    author: "OpenClaw",
    author_url: "https://github.com/openclaw/openclaw",
    category: SKILL_CATEGORIES[1], // Development
    tags: [
      { id: 1, name: "routing", display_name: "路由" },
      { id: 2, name: "multi-agent", display_name: "多代理" },
      { id: 3, name: "integration", display_name: "集成" },
    ],
    download_count: 2450,
    is_featured: false,
    content: `## ACP Router Skill

### 触发条件
当需要将请求路由到特定 AI 代理或执行多代理协作任务时激活。

### 支持的代理
- Pi
- Claude Code
- Codex
- Cursor
- Copilot
- ACP harness

### 工作流程
1. 解析请求意图
2. 选择合适的代理
3. 路由到目标会话
4. 收集并整合结果`,
    content_zh: `## ACP 路由技能

### 触发条件
当需要将请求路由到特定 AI 代理或执行多代理协作任务时激活。

### 支持的代理
- Pi
- Claude Code
- Codex
- Cursor
- Copilot
- ACP harness

### 工作流程
1. 解析请求意图
2. 选择合适的代理
3. 路由到目标会话
4. 收集并整合结果`,
    source_repo: "openclaw/openclaw",
    created_at: "2026-03-29",
    updated_at: "2026-03-29",
  },
  {
    id: 11,
    skill_id: "feishu-drive",
    name: "Feishu Drive",
    display_name: "飞书云盘管理",
    display_name_zh: "飞书云盘管理",
    description: "飞书云盘文件管理。当用户提到云空间、文件夹、云盘时激活。支持文件上传、下载、移动、分享和权限管理。",
    description_zh: "飞书云盘文件管理。当用户提到云空间、文件夹、云盘时激活。支持文件上传、下载、移动、分享和权限管理。",
    author: "OpenClaw",
    author_url: "https://github.com/openclaw/openclaw",
    category: SKILL_CATEGORIES[4], // Cloud Services
    tags: [
      { id: 1, name: "feishu", display_name: "飞书" },
      { id: 2, name: "cloud-storage", display_name: "云存储" },
      { id: 3, name: "file-management", display_name: "文件管理" },
    ],
    download_count: 1180,
    is_featured: false,
    content: `## Feishu Drive Skill

### 触发条件
当用户提到云空间、文件夹、云盘时激活。

### 支持的操作
- 浏览云盘文件
- 上传和下载文件
- 创建和管理文件夹
- 分享文件和链接
- 设置文件权限`,
    content_zh: `## 飞书云盘技能

### 触发条件
当用户提到云空间、文件夹、云盘时激活。

### 支持的操作
- 浏览云盘文件
- 上传和下载文件
- 创建和管理文件夹
- 分享文件和链接
- 设置文件权限`,
    source_repo: "openclaw/openclaw",
    created_at: "2026-02-06",
    updated_at: "2026-02-06",
  },
  {
    id: 12,
    skill_id: "feishu-wiki",
    name: "Feishu Wiki",
    display_name: "飞书知识库导航",
    display_name_zh: "飞书知识库导航",
    description: "飞书知识库导航。当用户提到知识库、百科或知识库链接时激活。支持知识库浏览、文档检索和知识图谱展示。",
    description_zh: "飞书知识库导航。当用户提到知识库、百科或知识库链接时激活。支持知识库浏览、文档检索和知识图谱展示。",
    author: "OpenClaw",
    author_url: "https://github.com/openclaw/openclaw",
    category: SKILL_CATEGORIES[2], // Documentation
    tags: [
      { id: 1, name: "feishu", display_name: "飞书" },
      { id: 2, name: "wiki", display_name: "知识库" },
      { id: 3, name: "knowledge-graph", display_name: "知识图谱" },
    ],
    download_count: 1420,
    is_featured: false,
    content: `## Feishu Wiki Skill

### 触发条件
当用户提到知识库、百科或知识库链接时激活。

### 功能特性
- 浏览知识库结构
- 检索知识库文档
- 展示知识图谱
- 管理知识节点
- 链接相关文档`,
    content_zh: `## 飞书知识库技能

### 触发条件
当用户提到知识库、百科或知识库链接时激活。

### 功能特性
- 浏览知识库结构
- 检索知识库文档
- 展示知识图谱
- 管理知识节点
- 链接相关文档`,
    source_repo: "openclaw/openclaw",
    created_at: "2026-02-06",
    updated_at: "2026-02-06",
  },
  // ================ Medical & Healthcare Skills ================
  {
    id: 13,
    skill_id: "medical-history-analysis",
    name: "Medical History Analysis",
    display_name: "病史分析与解读",
    display_name_zh: "病史分析与解读",
    description: "病史采集与分析技能，能够系统地收集、整理和分析患者的病史信息。包括主诉、现病史、既往史、家族史等，帮助生成结构化的病史摘要，支持临床诊断决策。",
    description_zh: "病史采集与分析技能，能够系统地收集、整理和分析患者的病史信息。包括主诉、现病史、既往史、家族史等，帮助生成结构化的病史摘要，支持临床诊断决策。",
    author: "Nexent Medical",
    author_url: "https://github.com/nexent-medical",
    category: SKILL_CATEGORIES[0], // Medical
    tags: [
      { id: 1, name: "medical-history", display_name: "病史" },
      { id: 2, name: "clinical", display_name: "临床" },
      { id: 3, name: "diagnosis", display_name: "诊断" },
    ],
    download_count: 3560,
    is_featured: true,
    content: `## Medical History Analysis Skill

### 触发条件
当需要收集、分析患者病史，或需要生成结构化病史摘要时激活。

### 功能特性
- 系统采集病史信息
- 生成结构化病史摘要
- 识别关键临床信息
- 支持鉴别诊断

### 病史采集要点
1. 主诉（Chief Complaint）
2. 现病史（History of Present Illness）
3. 既往史（Past Medical History）
4. 家族史（Family History）
5. 社会史（Social History）
6. 用药史（Medication History）
7. 过敏史（Allergy History）

### 输出格式
生成标准化的病史摘要，包含所有关键临床信息。`,
    content_zh: `## 病史分析与解读技能

### 触发条件
当需要收集、分析患者病史，或需要生成结构化病史摘要时激活。

### 功能特性
- 系统采集病史信息
- 生成结构化病史摘要
- 识别关键临床信息
- 支持鉴别诊断

### 病史采集要点
1. 主诉（Chief Complaint）
2. 现病史（History of Present Illness）
3. 既往史（Past Medical History）
4. 家族史（Family History）
5. 社会史（Social History）
6. 用药史（Medication History）
7. 过敏史（Allergy History）

### 输出格式
生成标准化的病史摘要，包含所有关键临床信息。`,
    source_repo: "nexent/nexent-medical",
    created_at: "2026-01-15",
    updated_at: "2026-03-20",
  },
  {
    id: 14,
    skill_id: "drug-interaction-check",
    name: "Drug Interaction Check",
    display_name: "药物相互作用检查",
    display_name_zh: "药物相互作用检查",
    description: "药物相互作用检测技能，能够分析多种药物同时使用时的潜在相互作用。包括药物-药物相互作用、药物-食物相互作用、禁忌症检查，支持临床用药安全决策。",
    description_zh: "药物相互作用检测技能，能够分析多种药物同时使用时的潜在相互作用。包括药物-药物相互作用、药物-食物相互作用、禁忌症检查，支持临床用药安全决策。",
    author: "Nexent Medical",
    author_url: "https://github.com/nexent-medical",
    category: SKILL_CATEGORIES[0], // Medical
    tags: [
      { id: 1, name: "pharmacology", display_name: "药理学" },
      { id: 2, name: "drug-safety", display_name: "用药安全" },
      { id: 3, name: "interaction", display_name: "相互作用" },
    ],
    download_count: 2890,
    is_featured: true,
    content: `## Drug Interaction Check Skill

### 触发条件
当需要检查药物相互作用、审核用药方案、或识别潜在用药风险时激活。

### 功能特性
- 药物-药物相互作用分析
- 药物-食物相互作用检查
- 禁忌症识别
- 用药剂量审核
- 不良反应风险评估

### 使用场景
- 门诊处方审核
- 住院患者用药方案调整
- 药物重整（Medication Reconciliation）
- 患者用药教育`,
    content_zh: `## 药物相互作用检查技能

### 触发条件
当需要检查药物相互作用、审核用药方案、或识别潜在用药风险时激活。

### 功能特性
- 药物-药物相互作用分析
- 药物-食物相互作用检查
- 禁忌症识别
- 用药剂量审核
- 不良反应风险评估

### 使用场景
- 门诊处方审核
- 住院患者用药方案调整
- 药物重整（Medication Reconciliation）
- 患者用药教育`,
    source_repo: "nexent/nexent-medical",
    created_at: "2026-01-20",
    updated_at: "2026-03-15",
  },
  {
    id: 15,
    skill_id: "clinical-note-generator",
    name: "Clinical Note Generator",
    display_name: "临床病历生成",
    display_name_zh: "临床病历生成",
    description: "临床病历智能生成技能，能够根据对话和检查结果自动生成规范的门诊病历、住院病程记录、出院小结等医疗文档。符合病历书写规范，支持多种格式输出。",
    description_zh: "临床病历智能生成技能，能够根据对话和检查结果自动生成规范的门诊病历、住院病程记录、出院小结等医疗文档。符合病历书写规范，支持多种格式输出。",
    author: "Nexent Medical",
    author_url: "https://github.com/nexent-medical",
    category: SKILL_CATEGORIES[0], // Medical
    tags: [
      { id: 1, name: "medical-record", display_name: "病历" },
      { id: 2, name: "documentation", display_name: "文档" },
      { id: 3, name: "ehr", display_name: "电子病历" },
    ],
    download_count: 4120,
    is_featured: true,
    content: `## Clinical Note Generator Skill

### 触发条件
当需要生成门诊病历、住院记录、出院小结等临床文档时激活。

### 支持的文档类型
- 门诊病历（OPD Note）
- 入院记录（Admission Note）
- 病程记录（Progress Note）
- 出院小结（Discharge Summary）
- 手术记录（Operative Note）
- 会诊记录（Consultation Note）

### 功能特性
- 符合病历书写规范
- 结构化信息提取
- 医学术语标准化（SNOMED CT / ICD编码）
- 多语言支持`,
    content_zh: `## 临床病历生成技能

### 触发条件
当需要生成门诊病历、住院记录、出院小结等临床文档时激活。

### 支持的文档类型
- 门诊病历（OPD Note）
- 入院记录（Admission Note）
- 病程记录（Progress Note）
- 出院小结（Discharge Summary）
- 手术记录（Operative Note）
- 会诊记录（Consultation Note）

### 功能特性
- 符合病历书写规范
- 结构化信息提取
- 医学术语标准化（SNOMED CT / ICD编码）
- 多语言支持`,
    source_repo: "nexent/nexent-medical",
    created_at: "2026-02-01",
    updated_at: "2026-03-25",
  },
  {
    id: 16,
    skill_id: "lab-result-interpretation",
    name: "Lab Result Interpretation",
    display_name: "检验报告解读",
    display_name_zh: "检验报告解读",
    description: "实验室检查结果解读技能，能够分析血液、尿液、生化、免疫等各类检验报告。识别异常值，关联临床意义，辅助诊断决策。",
    description_zh: "实验室检查结果解读技能，能够分析血液、尿液、生化、免疫等各类检验报告。识别异常值，关联临床意义，辅助诊断决策。",
    author: "Nexent Medical",
    author_url: "https://github.com/nexent-medical",
    category: SKILL_CATEGORIES[0], // Medical
    tags: [
      { id: 1, name: "laboratory", display_name: "检验" },
      { id: 2, name: "blood-test", display_name: "血液检查" },
      { id: 3, name: "biochemistry", display_name: "生化" },
    ],
    download_count: 3340,
    is_featured: false,
    content: `## Lab Result Interpretation Skill

### 触发条件
当需要解读检验报告、分析异常值、或关联检验结果与临床诊断时激活。

### 支持的检验类型
- 血常规（Complete Blood Count）
- 尿常规（Urinalysis）
- 生化检查（Biochemistry）
- 免疫检查（Immunology）
- 肿瘤标志物（Tumor Markers）
- 感染指标（Infectious Disease Markers）

### 功能特性
- 异常值自动标记
- 参考范围对比
- 临床意义解释
- 鉴别诊断建议`,
    content_zh: `## 检验报告解读技能

### 触发条件
当需要解读检验报告、分析异常值、或关联检验结果与临床诊断时激活。

### 支持的检验类型
- 血常规（Complete Blood Count）
- 尿常规（Urinalysis）
- 生化检查（Biochemistry）
- 免疫检查（Immunology）
- 肿瘤标志物（Tumor Markers）
- 感染指标（Infectious Disease Markers）

### 功能特性
- 异常值自动标记
- 参考范围对比
- 临床意义解释
- 鉴别诊断建议`,
    source_repo: "nexent/nexent-medical",
    created_at: "2026-02-10",
    updated_at: "2026-03-18",
  },
  {
    id: 17,
    skill_id: "imaging-analysis-assist",
    name: "Imaging Analysis Assist",
    display_name: "影像检查辅助分析",
    display_name_zh: "影像检查辅助分析",
    description: "医学影像检查辅助分析技能，支持 X 光、CT、MRI、超声等影像的描述性分析。帮助识别影像学特征，生成标准化影像报告，支持影像科与临床科室沟通。",
    description_zh: "医学影像检查辅助分析技能，支持 X 光、CT、MRI、超声等影像的描述性分析。帮助识别影像学特征，生成标准化影像报告，支持影像科与临床科室沟通。",
    author: "Nexent Medical",
    author_url: "https://github.com/nexent-medical",
    category: SKILL_CATEGORIES[0], // Medical
    tags: [
      { id: 1, name: "imaging", display_name: "影像" },
      { id: 2, name: "radiology", display_name: "放射科" },
      { id: 3, name: "xray", display_name: "X光" },
    ],
    download_count: 2780,
    is_featured: false,
    content: `## Imaging Analysis Assist Skill

### 触发条件
当需要分析医学影像、生成影像描述、或撰写影像报告时激活。

### 支持的影像类型
- X线（X-Ray）
- 计算机断层扫描（CT）
- 磁共振成像（MRI）
- 超声检查（Ultrasound）
- 乳腺钼靶（Mammography）

### 功能特性
- 影像学特征描述
- 标准化报告模板
- 术语规范化
- 影像-临床关联分析`,
    content_zh: `## 影像检查辅助分析技能

### 触发条件
当需要分析医学影像、生成影像描述、或撰写影像报告时激活。

### 支持的影像类型
- X线（X-Ray）
- 计算机断层扫描（CT）
- 磁共振成像（MRI）
- 超声检查（Ultrasound）
- 乳腺钼靶（Mammography）

### 功能特性
- 影像学特征描述
- 标准化报告模板
- 术语规范化
- 影像-临床关联分析`,
    source_repo: "nexent/nexent-medical",
    created_at: "2026-02-15",
    updated_at: "2026-03-22",
  },
  {
    id: 18,
    skill_id: "differential-diagnosis",
    name: "Differential Diagnosis",
    display_name: "鉴别诊断分析",
    display_name_zh: "鉴别诊断分析",
    description: "鉴别诊断辅助分析技能，基于患者的症状、体征和检查结果，系统地列出可能的诊断，进行鉴别分析，推荐进一步检查，帮助医生缩小诊断范围。",
    description_zh: "鉴别诊断辅助分析技能，基于患者的症状、体征和检查结果，系统地列出可能的诊断，进行鉴别分析，推荐进一步检查，帮助医生缩小诊断范围。",
    author: "Nexent Medical",
    author_url: "https://github.com/nexent-medical",
    category: SKILL_CATEGORIES[0], // Medical
    tags: [
      { id: 1, name: "diagnosis", display_name: "诊断" },
      { id: 2, name: "reasoning", display_name: "推理" },
      { id: 3, name: "clinical", display_name: "临床" },
    ],
    download_count: 4560,
    is_featured: true,
    content: `## Differential Diagnosis Skill

### 触发条件
当需要进行鉴别诊断、列出可能的诊断、或需要诊断决策支持时激活。

### 工作流程
1. 收集患者信息（症状、体征、检查结果）
2. 生成候选诊断列表
3. 按可能性排序
4. 分析鉴别要点
5. 推荐进一步检查
6. 提供诊断建议

### 功能特性
- 基于临床证据的诊断推理
- 罕见病识别提示
- 检查项目推荐
- 诊断路径建议`,
    content_zh: `## 鉴别诊断分析技能

### 触发条件
当需要进行鉴别诊断、列出可能的诊断、或需要诊断决策支持时激活。

### 工作流程
1. 收集患者信息（症状、体征、检查结果）
2. 生成候选诊断列表
3. 按可能性排序
4. 分析鉴别要点
5. 推荐进一步检查
6. 提供诊断建议

### 功能特性
- 基于临床证据的诊断推理
- 罕见病识别提示
- 检查项目推荐
- 诊断路径建议`,
    source_repo: "nexent/nexent-medical",
    created_at: "2026-02-20",
    updated_at: "2026-03-28",
  },
  {
    id: 19,
    skill_id: "patient-education",
    name: "Patient Education",
    display_name: "患者健康教育",
    display_name_zh: "患者健康教育",
    description: "患者健康教育技能，能够用通俗易懂的语言向患者解释疾病、治疗方案、用药说明和健康指导。支持多种语言和不同文化背景的患者教育需求。",
    description_zh: "患者健康教育技能，能够用通俗易懂的语言向患者解释疾病、治疗方案、用药说明和健康指导。支持多种语言和不同文化背景的患者教育需求。",
    author: "Nexent Medical",
    author_url: "https://github.com/nexent-medical",
    category: SKILL_CATEGORIES[0], // Medical
    tags: [
      { id: 1, name: "education", display_name: "教育" },
      { id: 2, name: "patient", display_name: "患者" },
      { id: 3, name: "health", display_name: "健康" },
    ],
    download_count: 2150,
    is_featured: false,
    content: `## Patient Education Skill

### 触发条件
当需要向患者解释疾病、提供健康指导、进行用药教育时激活。

### 支持的内容类型
- 疾病科普（Disease Explanation）
- 用药指导（Medication Instructions）
- 检查说明（Procedure Information）
- 术前宣教（Pre-op Education）
- 出院指导（Discharge Instructions）
- 健康生活方式（Health Lifestyle）

### 功能特性
- 通俗易懂的语言表达
- 医学术语解释
- 视觉辅助材料建议
- 文化敏感性适配`,
    content_zh: `## 患者健康教育技能

### 触发条件
当需要向患者解释疾病、提供健康指导、进行用药教育时激活。

### 支持的内容类型
- 疾病科普（Disease Explanation）
- 用药指导（Medication Instructions）
- 检查说明（Procedure Information）
- 术前宣教（Pre-op Education）
- 出院指导（Discharge Instructions）
- 健康生活方式（Health Lifestyle）

### 功能特性
- 通俗易懂的语言表达
- 医学术语解释
- 视觉辅助材料建议
- 文化敏感性适配`,
    source_repo: "nexent/nexent-medical",
    created_at: "2026-03-01",
    updated_at: "2026-03-26",
  },
  {
    id: 20,
    skill_id: "triage-assessment",
    name: "Triage Assessment",
    display_name: "分诊评估",
    display_name_zh: "分诊评估",
    description: "智能分诊评估技能，能够根据患者的症状和生命体征进行初步评估，判断病情紧急程度，推荐就诊科室，支持急诊和门诊分诊决策。",
    description_zh: "智能分诊评估技能，能够根据患者的症状和生命体征进行初步评估，判断病情紧急程度，推荐就诊科室，支持急诊和门诊分诊决策。",
    author: "Nexent Medical",
    author_url: "https://github.com/nexent-medical",
    category: SKILL_CATEGORIES[0], // Medical
    tags: [
      { id: 1, name: "triage", display_name: "分诊" },
      { id: 2, name: "emergency", display_name: "急诊" },
      { id: 3, name: "assessment", display_name: "评估" },
    ],
    download_count: 3230,
    is_featured: false,
    content: `## Triage Assessment Skill

### 触发条件
当需要进行分诊评估、判断病情紧急程度、或推荐就诊科室时激活。

### 紧急程度分级
- 一级（危急）：立即危及生命，需立即抢救
- 二级（紧急）：潜在危及生命，需尽快处理
- 三级（急迫）：需要尽快评估，可能需要等候
- 四级（不紧急）：可以等待，常规处理
- 五级（非紧急）：可延期处理或自我护理

### 功能特性
- 症状评估
- 生命体征分析
- 紧急程度判断
- 就诊科室推荐
- 等候时间预估`,
    content_zh: `## 分诊评估技能

### 触发条件
当需要进行分诊评估、判断病情紧急程度、或推荐就诊科室时激活。

### 紧急程度分级
- 一级（危急）：立即危及生命，需立即抢救
- 二级（紧急）：潜在危及生命，需尽快处理
- 三级（急迫）：需要尽快评估，可能需要等候
- 四级（不紧急）：可以等待，常规处理
- 五级（非紧急）：可延期处理或自我护理

### 功能特性
- 症状评估
- 生命体征分析
- 紧急程度判断
- 就诊科室推荐
- 等候时间预估`,
    source_repo: "nexent/nexent-medical",
    created_at: "2026-03-05",
    updated_at: "2026-03-27",
  },
];

/**
 * Get skill by ID
 */
export function getSkillById(skillId: string): SkillMarketItem | undefined {
  return STATIC_SKILL_MARKET_DATA.find((skill) => skill.skill_id === skillId);
}

/**
 * Get skills by category
 */
export function getSkillsByCategory(categoryName: string): SkillMarketItem[] {
  if (categoryName === "all") {
    // Sort: medical skills first, then by download count
    return [...STATIC_SKILL_MARKET_DATA].sort((a, b) => {
      const aIsMedical = a.category.name === "medical";
      const bIsMedical = b.category.name === "medical";
      if (aIsMedical && !bIsMedical) return -1;
      if (!aIsMedical && bIsMedical) return 1;
      return b.download_count - a.download_count;
    });
  }
  return STATIC_SKILL_MARKET_DATA.filter(
    (skill) => skill.category.name === categoryName
  );
}

/**
 * Search skills by keyword
 */
export function searchSkills(keyword: string): SkillMarketItem[] {
  const lowerKeyword = keyword.toLowerCase();
  return STATIC_SKILL_MARKET_DATA.filter(
    (skill) =>
      skill.display_name.toLowerCase().includes(lowerKeyword) ||
      skill.display_name_zh.includes(keyword) ||
      skill.description.toLowerCase().includes(lowerKeyword) ||
      skill.description_zh.includes(keyword) ||
      skill.author.toLowerCase().includes(lowerKeyword) ||
      skill.tags.some((tag) => tag.display_name.includes(keyword))
  );
}
