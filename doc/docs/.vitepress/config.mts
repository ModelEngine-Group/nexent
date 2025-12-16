// https://vitepress.dev/reference/site-config
import { defineConfig } from "vitepress";

export default defineConfig({
  // Set base path for GitHub Pages deployment
  base: (globalThis as any).process?.env?.GITHUB_PAGES ? '/nexent/' : '/',
  title: "Nexent Doc",
  description:
    "A zero-code platform for auto-generating agents  no orchestration, no complex drag-and-drop required.",

  // Add favicon to head
  head: [["link", { rel: "icon", href: (globalThis as any).process?.env?.GITHUB_PAGES ? "/nexent/favicon.ico" : "/doc/favicon.ico" }]],

  // Ignore localhost links as they are meant for local deployment access
  ignoreDeadLinks: [
    // Ignore localhost links for main app
    /^http:\/\/localhost:3000/,
    // Ignore localhost links for monitoring services
    /^http:\/\/localhost:3005/, // Grafana
    /^http:\/\/localhost:9090/, // Prometheus
    /^http:\/\/localhost:16686/, // Jaeger
    /^http:\/\/localhost:8000/, // Metrics endpoint
  ],

  locales: {
    en: {
      label: "English",
      lang: "en",
      themeConfig: {
        nav: [
          { text: "Home", link: "http://nexent.tech" },
          { text: "Docs", link: "/en/getting-started/overview" },
        ],
        sidebar: [
          {
            text: "Overview",
            items: [
              { text: "Overview", link: "/en/getting-started/overview" },
              { text: "Key Features", link: "/en/getting-started/features" },
              {
                text: "Software Architecture",
                link: "/en/getting-started/software-architecture",
              },
            ],
          },
          {
            text: "Quick Start",
            items: [
              {
                text: "Installation & Deployment",
                link: "/en/quick-start/installation",
              },
              {
                text: "Upgrade Guide",
                link: "/en/quick-start/upgrade-guide",
              },
              { text: "FAQ", link: "/en/quick-start/faq" },
            ],
          },
          {
            text: "Developer Guide",
            items: [
              {
                text: "Overview",
                link: "/en/developer-guide/overview",
              },
              {
                text: "Environment Preparation",
                link: "/en/developer-guide/environment-setup",
              },
            ],
          },
          {
            text: "User Guide",
            items: [
              { text: "Home Page", link: "/en/user-guide/home-page" },
              { text: "Start Chat", link: "/en/user-guide/start-chat" },
              {
                text: "Quick Setup",
                link: "/en/user-guide/quick-setup",
              },
              { text: "Agent Space", link: "/en/user-guide/agent-space" },
              { text: "Agent Market", link: "/en/user-guide/agent-market" },
              {
                text: "Agent Development",
                link: "/en/user-guide/agent-development",
              },
              {
                text: "Knowledge Base",
                link: "/en/user-guide/knowledge-base",
              },
              { text: "MCP Tools", link: "/en/user-guide/mcp-tools" },
              { text: "Monitoring & Ops", link: "/en/user-guide/monitor" },
              {
                text: "Model Management",
                link: "/en/user-guide/model-management",
              },
              {
                text: "Memory Management",
                link: "/en/user-guide/memory-management",
              },
              { text: "User Management", link: "/en/user-guide/user-management" },
              {
                text: "Local Tools",
                items: [
                  { text: "Overview", link: "/en/user-guide/local-tools/" },
                  { text: "File Tools", link: "/en/user-guide/local-tools/file-tools" },
                  { text: "Email Tools", link: "/en/user-guide/local-tools/email-tools" },
                  { text: "Search Tools", link: "/en/user-guide/local-tools/search-tools" },
                  { text: "Multimodal Tools", link: "/en/user-guide/local-tools/multimodal-tools" },
                  { text: "Terminal Tool", link: "/en/user-guide/local-tools/terminal-tool" },
                ],
              },
            ],
          },
          {
            text: "SDK Documentation",
            items: [
              { text: "Overview", link: "/en/sdk/overview" },
              { text: "Basic Usage", link: "/en/sdk/basic-usage" },
              { text: "Features Explained", link: "/en/sdk/features" },
              {
                text: "Core Modules",
                items: [
                  { text: "Agents", link: "/en/sdk/core/agents" },
                  { text: "Tools", link: "/en/sdk/core/tools" },
                  { text: "Models", link: "/en/sdk/core/models" },
                ],
              },
              { text: "Performance Monitoring", link: "/en/sdk/monitoring" },
              { text: "Vector Database", link: "/en/sdk/vector-database" },
              { text: "Data Processing", link: "/en/sdk/data-process" },
            ],
          },
          {
            text: "Frontend Development",
            items: [
              { text: "Overview", link: "/en/frontend/overview" },
            ],
          },
          {
            text: "Backend Development",
            items: [
              { text: "Overview", link: "/en/backend/overview" },
              { text: "API Reference", link: "/en/backend/api-reference" },
              {
                text: "Tools Integration",
                items: [
                  {
                    text: "Nexent Tools",
                    link: "/en/backend/tools/nexent-native",
                  },
                  {
                    text: "LangChain Tools",
                    link: "/en/backend/tools/langchain",
                  },
                  { text: "MCP Tools", link: "/en/backend/tools/mcp" },
                ],
              },
              {
                text: "Prompt Development",
                link: "/en/backend/prompt-development",
              },
              {
                text: "Version Management",
                link: "/en/backend/version-management",
              },
            ],
          },
          {
            text: "Documentation Development",
            items: [
              { text: "Docs Development Guide", link: "/en/docs-development" },
            ],
          },
          {
            text: "Container Build & Containerized Development",
            items: [
              { text: "Docker Build", link: "/en/deployment/docker-build" },
              { text: "Dev Container", link: "/en/deployment/devcontainer" },
            ],
          },
          {
            text: "MCP Ecosystem",
            items: [
              { text: "Overview", link: "/en/mcp-ecosystem/overview" },
              { text: "MCP Recommendations", link: "/en/mcp-ecosystem/mcp-recommendations" },
              { text: "Use Cases", link: "/en/mcp-ecosystem/use-cases" },
            ],
          },
          {
            text: "Testing",
            items: [
              { text: "Overview", link: "/en/testing/overview" },
              { text: "Backend Testing", link: "/en/testing/backend" },
            ],
          },
          {
            text: "Community",
            items: [
              { text: "Contributing", link: "/en/contributing" },
              {
                text: "Open Source Memorial Wall",
                link: "/en/opensource-memorial-wall",
              },
              { text: "Code of Conduct", link: "/en/code-of-conduct" },
              { text: "Security Policy", link: "/en/security" },
              { text: "Core Contributors", link: "/en/contributors" },
              { text: "License", link: "/en/license" },
            ],
          },
        ],
        socialLinks: [
          {
            icon: "github",
            link: "https://github.com/ModelEngine-Group/nexent",
          },
          { icon: "discord", link: "https://discord.gg/tb5H3S3wyv" },
          { icon: "wechat", link: "http://nexent.tech/contact" },
        ],
      },
    },
    zh: {
      label: "简体中文",
      lang: "zh-CN",
      themeConfig: {
        nav: [
          { text: "首页", link: "http://nexent.tech" },
          { text: "文档", link: "/zh/getting-started/overview" },
        ],
        sidebar: [
          {
            text: "概览",
            items: [
              { text: "项目概览", link: "/zh/getting-started/overview" },
              { text: "核心特性", link: "/zh/getting-started/features" },
              {
                text: "软件架构",
                link: "/zh/getting-started/software-architecture",
              },
            ],
          },
          {
            text: "快速开始",
            items: [
              { text: "安装部署", link: "/zh/quick-start/installation" },
              {
                text: "升级指导",
                link: "/zh/quick-start/upgrade-guide",
              },
              { text: "常见问题", link: "/zh/quick-start/faq" },
            ],
          },
          {
            text: "开发者指南",
            items: [
              {
                text: "概览",
                link: "/zh/developer-guide/overview",
              },
              {
                text: "环境准备",
                link: "/zh/developer-guide/environment-setup",
              },
            ],
          },
          {
            text: "用户指南",
            items: [
              { text: "首页", link: "/zh/user-guide/home-page" },
              { text: "开始问答", link: "/zh/user-guide/start-chat" },
              { text: "快速配置", link: "/zh/user-guide/quick-setup" },
              { text: "智能体空间", link: "/zh/user-guide/agent-space" },
              { text: "智能体市场", link: "/zh/user-guide/agent-market" },
              {
                text: "智能体开发",
                link: "/zh/user-guide/agent-development",
              },
              {
                text: "知识库",
                link: "/zh/user-guide/knowledge-base",
              },
              { text: "MCP工具", link: "/zh/user-guide/mcp-tools" },
              { text: "监控与运维", link: "/zh/user-guide/monitor" },
              { text: "模型管理", link: "/zh/user-guide/model-management" },
              { text: "记忆管理", link: "/zh/user-guide/memory-management" },
              { text: "用户管理", link: "/zh/user-guide/user-management" },
              {
                text: "本地工具",
                items: [
                  { text: "概览", link: "/zh/user-guide/local-tools/" },
                  { text: "文件工具", link: "/zh/user-guide/local-tools/file-tools" },
                  { text: "邮件工具", link: "/zh/user-guide/local-tools/email-tools" },
                  { text: "搜索工具", link: "/zh/user-guide/local-tools/search-tools" },
                  { text: "多模态工具", link: "/zh/user-guide/local-tools/multimodal-tools" },
                  { text: "终端工具", link: "/zh/user-guide/local-tools/terminal-tool" },
                ],
              },
            ],
          },
          {
            text: "SDK 文档",
            items: [
              { text: "概览", link: "/zh/sdk/overview" },
              { text: "基本使用", link: "/zh/sdk/basic-usage" },
              { text: "特性详解", link: "/zh/sdk/features" },
              {
                text: "核心模块",
                items: [
                  { text: "智能体模块", link: "/zh/sdk/core/agents" },
                  { text: "工具模块", link: "/zh/sdk/core/tools" },
                  { text: "模型模块", link: "/zh/sdk/core/models" },
                ],
              },
              { text: "性能监控", link: "/zh/sdk/monitoring" },
              { text: "向量数据库", link: "/zh/sdk/vector-database" },
              { text: "数据处理", link: "/zh/sdk/data-process" },
            ],
          },
          {
            text: "前端开发",
            items: [{ text: "概览", link: "/zh/frontend/overview" }],
          },
          {
            text: "后端开发",
            items: [
              { text: "概览", link: "/zh/backend/overview" },
              { text: "API 文档", link: "/zh/backend/api-reference" },
              {
                text: "工具集成",
                items: [
                  {
                    text: "Nexent 工具",
                    link: "/zh/backend/tools/nexent-native",
                  },
                  {
                    text: "LangChain 工具",
                    link: "/zh/backend/tools/langchain",
                  },
                  { text: "MCP 工具", link: "/zh/backend/tools/mcp" },
                ],
              },
              { text: "提示词开发", link: "/zh/backend/prompt-development" },
              { text: "版本管理", link: "/zh/backend/version-management" },
            ],
          },
          {
            text: "文档开发",
            items: [{ text: "开发指南", link: "/zh/docs-development" }],
          },
          {
            text: "容器构建与容器化开发",
            items: [
              { text: "镜像构建", link: "/zh/deployment/docker-build" },
              { text: "容器开发", link: "/zh/deployment/devcontainer" },
            ],
          },
          {
            text: "MCP 生态系统",
            items: [
              { text: "概览", link: "/zh/mcp-ecosystem/overview" },
              { text: "MCP 推荐", link: "/zh/mcp-ecosystem/mcp-recommendations" },
              { text: "用例场景", link: "/zh/mcp-ecosystem/use-cases" },
            ],
          },
          {
            text: "测试",
            items: [
              { text: "概览", link: "/zh/testing/overview" },
              { text: "后端测试", link: "/zh/testing/backend" },
            ],
          },
          {
            text: "社区",
            items: [
              { text: "贡献指南", link: "/zh/contributing" },
              { text: "开源纪念墙", link: "/zh/opensource-memorial-wall" },
              { text: "行为准则", link: "/zh/code-of-conduct" },
              { text: "安全政策", link: "/zh/security" },
              { text: "核心贡献者", link: "/zh/contributors" },
              { text: "许可证", link: "/zh/license" },
            ],
          },
        ],
        socialLinks: [
          {
            icon: "github",
            link: "https://github.com/ModelEngine-Group/nexent",
          },
          { icon: "discord", link: "https://discord.gg/tb5H3S3wyv" },
          { icon: "wechat", link: "http://nexent.tech/contact" },
        ],
      },
    },
  },

  themeConfig: {
    logo: "/Nexent Logo.jpg",
    socialLinks: [
      { icon: "github", link: "https://github.com/ModelEngine-Group/nexent" },
    ],
  },
});
