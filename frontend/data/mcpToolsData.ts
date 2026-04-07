/**
 * Static MCP Tools market data
 * MCP tools are hardcoded and do not persist to database
 * Data sourced from https://mcpmarket.com/zh/leaderboards
 */

import { McpToolsItem, McpToolsCategory } from "@/types/mcpTools";

export const MCP_TOOLS_CATEGORIES: McpToolsCategory[] = [
  {
    id: 9,
    name: "medical_healthcare",
    display_name: "Medical & Healthcare",
    display_name_zh: "医疗健康",
    description: "MCP tools for medical diagnosis, health data, and healthcare assistance",
    description_zh: "医学诊断、健康数据和医疗辅助 MCP 工具",
    icon: "🏥",
    sort_order: 1,
  },
  {
    id: 1,
    name: "developer_tools",
    display_name: "Developer Tools",
    display_name_zh: "开发者工具",
    description: "Tools for AI coding agents and software development",
    description_zh: "AI编码智能体和软件开发工具",
    icon: "🔧",
    sort_order: 2,
  },
  {
    id: 2,
    name: "api_development",
    display_name: "API Development",
    display_name_zh: "API 开发",
    description: "Tools for building and integrating APIs",
    description_zh: "API 构建和集成工具",
    icon: "🔌",
    sort_order: 3,
  },
  {
    id: 3,
    name: "database_management",
    display_name: "Database Management",
    display_name_zh: "数据库管理",
    description: "Tools for database operations and management",
    description_zh: "数据库操作和管理工具",
    icon: "🗄️",
    sort_order: 4,
  },
  {
    id: 4,
    name: "browser_automation",
    display_name: "Browser Automation",
    display_name_zh: "浏览器自动化",
    description: "Tools for browser control and web automation",
    description_zh: "浏览器控制和网页自动化工具",
    icon: "🌐",
    sort_order: 5,
  },
  {
    id: 5,
    name: "data_science_ml",
    display_name: "Data Science & ML",
    display_name_zh: "数据科学与机器学习",
    description: "Tools for data analysis and machine learning",
    description_zh: "数据分析和机器学习工具",
    icon: "📊",
    sort_order: 6,
  },
  {
    id: 6,
    name: "productivity_workflow",
    display_name: "Productivity & Workflow",
    display_name_zh: "生产力与工作流",
    description: "Tools for productivity and workflow automation",
    description_zh: "生产力和工作流自动化工具",
    icon: "⚡",
    sort_order: 7,
  },
  {
    id: 7,
    name: "deployment_devops",
    display_name: "Deployment & DevOps",
    display_name_zh: "部署与运维",
    description: "Tools for deployment and DevOps operations",
    description_zh: "部署和运维操作工具",
    icon: "🚀",
    sort_order: 8,
  },
  {
    id: 8,
    name: "web_scraping",
    display_name: "Web Scraping & Data",
    display_name_zh: "网页爬取与数据",
    description: "Tools for web scraping and data collection",
    description_zh: "网页爬取和数据收集工具",
    icon: "🕸️",
    sort_order: 9,
  },
];

