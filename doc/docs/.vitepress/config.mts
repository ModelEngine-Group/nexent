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
            text: "Getting Started",
            items: [
              { text: "Overview", link: "/en/getting-started/overview" },
              { text: "Key Features", link: "/en/getting-started/features" },
              {
                text: "Software Architecture",
                link: "/en/getting-started/software-architecture",
              },
              {
                text: "Installation & Deployment",
                link: "/en/getting-started/installation",
              },
              {
                text: "Development Guide",
                link: "/en/getting-started/development-guide",
              },
              { text: "FAQ", link: "/en/getting-started/faq" },
            ],
          },
          {
            text: "User Guide",
            items: [
              { text: "Quick Start", link: "/en/user-guide/" },
              {
                text: "App Configuration",
                link: "/en/user-guide/app-configuration",
              },
              {
                text: "Model Configuration",
                link: "/en/user-guide/model-configuration",
              },
              {
                text: "Knowledge Base Configuration",
                link: "/en/user-guide/knowledge-base-configuration",
              },
              {
                text: "Agent Configuration",
                link: "/en/user-guide/agent-configuration",
              },
              { text: "Chat Interface", link: "/en/user-guide/chat-interface" },
              { text: "Memory Configuration", link: "/en/user-guide/memory" },
              {
                text: "Local Tools",
                items: [
                  {
                    text: "Local Tools Overview",
                    link: "/en/user-guide/local-tools/",
                  },
                  {
                    text: "Terminal Tool",
                    link: "/en/user-guide/local-tools/terminal-tool",
                  },
                ],
              },
            ],
          },
          {
            text: "SDK Documentation",
            items: [
              { text: "SDK Overview", link: "/en/sdk/overview" },
              { text: "Basic Usage", link: "/en/sdk/basic-usage" },
              { text: "Features Explained", link: "/en/sdk/features" },
              {
                text: "Core Modules",
                items: [
                  { text: "Agents", link: "/en/sdk/core/agents" },
                  {
                    text: "Run agent with agent_run",
                    link: "/en/sdk/core/agent-run",
                  },
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
              { text: "Frontend Overview", link: "/en/frontend/overview" },
            ],
          },
          {
            text: "Backend Development",
            items: [
              { text: "Backend Overview", link: "/en/backend/overview" },
              { text: "API Reference", link: "/en/backend/api-reference" },
              {
                text: "Tools Integration",
                items: [
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
              { text: "Use Cases", link: "/en/mcp-ecosystem/use-cases" },
            ],
          },
          {
            text: "Version Management",
            items: [
              {
                text: "Version Management Guide",
                link: "/en/version/version-management",
              },
            ],
          },
          {
            text: "Testing",
            items: [
              { text: "Testing Overview", link: "/en/testing/overview" },
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
              { text: "Known Issues", link: "/en/known-issues" },
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
            text: "快速开始",
            items: [
              { text: "项目概览", link: "/zh/getting-started/overview" },
              { text: "核心特性", link: "/zh/getting-started/features" },
              {
                text: "软件架构",
                link: "/zh/getting-started/software-architecture",
              },
              { text: "安装部署", link: "/zh/getting-started/installation" },
              {
                text: "开发指南",
                link: "/zh/getting-started/development-guide",
              },
              { text: "常见问题", link: "/zh/getting-started/faq" },
            ],
          },
          {
            text: "用户指南",
            items: [
              { text: "快速开始", link: "/zh/user-guide/" },
              { text: "应用配置", link: "/zh/user-guide/app-configuration" },
              { text: "模型配置", link: "/zh/user-guide/model-configuration" },
              {
                text: "知识库配置",
                link: "/zh/user-guide/knowledge-base-configuration",
              },
              {
                text: "智能体配置",
                link: "/zh/user-guide/agent-configuration",
              },
              { text: "对话页面", link: "/zh/user-guide/chat-interface" },
              { text: "记忆配置", link: "/zh/user-guide/memory" },
              {
                text: "本地工具",
                items: [
                  { text: "本地工具概览", link: "/zh/user-guide/local-tools/" },
                  {
                    text: "Terminal工具",
                    link: "/zh/user-guide/local-tools/terminal-tool",
                  },
                ],
              },
            ],
          },
          {
            text: "SDK 文档",
            items: [
              { text: "SDK 概览", link: "/zh/sdk/overview" },
              { text: "基本使用", link: "/zh/sdk/basic-usage" },
              { text: "特性详解", link: "/zh/sdk/features" },
              {
                text: "核心模块",
                items: [
                  { text: "智能体模块", link: "/zh/sdk/core/agents" },
                  {
                    text: "使用 agent_run 运行智能体",
                    link: "/zh/sdk/core/agent-run",
                  },
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
            items: [{ text: "前端概览", link: "/zh/frontend/overview" }],
          },
          {
            text: "后端开发",
            items: [
              { text: "后端概览", link: "/zh/backend/overview" },
              { text: "API 文档", link: "/zh/backend/api-reference" },
              {
                text: "工具集成",
                items: [
                  {
                    text: "LangChain 工具",
                    link: "/zh/backend/tools/langchain",
                  },
                  { text: "MCP 工具", link: "/zh/backend/tools/mcp" },
                ],
              },
              { text: "提示词开发", link: "/zh/backend/prompt-development" },
            ],
          },
          {
            text: "文档开发",
            items: [{ text: "文档开发指南", link: "/zh/docs-development" }],
          },
          {
            text: "容器构建与容器化开发",
            items: [
              { text: "Docker 构建", link: "/zh/deployment/docker-build" },
              { text: "开发容器", link: "/zh/deployment/devcontainer" },
            ],
          },
          {
            text: "MCP 生态系统",
            items: [
              { text: "概览", link: "/zh/mcp-ecosystem/overview" },
              { text: "用例场景", link: "/zh/mcp-ecosystem/use-cases" },
            ],
          },
          {
            text: "版本信息管理",
            items: [
              { text: "版本管理指南", link: "/zh/version/version-management" },
            ],
          },
          {
            text: "测试",
            items: [
              { text: "测试概览", link: "/zh/testing/overview" },
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
              { text: "已知问题", link: "/zh/known-issues" },
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
