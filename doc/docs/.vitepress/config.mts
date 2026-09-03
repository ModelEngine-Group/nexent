// https://vitepress.dev/reference/site-config
import { defineConfig } from "vitepress";

export default defineConfig({
  // Set base path for GitHub Pages deployment
  base: (globalThis as any).process?.env?.GITHUB_PAGES ? "/nexent/" : "/",
  title: "Nexent Doc",
  description:
    "A zero-code platform for auto-generating production-grade AI agents using Harness Engineering principles.",

  // Add favicon to head
  head: [
    [
      "link",
      {
        rel: "icon",
        href: (globalThis as any).process?.env?.GITHUB_PAGES
          ? "/nexent/favicon.ico"
          : "/doc/favicon.ico",
      },
    ],
  ],

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
            collapsed: false,
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
            text: "Deployment & Upgrade",
            collapsed: false,
            items: [
              {
                text: "Installation & Deployment",
                items: [
                  {
                    text: "Docker",
                    link: "/en/quick-start/installation",
                  },
                  {
                    text: "Kubernetes",
                    link: "/en/quick-start/kubernetes-installation",
                  },
                ],
              },
              {
                text: "Upgrade Guide",
                items: [
                  {
                    text: "Docker",
                    link: "/en/quick-start/upgrade-guide",
                  },
                  {
                    text: "Kubernetes",
                    link: "/en/quick-start/kubernetes-upgrade-guide",
                  },
                ],
              },
              { text: "FAQ", link: "/en/quick-start/faq" },
            ],
          },
          {
            text: "User Guide",
            collapsed: false,
            items: [
              { text: "Home Page", link: "/en/user-guide/home-page" },
              { text: "Start Chat", link: "/en/user-guide/start-chat" },
              { text: "Auto Tasks", link: "/en/user-guide/auto-tasks" },
              {
                text: "Agent Development",
                link: "/en/user-guide/agent-development",
                items: [
                  {
                    text: "Model Configuration",
                    link: "/en/user-guide/agent-development/model-configuration",
                  },
                  {
                    text: "Knowledge Configuration",
                    link: "/en/user-guide/agent-development/knowledge-configuration",
                  },
                  {
                    text: "Agent Configuration",
                    link: "/en/user-guide/agent-development/agent-configuration",
                    items: [
                      {
                        text: "Add External A2A Agents",
                        link: "/en/user-guide/agent-development/a2a-external",
                      },
                      {
                        text: "Publish as A2A Agent",
                        link: "/en/user-guide/agent-development/a2a-publish",
                      },
                      {
                        text: "Local Tools",
                        link: "/en/user-guide/local-tools/",
                      },
                    ],
                  },
                  {
                    text: "Memory Configuration",
                    link: "/en/user-guide/agent-development/memory-configuration",
                  },
                ],
              },
              {
                text: "Resource Repository",
                items: [
                  {
                    text: "Agent Repository",
                    link: "/en/user-guide/resource-repository/agent-repository",
                  },
                  {
                    text: "MCP Repository",
                    link: "/en/user-guide/resource-repository/mcp-repository",
                  },
                  {
                    text: "Skill Repository",
                    link: "/en/user-guide/resource-repository/skill-repository",
                  },
                ],
              },
              {
                text: "Resource Management",
                link: "/en/user-guide/resource-management",
              },
            ],
          },
          {
            text: "Developer Guide",
            collapsed: false,
            items: [
              {
                text: "Developer Guide",
                items: [
                  { text: "Overview", link: "/en/developer-guide/overview" },
                  { text: "Environment Setup", link: "/en/developer-guide/environment-setup" },
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
                text: "Testing",
                items: [
                  { text: "Overview", link: "/en/testing/overview" },
                  { text: "Backend Testing", link: "/en/testing/backend" },
                ],
              },
            ],
          },
          {
            text: "Third-Party Integration",
            collapsed: false,
            items: [
              {
                text: "Integration Overview",
                link: "/en/integration/",
              },
              {
                text: "Integration-In (Inbound)",
                link: "/en/integration/integration-in/overview",
                items: [
                  {
                    text: "MCP Service Integration",
                    link: "/en/integration/integration-in/mcp",
                  },
                  {
                    text: "Skill Integration",
                    link: "/en/integration/integration-in/skills",
                  },
                  {
                    text: "Agent Integration",
                    link: "/en/integration/integration-in/agents",
                  },
                ],
              },
              {
                text: "Integration-Out (Outbound)",
                link: "/en/integration/integration-out/overview",
                items: [
                  {
                    text: "Agent Export",
                    link: "/en/integration/integration-out/agents-export",
                  },
                  {
                    text: "Agent Publishing",
                    link: "/en/integration/integration-out/agents-publish",
                  },
                  {
                    text: "Northbound API",
                    link: "/en/integration/integration-out/northbound-api",
                  },
                ],
              },
            ],
          },
          {
            text: "SDK Documentation",
            collapsed: false,
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
            text: "Community",
            collapsed: false,
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
            collapsed: false,
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
            text: "部署与升级",
            collapsed: false,
            items: [
              {
                text: "安装部署",
                items: [
                  {
                    text: "Docker",
                    link: "/zh/quick-start/installation",
                  },
                  {
                    text: "Kubernetes",
                    link: "/zh/quick-start/kubernetes-installation",
                  },
                ],
              },
              {
                text: "升级指南",
                items: [
                  {
                    text: "Docker",
                    link: "/zh/quick-start/upgrade-guide",
                  },
                  {
                    text: "Kubernetes",
                    link: "/zh/quick-start/kubernetes-upgrade-guide",
                  },
                ],
              },
              { text: "常见问题", link: "/zh/quick-start/faq" },
            ],
          },
          {
            text: "用户指南",
            collapsed: false,
            items: [
              { text: "首页", link: "/zh/user-guide/home-page" },
              { text: "开始问答", link: "/zh/user-guide/start-chat" },
              { text: "自动任务", link: "/zh/user-guide/auto-tasks" },
              {
                text: "智能体开发",
                link: "/zh/user-guide/agent-development",
                items: [
                  {
                    text: "模型配置",
                    link: "/zh/user-guide/agent-development/model-configuration",
                  },
                  {
                    text: "知识库配置",
                    link: "/zh/user-guide/agent-development/knowledge-configuration",
                  },
                  {
                    text: "智能体配置",
                    link: "/zh/user-guide/agent-development/agent-configuration",
                    items: [
                      {
                        text: "添加外部 A2A Agent",
                        link: "/zh/user-guide/agent-development/a2a-external",
                      },
                      {
                        text: "发布为 A2A Agent",
                        link: "/zh/user-guide/agent-development/a2a-publish",
                      },
                      {
                        text: "本地工具",
                        link: "/zh/user-guide/local-tools/",
                      },
                    ],
                  },
                  {
                    text: "记忆配置",
                    link: "/zh/user-guide/agent-development/memory-configuration",
                  },
                ],
              },
              {
                text: "资源仓库",
                items: [
                  {
                    text: "智能体仓库",
                    link: "/zh/user-guide/resource-repository/agent-repository",
                  },
                  {
                    text: "MCP仓库",
                    link: "/zh/user-guide/resource-repository/mcp-repository",
                  },
                ],
              },
              {
                text: "资源管理",
                link: "/zh/user-guide/resource-management",
              },
            ],
          },
          {
            text: "开发者指南",
            collapsed: false,
            items: [
              {
                text: "开发者指南",
                items: [
                  { text: "概览", link: "/zh/developer-guide/overview" },
                  { text: "环境准备", link: "/zh/developer-guide/environment-setup" },
                ],
              },
              {
                text: "前端开发",
                items: [
                  { text: "概览", link: "/zh/frontend/overview" },
                ],
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
                items: [
                  { text: "开发指南", link: "/zh/docs-development" },
                ],
              },
              {
                text: "容器构建与容器化开发",
                items: [
                  { text: "镜像构建", link: "/zh/deployment/docker-build" },
                  { text: "容器开发", link: "/zh/deployment/devcontainer" },
                ],
              },
              {
                text: "测试",
                items: [
                  { text: "概览", link: "/zh/testing/overview" },
                  { text: "后端测试", link: "/zh/testing/backend" },
                ],
              },
            ],
          },
          {
            text: "第三方集成",
            collapsed: false,
            items: [
              {
                text: "集成概览",
                link: "/zh/integration/",
              },
              {
                text: "资源接入指南",
                link: "/zh/integration/integration-in/overview",
                items: [
                  {
                    text: "MCP 服务接入",
                    link: "/zh/integration/integration-in/mcp",
                  },
                  {
                    text: "Skill 技能接入",
                    link: "/zh/integration/integration-in/skills",
                  },
                  {
                    text: "Agent 智能体接入",
                    link: "/zh/integration/integration-in/agents",
                  },
                ],
              },
              {
                text: "导出与发布指南",
                link: "/zh/integration/integration-out/overview",
                items: [
                  {
                    text: "Agent 导出",
                    link: "/zh/integration/integration-out/agents-export",
                  },
                  {
                    text: "Agent 发布",
                    link: "/zh/integration/integration-out/agents-publish",
                  },
                  {
                    text: "调用 Agent 北向 API",
                    link: "/zh/integration/integration-out/northbound-api",
                  },
                ],
              },
            ],
          },
          {
            text: "SDK 文档",
            collapsed: false,
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
              { text: "OpenTelemetry 设计", link: "/zh/sdk/opentelemetry-design" },
              { text: "向量数据库", link: "/zh/sdk/vector-database" },
              { text: "数据处理", link: "/zh/sdk/data-process" },
            ],
          },
          {
            text: "社区",
            collapsed: false,
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