export const STATIC_MCP_TOOLS_DATA: McpToolsItem[] = [
  // ================ Medical & Healthcare MCP Tools (Index 0) ================
  {
    id: 100,
    mcp_id: "medical-diagnosis-assist",
    name: "Medical Diagnosis Assist",
    display_name: "Medical Diagnosis Assist",
    display_name_zh: "医学诊断辅助",
    description: "Provides clinical decision support with evidence-based diagnosis suggestions, differential diagnosis analysis, and medical knowledge retrieval for healthcare professionals.",
    description_zh: "为医疗专业人员提供基于证据的诊断建议、鉴别诊断分析和医学知识检索的临床决策支持。",
    author: "Nexent Medical",
    author_url: "https://github.com/nexent-medical/mcp",
    category: MCP_TOOLS_CATEGORIES[0],
    tags: [
      { id: 1, name: "diagnosis", display_name: "诊断" },
      { id: 2, name: "clinical", display_name: "临床" },
      { id: 3, name: "decision-support", display_name: "决策支持" },
    ],
    github_stars: 18500,
    is_featured: true,
    content: `## Medical Diagnosis Assist MCP

### Overview
Provides clinical decision support with evidence-based diagnosis suggestions.

### Features
- Differential diagnosis generation
- Evidence-based suggestions
- Medical literature retrieval
- Symptom analysis

### Installation
\`\`\`bash
npm install @nexent/medical-diagnosis-mcp
\`\`\``,
    content_zh: `## 医学诊断辅助 MCP

### 概述
提供基于证据的诊断建议和临床决策支持。

### 功能特性
- 鉴别诊断生成
- 基于证据的建议
- 医学文献检索
- 症状分析

### 安装
\`\`\`bash
npm install @nexent/medical-diagnosis-mcp
\`\`\``,
    source_repo: "nexent/medical-mcp",
    official_url: "https://mcpmarket.com/zh/server/medical-diagnosis-assist",
    created_at: "2026-01-01",
    updated_at: "2026-04-07",
  },
  {
    id: 101,
    mcp_id: "health-data-analysis",
    name: "Health Data Analysis",
    display_name: "Health Data Analysis",
    display_name_zh: "健康数据分析",
    description: "Analyzes patient health records, lab results, and medical imaging data to extract insights and support clinical decision-making.",
    description_zh: "分析患者健康记录、检验结果和医学影像数据，提取洞察并支持临床决策。",
    author: "Nexent Medical",
    author_url: "https://github.com/nexent-medical/mcp",
    category: MCP_TOOLS_CATEGORIES[0],
    tags: [
      { id: 1, name: "health-records", display_name: "健康记录" },
      { id: 2, name: "analytics", display_name: "分析" },
      { id: 3, name: "lab-results", display_name: "检验结果" },
    ],
    github_stars: 14200,
    is_featured: true,
    content: `## Health Data Analysis MCP

### Overview
Analyzes patient health data and medical records.

### Features
- Lab result interpretation
- Health record aggregation
- Trend analysis
- Risk assessment`,
    content_zh: `## 健康数据分析 MCP

### 概述
分析患者健康数据和病历记录。

### 功能特性
- 检验结果解读
- 健康记录聚合
- 趋势分析
- 风险评估`,
    source_repo: "nexent/medical-mcp",
    official_url: "https://mcpmarket.com/zh/server/health-data-analysis",
    created_at: "2026-01-15",
    updated_at: "2026-04-06",
  },
  {
    id: 102,
    mcp_id: "drug-information",
    name: "Drug Information",
    display_name: "Drug Information",
    display_name_zh: "药物信息查询",
    description: "Provides comprehensive drug information including dosage, interactions, contraindications, and side effects for safe medication management.",
    description_zh: "提供全面的药物信息，包括剂量、相互作用、禁忌症和副作用，支持安全用药管理。",
    author: "Nexent Medical",
    author_url: "https://github.com/nexent-medical/mcp",
    category: MCP_TOOLS_CATEGORIES[0],
    tags: [
      { id: 1, name: "pharmacology", display_name: "药理学" },
      { id: 2, name: "medication", display_name: "用药" },
      { id: 3, name: "drug-safety", display_name: "用药安全" },
    ],
    github_stars: 12800,
    is_featured: true,
    content: `## Drug Information MCP

### Overview
Provides comprehensive drug information for safe medication management.

### Features
- Dosage information
- Drug interaction checking
- Contraindication alerts
- Side effect database`,
    content_zh: `## 药物信息查询 MCP

### 概述
提供全面的药物信息，支持安全用药管理。

### 功能特性
- 剂量信息
- 药物相互作用检查
- 禁忌症提醒
- 副作用数据库`,
    source_repo: "nexent/medical-mcp",
    official_url: "https://mcpmarket.com/zh/server/drug-information",
    created_at: "2026-02-01",
    updated_at: "2026-04-05",
  },
  {
    id: 103,
    mcp_id: "medical-imaging",
    name: "Medical Imaging",
    display_name: "Medical Imaging",
    display_name_zh: "医学影像分析",
    description: "Assists in analyzing medical images including X-ray, CT, MRI, and ultrasound scans with structured reporting support.",
    description_zh: "辅助分析 X 光、CT、MRI 和超声等医学影像，提供结构化报告支持。",
    author: "Nexent Medical",
    author_url: "https://github.com/nexent-medical/mcp",
    category: MCP_TOOLS_CATEGORIES[0],
    tags: [
      { id: 1, name: "imaging", display_name: "影像" },
      { id: 2, name: "radiology", display_name: "放射科" },
      { id: 3, name: "xray", display_name: "X光" },
    ],
    github_stars: 11500,
    is_featured: true,
    content: `## Medical Imaging MCP

### Overview
Assists in analyzing medical images with structured reporting.

### Features
- X-ray analysis
- CT scan interpretation
- MRI analysis
- Ultrasound support`,
    content_zh: `## 医学影像分析 MCP

### 概述
辅助分析医学影像，提供结构化报告。

### 功能特性
- X光分析
- CT 扫描解读
- MRI 分析
- 超声支持`,
    source_repo: "nexent/medical-mcp",
    official_url: "https://mcpmarket.com/zh/server/medical-imaging",
    created_at: "2026-02-15",
    updated_at: "2026-04-04",
  },
  {
    id: 104,
    mcp_id: "patient-records",
    name: "Patient Records",
    display_name: "Patient Records",
    display_name_zh: "病历记录管理",
    description: "Manages and retrieves patient medical records, clinical notes, and healthcare documentation with HIPAA-compliant access controls.",
    description_zh: "管理和检索患者病历、临床记录和医疗文档，支持 HIPAA 合规的访问控制。",
    author: "Nexent Medical",
    author_url: "https://github.com/nexent-medical/mcp",
    category: MCP_TOOLS_CATEGORIES[0],
    tags: [
      { id: 1, name: "ehr", display_name: "电子病历" },
      { id: 2, name: "records", display_name: "记录" },
      { id: 3, name: "hipaa", display_name: "HIPAA" },
    ],
    github_stars: 9800,
    is_featured: false,
    content: `## Patient Records MCP

### Overview
Manages patient medical records with HIPAA compliance.

### Features
- Medical record retrieval
- Clinical notes management
- Document organization`,
    content_zh: `## 病历记录管理 MCP

### 概述
管理患者病历记录，支持 HIPAA 合规。

### 功能特性
- 病历检索
- 临床记录管理
- 文档整理`,
    source_repo: "nexent/medical-mcp",
    official_url: "https://mcpmarket.com/zh/server/patient-records",
    created_at: "2026-03-01",
    updated_at: "2026-04-03",
  },
  {
    id: 105,
    mcp_id: "clinical-trials",
    name: "Clinical Trials",
    display_name: "Clinical Trials",
    display_name_zh: "临床试验查询",
    description: "Searches and retrieves clinical trial information including eligibility criteria, results, and enrollment status for research and treatment planning.",
    description_zh: "搜索和检索临床试验信息，包括入组标准、研究结果和招募状态，支持研究和治疗计划。",
    author: "Nexent Medical",
    author_url: "https://github.com/nexent-medical/mcp",
    category: MCP_TOOLS_CATEGORIES[0],
    tags: [
      { id: 1, name: "clinical-trials", display_name: "临床试验" },
      { id: 2, name: "research", display_name: "研究" },
      { id: 3, name: "enrollment", display_name: "招募" },
    ],
    github_stars: 8600,
    is_featured: false,
    content: `## Clinical Trials MCP

### Overview
Searches and retrieves clinical trial information.

### Features
- Trial search
- Eligibility checking
- Results retrieval`,
    content_zh: `## 临床试验查询 MCP

### 概述
搜索和检索临床试验信息。

### 功能特性
- 试验搜索
- 入组资格检查
- 结果检索`,
    source_repo: "nexent/medical-mcp",
    official_url: "https://mcpmarket.com/zh/server/clinical-trials",
    created_at: "2026-03-10",
    updated_at: "2026-04-02",
  },
  {
    id: 106,
    mcp_id: "medical-coding",
    name: "Medical Coding",
    display_name: "Medical Coding",
    display_name_zh: "医学编码",
    description: "Assists with ICD-10, CPT, and SNOMED CT coding for diagnoses, procedures, and medical documentation standardization.",
    description_zh: "辅助 ICD-10、CPT 和 SNOMED CT 编码，支持诊断、操作和医疗文档标准化。",
    author: "Nexent Medical",
    author_url: "https://github.com/nexent-medical/mcp",
    category: MCP_TOOLS_CATEGORIES[0],
    tags: [
      { id: 1, name: "icd", display_name: "ICD" },
      { id: 2, name: "cpt", display_name: "CPT" },
      { id: 3, name: "coding", display_name: "编码" },
    ],
    github_stars: 7500,
    is_featured: false,
    content: `## Medical Coding MCP

### Overview
Assists with medical coding for standardized documentation.

### Features
- ICD-10 coding
- CPT code lookup
- SNOMED CT mapping`,
    content_zh: `## 医学编码 MCP

### 概述
辅助医学编码，支持文档标准化。

### 功能特性
- ICD-10 编码
- CPT 代码查询
- SNOMED CT 映射`,
    source_repo: "nexent/medical-mcp",
    official_url: "https://mcpmarket.com/zh/server/medical-coding",
    created_at: "2026-03-15",
    updated_at: "2026-04-01",
  },
  {
    id: 107,
    mcp_id: "health-vital-signs",
    name: "Health Vital Signs",
    display_name: "Health Vital Signs",
    display_name_zh: "生命体征监测",
    description: "Monitors and analyzes patient vital signs including heart rate, blood pressure, temperature, and respiratory rate with trend analysis.",
    description_zh: "监测和分析患者生命体征，包括心率、血压、体温和呼吸频率，支持趋势分析。",
    author: "Nexent Medical",
    author_url: "https://github.com/nexent-medical/mcp",
    category: MCP_TOOLS_CATEGORIES[0],
    tags: [
      { id: 1, name: "vitals", display_name: "生命体征" },
      { id: 2, name: "monitoring", display_name: "监测" },
      { id: 3, name: "trends", display_name: "趋势" },
    ],
    github_stars: 6800,
    is_featured: false,
    content: `## Health Vital Signs MCP

### Overview
Monitors and analyzes patient vital signs.

### Features
- Heart rate monitoring
- Blood pressure tracking
- Temperature analysis`,
    content_zh: `## 生命体征监测 MCP

### 概述
监测和分析患者生命体征。

### 功能特性
- 心率监测
- 血压追踪
- 体温分析`,
    source_repo: "nexent/medical-mcp",
    official_url: "https://mcpmarket.com/zh/server/health-vital-signs",
    created_at: "2026-03-20",
    updated_at: "2026-03-31",
  },

  // ================ Developer Tools (Index 1) ================
  {
    id: 1,
    mcp_id: "superpowers",
    name: "Superpowers",
    display_name: "Superpowers",
    display_name_zh: "Superpowers",
    description: "Empowers AI coding agents with a comprehensive and structured software development workflow, from design refinement to TDD-driven implementation.",
    description_zh: "为 AI 编码智能体提供全面、结构化的软件开发工作流程，从设计优化到 TDD 驱动的实现。",
    author: "Superpowers Labs",
    author_url: "https://github.com/superpowerslabs/superpowers",
    category: MCP_TOOLS_CATEGORIES[1],
    tags: [
      { id: 1, name: "tdd", display_name: "TDD" },
      { id: 2, name: "workflow", display_name: "工作流" },
      { id: 3, name: "development", display_name: "开发" },
    ],
    github_stars: 136319,
    is_featured: false,
    content: `## Superpowers MCP

### Overview
Empowers AI coding agents with comprehensive development workflows.

### Features
- Design refinement
- TDD-driven implementation
- Code review automation`,
    content_zh: `## Superpowers MCP

### 概述
为 AI 编码智能体提供全面的开发工作流程。

### 功能特性
- 设计优化
- TDD 驱动实现
- 代码审查自动化`,
    source_repo: "superpowerslabs/superpowers",
    official_url: "https://mcpmarket.com/zh/server/superpowers",
    created_at: "2026-01-15",
    updated_at: "2026-04-01",
  },
  {
    id: 5,
    mcp_id: "openspec",
    name: "OpenSpec",
    display_name: "OpenSpec",
    display_name_zh: "OpenSpec",
    description: "Facilitates spec-driven development to ensure alignment between humans and AI coding assistants before any code is written.",
    description_zh: "促进规范驱动的开发，确保在编写任何代码之前人与 AI 编码助手之间的一致性。",
    author: "OpenSpec",
    author_url: "https://github.com/openspec/openspec",
    category: MCP_TOOLS_CATEGORIES[1],
    tags: [
      { id: 1, name: "spec-driven", display_name: "规范驱动" },
      { id: 2, name: "collaboration", display_name: "协作" },
      { id: 3, name: "documentation", display_name: "文档" },
    ],
    github_stars: 37470,
    is_featured: false,
    content: `## OpenSpec MCP

### Overview
Facilitates spec-driven development for better human-AI collaboration.

### Features
- Specification templates
- Requirement tracking`,
    content_zh: `## OpenSpec MCP

### 概述
促进规范驱动的开发，实现更好的人机协作。

### 功能特性
- 规范模板
- 需求跟踪`,
    source_repo: "openspec/openspec",
    official_url: "https://mcpmarket.com/zh/server/openspec",
    created_at: "2026-01-25",
    updated_at: "2026-03-30",
  },
  {
    id: 8,
    mcp_id: "ruflo",
    name: "Ruflo",
    display_name: "Ruflo",
    display_name_zh: "Ruflo",
    description: "Orchestrates intelligent multi-agent swarms for Claude, coordinating autonomous workflows and building conversational AI systems.",
    description_zh: "为 Claude 编排智能多智能体群，协调自主工作流并构建对话式 AI 系统。",
    author: "Ruflo",
    author_url: "https://github.com/ruflo/ruflo",
    category: MCP_TOOLS_CATEGORIES[1],
    tags: [
      { id: 1, name: "multi-agent", display_name: "多智能体" },
      { id: 2, name: "orchestration", display_name: "编排" },
      { id: 3, name: "workflow", display_name: "工作流" },
    ],
    github_stars: 30137,
    is_featured: false,
    content: `## Ruflo MCP

### Overview
Orchestrates intelligent multi-agent swarms for Claude.

### Features
- Multi-agent coordination
- Autonomous workflows`,
    content_zh: `## Ruflo MCP

### 概述
为 Claude 编排智能多智能体群。

### 功能特性
- 多智能体协调
- 自主工作流`,
    source_repo: "ruflo/ruflo",
    official_url: "https://mcpmarket.com/zh/server/ruflo",
    created_at: "2026-02-15",
    updated_at: "2026-04-04",
  },
  {
    id: 9,
    mcp_id: "github",
    name: "GitHub",
    display_name: "GitHub",
    display_name_zh: "GitHub",
    description: "Enables advanced automation and interaction capabilities with GitHub APIs for developers and tools using the Model Context Protocol.",
    description_zh: "使用 MCP 协议为开发者和工具提供 GitHub API 的高级自动化和交互能力。",
    author: "GitHub",
    author_url: "https://github.com/github/github-mcp",
    category: MCP_TOOLS_CATEGORIES[1],
    tags: [
      { id: 1, name: "github", display_name: "GitHub" },
      { id: 2, name: "api", display_name: "API" },
      { id: 3, name: "automation", display_name: "自动化" },
    ],
    github_stars: 28574,
    is_featured: false,
    content: `## GitHub MCP

### Overview
Advanced GitHub API automation for AI coding agents.

### Features
- Repository management
- Issue tracking
- PR operations`,
    content_zh: `## GitHub MCP

### 概述
AI 编码智能体的高级 GitHub API 自动化。

### 功能特性
- 仓库管理
- 问题跟踪
- PR 操作`,
    source_repo: "github/github-mcp",
    official_url: "https://mcpmarket.com/zh/server/github-15",
    created_at: "2026-01-05",
    updated_at: "2026-04-06",
  },
  {
    id: 19,
    mcp_id: "filesystem",
    name: "Filesystem",
    display_name: "Filesystem",
    display_name_zh: "文件系统",
    description: "Provides secure file system operations for AI agents, including reading, writing, and organizing files.",
    description_zh: "为 AI 智能体提供安全的文件系统操作，包括读取、写入和组织文件。",
    author: "MCP Community",
    author_url: "https://github.com/modelcontextprotocol/servers",
    category: MCP_TOOLS_CATEGORIES[1],
    tags: [
      { id: 1, name: "filesystem", display_name: "文件系统" },
      { id: 2, name: "file-operations", display_name: "文件操作" },
      { id: 3, name: "security", display_name: "安全" },
    ],
    github_stars: 4521,
    is_featured: false,
    content: `## Filesystem MCP

### Overview
Secure file system operations for AI agents.

### Features
- File read/write
- Directory listing
- Path manipulation`,
    content_zh: `## 文件系统 MCP

### 概述
AI 智能体的安全文件系统操作。

### 功能特性
- 文件读写
- 目录列表
- 路径操作`,
    source_repo: "modelcontextprotocol/servers",
    official_url: "https://mcpmarket.com/zh/server/filesystem",
    created_at: "2026-04-01",
    updated_at: "2026-04-06",
  },

  // ================ API Development (Index 2) ================
  {
    id: 2,
    mcp_id: "context7",
    name: "Context7",
    display_name: "Context7",
    display_name_zh: "Context7",
    description: "Fetches up-to-date documentation and code examples for LLMs and AI code editors directly from the source.",
    description_zh: "直接从源获取 LLMs 和 AI 代码编辑器的最新文档和代码示例。",
    author: "Context7",
    author_url: "https://github.com/context7/context7",
    category: MCP_TOOLS_CATEGORIES[2],
    tags: [
      { id: 1, name: "documentation", display_name: "文档" },
      { id: 2, name: "llm", display_name: "LLM" },
      { id: 3, name: "code-examples", display_name: "代码示例" },
    ],
    github_stars: 51717,
    is_featured: false,
    content: `## Context7 MCP

### Overview
Fetches up-to-date documentation and code examples for LLMs.

### Features
- Real-time documentation fetching
- Code example retrieval
- Multi-language support`,
    content_zh: `## Context7 MCP

### 概述
直接从源获取 LLMs 的最新文档和代码示例。

### 功能特性
- 实时文档获取
- 代码示例检索
- 多语言支持`,
    source_repo: "context7/context7",
    official_url: "https://mcpmarket.com/zh/server/context7-1",
    created_at: "2026-01-10",
    updated_at: "2026-03-28",
  },
  {
    id: 13,
    mcp_id: "fastmcp",
    name: "FastMCP",
    display_name: "FastMCP",
    display_name_zh: "FastMCP",
    description: "Facilitates the creation of Model Context Protocol (MCP) servers with a Pythonic interface.",
    description_zh: "使用 Python 风格的接口促进 MCP 服务器的创建。",
    author: "FastMCP",
    author_url: "https://github.com/fastmcp/fastmcp",
    category: MCP_TOOLS_CATEGORIES[2],
    tags: [
      { id: 1, name: "mcp", display_name: "MCP" },
      { id: 2, name: "python", display_name: "Python" },
      { id: 3, name: "server", display_name: "服务器" },
    ],
    github_stars: 22898,
    is_featured: false,
    content: `## FastMCP

### Overview
Create MCP servers with a Pythonic interface.

### Features
- Simple decorators
- Type hints support
- Async/await native`,
    content_zh: `## FastMCP

### 概述
使用 Python 风格的接口创建 MCP 服务器。

### 功能特性
- 简单的装饰器
- 类型提示支持
- 原生异步支持`,
    source_repo: "fastmcp/fastmcp",
    official_url: "https://mcpmarket.com/zh/server/fastmcp",
    created_at: "2026-03-05",
    updated_at: "2026-04-02",
  },

  // ================ Database Management (Index 3) ================
  {
    id: 4,
    mcp_id: "mindsdb",
    name: "MindsDB",
    display_name: "MindsDB",
    display_name_zh: "MindsDB",
    description: "Build AI applications that can learn and answer questions over large-scale federated data sources using a federated query engine.",
    description_zh: "使用联邦查询引擎构建能够在大规模联邦数据源上学习和回答问题的 AI 应用。",
    author: "MindsDB",
    author_url: "https://github.com/mindsdb/mindsdb",
    category: MCP_TOOLS_CATEGORIES[3],
    tags: [
      { id: 1, name: "federated", display_name: "联邦" },
      { id: 2, name: "ai", display_name: "AI" },
      { id: 3, name: "database", display_name: "数据库" },
    ],
    github_stars: 38909,
    is_featured: false,
    content: `## MindsDB MCP

### Overview
Build AI applications that can learn and answer questions over data.

### Features
- Federated query engine
- ML model integration
- Natural language queries`,
    content_zh: `## MindsDB MCP

### 概述
构建能够从数据中学习和回答问题的 AI 应用。

### 功能特性
- 联邦查询引擎
- ML 模型集成
- 自然语言查询`,
    source_repo: "mindsdb/mindsdb",
    official_url: "https://mcpmarket.com/zh/server/mindsdb",
    created_at: "2026-01-20",
    updated_at: "2026-03-25",
  },
  {
    id: 12,
    mcp_id: "graphiti",
    name: "Graphiti",
    display_name: "Graphiti",
    display_name_zh: "Graphiti",
    description: "Builds and queries temporally-aware knowledge graphs tailored for AI agents operating in dynamic environments.",
    description_zh: "构建和查询时间感知的知识图谱，专为在动态环境中运行的 AI 智能体设计。",
    author: "Graphiti",
    author_url: "https://github.com/graphiti/graphiti",
    category: MCP_TOOLS_CATEGORIES[3],
    tags: [
      { id: 1, name: "knowledge-graph", display_name: "知识图谱" },
      { id: 2, name: "temporal", display_name: "时间感知" },
      { id: 3, name: "ai", display_name: "AI" },
    ],
    github_stars: 24519,
    is_featured: false,
    content: `## Graphiti MCP

### Overview
Build temporally-aware knowledge graphs for AI agents.

### Features
- Knowledge graph construction
- Temporal queries
- Entity resolution`,
    content_zh: `## Graphiti MCP

### 概述
为 AI 智能体构建时间感知的知识图谱。

### 功能特性
- 知识图谱构建
- 时间查询
- 实体解析`,
    source_repo: "graphiti/graphiti",
    official_url: "https://mcpmarket.com/zh/server/graphiti",
    created_at: "2026-03-01",
    updated_at: "2026-04-03",
  },

  // ================ Browser Automation (Index 4) ================
  {
    id: 6,
    mcp_id: "chrome-devtools",
    name: "Chrome DevTools",
    display_name: "Chrome DevTools",
    display_name_zh: "Chrome 开发者工具",
    description: "Provides coding agents with programmatic access to Chrome DevTools for comprehensive browser control, inspection, and debugging.",
    description_zh: "为编码智能体提供对 Chrome DevTools 的编程访问，实现全面的浏览器控制、检查和调试。",
    author: "Chrome DevTools Team",
    author_url: "https://github.com/chrome-devtools/chrome-devtools",
    category: MCP_TOOLS_CATEGORIES[4],
    tags: [
      { id: 1, name: "browser", display_name: "浏览器" },
      { id: 2, name: "debugging", display_name: "调试" },
      { id: 3, name: "inspection", display_name: "检查" },
    ],
    github_stars: 33296,
    is_featured: false,
    content: `## Chrome DevTools MCP

### Overview
Programmatic access to Chrome DevTools for browser automation.

### Features
- Page inspection
- Console access
- Network monitoring`,
    content_zh: `## Chrome DevTools MCP

### 概述
编程访问 Chrome DevTools，实现浏览器自动化。

### 功能特性
- 页面检查
- 控制台访问
- 网络监控`,
    source_repo: "chrome-devtools/chrome-devtools",
    official_url: "https://mcpmarket.com/zh/server/chrome-devtools-1",
    created_at: "2026-02-05",
    updated_at: "2026-04-02",
  },
  {
    id: 7,
    mcp_id: "playwright",
    name: "Playwright",
    display_name: "Playwright",
    display_name_zh: "Playwright",
    description: "Automates browser interactions for Large Language Models (LLMs) using Playwright.",
    description_zh: "使用 Playwright 为大型语言模型 (LLM) 自动化浏览器交互。",
    author: "Microsoft",
    author_url: "https://github.com/microsoft/playwright",
    category: MCP_TOOLS_CATEGORIES[4],
    tags: [
      { id: 1, name: "playwright", display_name: "Playwright" },
      { id: 2, name: "browser", display_name: "浏览器" },
      { id: 3, name: "automation", display_name: "自动化" },
    ],
    github_stars: 30323,
    is_featured: false,
    content: `## Playwright MCP

### Overview
Automates browser interactions for LLMs using Playwright.

### Features
- Cross-browser testing
- Screenshot capture
- Form filling`,
    content_zh: `## Playwright MCP

### 概述
使用 Playwright 为 LLM 自动化浏览器交互。

### 功能特性
- 跨浏览器测试
- 截图捕获
- 表单填写`,
    source_repo: "microsoft/playwright",
    official_url: "https://mcpmarket.com/zh/server/playwright-5",
    created_at: "2026-02-10",
    updated_at: "2026-04-03",
  },

  // ================ Data Science & ML (Index 5) ================
  {
    id: 3,
    mcp_id: "trendradar",
    name: "TrendRadar",
    display_name: "TrendRadar",
    display_name_zh: "TrendRadar",
    description: "Aggregates trending topics from over 35 platforms, offering intelligent filtering, automated multi-channel notifications, and AI-powered conversational analysis.",
    description_zh: "从 35+ 平台聚合趋势话题，提供智能过滤、自动多渠道通知和 AI 驱动的对话分析。",
    author: "TrendRadar",
    author_url: "https://github.com/trendradar/trendradar",
    category: MCP_TOOLS_CATEGORIES[5],
    tags: [
      { id: 1, name: "trending", display_name: "趋势" },
      { id: 2, name: "analytics", display_name: "分析" },
      { id: 3, name: "notifications", display_name: "通知" },
    ],
    github_stars: 50924,
    is_featured: false,
    content: `## TrendRadar MCP

### Overview
Aggregates trending topics from over 35 platforms for real-time insights.

### Features
- Multi-platform aggregation
- Intelligent filtering
- Automated notifications`,
    content_zh: `## TrendRadar MCP

### 概述
从 35+ 平台聚合趋势话题，获取实时洞察。

### 功能特性
- 多平台聚合
- 智能过滤
- 自动通知`,
    source_repo: "trendradar/trendradar",
    official_url: "https://mcpmarket.com/zh/server/trendradar",
    created_at: "2026-02-01",
    updated_at: "2026-04-05",
  },
  {
    id: 10,
    mcp_id: "task-master",
    name: "Task Master",
    display_name: "Task Master",
    display_name_zh: "任务大师",
    description: "Streamline AI-driven development workflows by automating task management with Claude.",
    description_zh: "通过 Claude 自动执行任务管理，简化 AI 驱动的工作流程。",
    author: "TaskMaster",
    author_url: "https://github.com/taskmaster/taskmaster",
    category: MCP_TOOLS_CATEGORIES[5],
    tags: [
      { id: 1, name: "task-management", display_name: "任务管理" },
      { id: 2, name: "automation", display_name: "自动化" },
      { id: 3, name: "workflow", display_name: "工作流" },
    ],
    github_stars: 26410,
    is_featured: false,
    content: `## Task Master MCP

### Overview
Automate task management with Claude.

### Features
- Task creation
- Progress tracking
- Deadline management`,
    content_zh: `## 任务大师 MCP

### 概述
通过 Claude 自动执行任务管理。

### 功能特性
- 任务创建
- 进度跟踪
- 截止日期管理`,
    source_repo: "taskmaster/taskmaster",
    official_url: "https://mcpmarket.com/zh/server/task-master",
    created_at: "2026-02-20",
    updated_at: "2026-04-05",
  },
  {
    id: 16,
    mcp_id: "notion",
    name: "Notion",
    display_name: "Notion",
    display_name_zh: "Notion",
    description: "Implements a Model Context Protocol (MCP) server for the Notion API, enabling AI-driven interaction with Notion content.",
    description_zh: "为 Notion API 实现 MCP 服务器，支持与 Notion 内容的 AI 驱动交互。",
    author: "Notion",
    author_url: "https://github.com/notionhq/notion-mcp",
    category: MCP_TOOLS_CATEGORIES[5],
    tags: [
      { id: 1, name: "notion", display_name: "Notion" },
      { id: 2, name: "productivity", display_name: "生产力" },
      { id: 3, name: "workspace", display_name: "工作空间" },
    ],
    github_stars: 4175,
    is_featured: false,
    content: `## Notion MCP

### Overview
AI-driven interaction with Notion content.

### Features
- Page CRUD operations
- Database queries
- Block manipulation`,
    content_zh: `## Notion MCP

### 概述
与 Notion 内容的 AI 驱动交互。

### 功能特性
- 页面 CRUD 操作
- 数据库查询
- 块操作`,
    source_repo: "notionhq/notion-mcp",
    official_url: "https://mcpmarket.com/zh/server/notion-12",
    created_at: "2026-03-20",
    updated_at: "2026-04-04",
  },
  {
    id: 18,
    mcp_id: "slack",
    name: "Slack",
    display_name: "Slack",
    display_name_zh: "Slack",
    description: "Enables AI agents to send messages, manage channels, and interact with Slack workspaces.",
    description_zh: "使 AI 智能体能够发送消息、管理频道并与 Slack 工作空间交互。",
    author: "Slack",
    author_url: "https://github.com/slackhq/slack-mcp",
    category: MCP_TOOLS_CATEGORIES[5],
    tags: [
      { id: 1, name: "slack", display_name: "Slack" },
      { id: 2, name: "messaging", display_name: "消息" },
      { id: 3, name: "collaboration", display_name: "协作" },
    ],
    github_stars: 3256,
    is_featured: false,
    content: `## Slack MCP

### Overview
AI-driven Slack interactions.

### Features
- Message sending
- Channel management
- User search`,
    content_zh: `## Slack MCP

### 概述
AI 驱动的 Slack 交互。

### 功能特性
- 消息发送
- 频道管理
- 用户搜索`,
    source_repo: "slackhq/slack-mcp",
    official_url: "https://mcpmarket.com/zh/server/slack",
    created_at: "2026-03-28",
    updated_at: "2026-04-05",
  },
  {
    id: 20,
    mcp_id: "memory",
    name: "Memory",
    display_name: "Memory",
    display_name_zh: "记忆系统",
    description: "Provides persistent memory capabilities for AI agents, enabling long-term context retention across sessions.",
    description_zh: "为 AI 智能体提供持久化记忆能力，支持跨会话的长期上下文保留。",
    author: "MCP Community",
    author_url: "https://github.com/modelcontextprotocol/servers",
    category: MCP_TOOLS_CATEGORIES[5],
    tags: [
      { id: 1, name: "memory", display_name: "记忆" },
      { id: 2, name: "persistence", display_name: "持久化" },
      { id: 3, name: "context", display_name: "上下文" },
    ],
    github_stars: 3892,
    is_featured: false,
    content: `## Memory MCP

### Overview
Persistent memory for AI agents.

### Features
- Long-term storage
- Semantic search
- Context retrieval`,
    content_zh: `## 记忆 MCP

### 概述
AI 智能体的持久化记忆。

### 功能特性
- 长期存储
- 语义搜索
- 上下文检索`,
    source_repo: "modelcontextprotocol/servers",
    official_url: "https://mcpmarket.com/zh/server/memory",
    created_at: "2026-04-05",
    updated_at: "2026-04-07",
  },

  // ================ Deployment & DevOps (Index 6) ================
  {
    id: 14,
    mcp_id: "aws",
    name: "AWS",
    display_name: "AWS",
    display_name_zh: "AWS 云服务",
    description: "Bring AWS best practices directly into development workflows with a suite of specialized Model Context Protocol (MCP) servers.",
    description_zh: "通过一套专门的 MCP 服务器将 AWS 最佳实践直接带入开发工作流程。",
    author: "AWS",
    author_url: "https://github.com/aws/aws-mcp",
    category: MCP_TOOLS_CATEGORIES[6],
    tags: [
      { id: 1, name: "aws", display_name: "AWS" },
      { id: 2, name: "cloud", display_name: "云" },
      { id: 3, name: "devops", display_name: "运维" },
    ],
    github_stars: 8686,
    is_featured: false,
    content: `## AWS MCP

### Overview
AWS services integration for AI agents.

### Features
- EC2 management
- S3 operations
- Lambda functions`,
    content_zh: `## AWS MCP

### 概述
AI 智能体的 AWS 服务集成。

### 功能特性
- EC2 管理
- S3 操作
- Lambda 函数`,
    source_repo: "aws/aws-mcp",
    official_url: "https://mcpmarket.com/zh/server/aws-3",
    created_at: "2026-03-10",
    updated_at: "2026-04-01",
  },
  {
    id: 17,
    mcp_id: "k8s-lens",
    name: "Kubernetes Lens",
    display_name: "Kubernetes Lens",
    display_name_zh: "Kubernetes Lens",
    description: "Provides comprehensive Kubernetes cluster management and monitoring capabilities for AI agents.",
    description_zh: "为 AI 智能体提供全面的 Kubernetes 集群管理和监控能力。",
    author: "K8s Lens",
    author_url: "https://github.com/k8slens/k8s-lens",
    category: MCP_TOOLS_CATEGORIES[6],
    tags: [
      { id: 1, name: "kubernetes", display_name: "Kubernetes" },
      { id: 2, name: "cluster", display_name: "集群" },
      { id: 3, name: "monitoring", display_name: "监控" },
    ],
    github_stars: 7542,
    is_featured: false,
    content: `## Kubernetes Lens MCP

### Overview
Kubernetes cluster management for AI agents.

### Features
- Pod management
- Service discovery
- Log aggregation`,
    content_zh: `## Kubernetes Lens MCP

### 概述
AI 智能体的 Kubernetes 集群管理。

### 功能特性
- Pod 管理
- 服务发现
- 日志聚合`,
    source_repo: "k8slens/k8s-lens",
    official_url: "https://mcpmarket.com/zh/server/k8s-lens",
    created_at: "2026-03-25",
    updated_at: "2026-04-03",
  },

  // ================ Web Scraping & Data (Index 7) ================
  {
    id: 11,
    mcp_id: "gpt-researcher",
    name: "GPT Researcher",
    display_name: "GPT Researcher",
    display_name_zh: "GPT 研究员",
    description: "Conducts in-depth web and local research on any topic, generating comprehensive reports with citations.",
    description_zh: "对任何主题进行深入的网络和本地研究，生成带有引用的综合报告。",
    author: "GPT Researcher",
    author_url: "https://github.com/gpt-researcher/gpt-researcher",
    category: MCP_TOOLS_CATEGORIES[7],
    tags: [
      { id: 1, name: "research", display_name: "研究" },
      { id: 2, name: "web-search", display_name: "网络搜索" },
      { id: 3, name: "reports", display_name: "报告" },
    ],
    github_stars: 26255,
    is_featured: false,
    content: `## GPT Researcher MCP

### Overview
Conduct in-depth research and generate comprehensive reports.

### Features
- Web research
- Local document analysis
- Citation generation`,
    content_zh: `## GPT 研究员 MCP

### 概述
进行深入研究并生成综合报告。

### 功能特性
- 网络研究
- 本地文档分析
- 引用生成`,
    source_repo: "gpt-researcher/gpt-researcher",
    official_url: "https://mcpmarket.com/zh/server/gpt-researcher-1",
    created_at: "2026-02-25",
    updated_at: "2026-04-04",
  },
  {
    id: 15,
    mcp_id: "firecrawl",
    name: "Firecrawl",
    display_name: "Firecrawl",
    display_name_zh: "Firecrawl",
    description: "Integrates powerful web scraping and content extraction capabilities into LLM clients like Cursor and Claude.",
    description_zh: "将强大的网页爬取和内容提取能力集成到 Cursor 和 Claude 等 LLM 客户端中。",
    author: "Firecrawl",
    author_url: "https://github.com/firecrawl/firecrawl",
    category: MCP_TOOLS_CATEGORIES[7],
    tags: [
      { id: 1, name: "web-scraping", display_name: "网页爬取" },
      { id: 2, name: "content-extraction", display_name: "内容提取" },
      { id: 3, name: "llm", display_name: "LLM" },
    ],
    github_stars: 5953,
    is_featured: false,
    content: `## Firecrawl MCP

### Overview
Web scraping and content extraction for AI agents.

### Features
- Full page extraction
- Sitemap crawling
- Content cleaning`,
    content_zh: `## Firecrawl MCP

### 概述
AI 智能体的网页爬取和内容提取。

### 功能特性
- 整页提取
- 站点地图爬取
- 内容清洗`,
    source_repo: "firecrawl/firecrawl",
    official_url: "https://mcpmarket.com/zh/server/firecrawl-10",
    created_at: "2026-03-15",
    updated_at: "2026-04-05",
  },
];

/**
 * Get MCP tools by category
 */
export function getMcpToolsByCategory(category: string): McpToolsItem[] {
  if (category === "all") {
    // Sort: medical tools first, then by github_stars
    return [...STATIC_MCP_TOOLS_DATA].sort((a, b) => {
      const aIsMedical = a.category.name === "medical_healthcare";
      const bIsMedical = b.category.name === "medical_healthcare";
      if (aIsMedical && !bIsMedical) return -1;
      if (!aIsMedical && bIsMedical) return 1;
      return b.github_stars - a.github_stars;
    });
  }
  return STATIC_MCP_TOOLS_DATA.filter(
    (tool) => tool.category.name === category
  );
}

/**
 * Search MCP tools by keyword
 */
export function searchMcpTools(keyword: string): McpToolsItem[] {
  const lowerKeyword = keyword.toLowerCase();
  return STATIC_MCP_TOOLS_DATA.filter(
    (tool) =>
      tool.name.toLowerCase().includes(lowerKeyword) ||
      tool.display_name.toLowerCase().includes(lowerKeyword) ||
      tool.display_name_zh.includes(keyword) ||
      tool.description.toLowerCase().includes(lowerKeyword) ||
      tool.description_zh.includes(keyword) ||
      tool.tags.some(
        (tag) =>
          tag.name.toLowerCase().includes(lowerKeyword) ||
          tag.display_name.includes(keyword)
      )
  );
}
