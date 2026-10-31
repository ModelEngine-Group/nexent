# MCP 服务接入

MCP（Model Context Protocol，模型上下文协议）是 AI 工具的标准通信协议。Nexent 平台支持接入符合 MCP 规范的工具服务，极大地扩展智能体的能力范围。

## 📋 接入方式概览

Nexent 支持多种 MCP 服务接入方式：

| 接入方式 | 适用场景 | 前置条件 |
|----------|----------|----------|
| **远程链接** | 已独立部署的 MCP 服务（HTTP/SSE） | 服务 URL 可访问 |
| **容器化部署** | 以容器方式运行的 MCP 服务 | Docker 环境或镜像 |
| **API 转 MCP** | 将 REST API 转换为 MCP 工具 | OpenAPI 规范文档 |

## 🌐 方式一：远程链接接入

适用于已有独立部署的 MCP 服务，如 ModelScope 提供的 MCP 服务。

### 操作步骤

1. 进入 **MCP 仓库** → **我的 MCP** 页面
2. 点击「添加 MCP 服务」
3. 选择集成类型为「远程」
4. 填写服务配置：

| 配置项 | 说明 | 示例 |
|--------|------|------|
| **服务名称** | MCP 服务的显示名称 | `modelscope-github` |
| **服务 URL** | MCP 服务的 HTTP/SSE 端点地址 | `https://api.modelscope.cn/mcp/sse` |
| **Authorization Token** | 认证令牌（如需要） | `Bearer xxx` |
| **自定义请求头** | 额外的 HTTP 请求头（JSON 格式） | `{"X-API-Key": "xxx"}` |

5. 点击「连通性校验」确认服务可访问
6. 点击「保存」完成添加

### 示例：接入 ModelScope GitHub MCP

ModelScope 提供了丰富的 MCP 服务，以下是接入 GitHub MCP 的示例：

1. 访问 [ModelScope MCP 市场](https://modelscope.cn/mcp) 查找 GitHub MCP
2. 获取服务的 SSE 端点地址
3. 在 Nexent 中填写配置：

```json
{
  "name": "modelscope-github",
  "url": "https://api.modelscope.cn/mcp/servers/github",
  "headers": {}
}
```

4. 完成校验后即可使用

## 🐳 方式二：容器化部署接入

适用于以 Docker 容器方式运行的 MCP 服务，如通过 npx 部署的服务。

### 操作步骤

1. 进入 **MCP 仓库** → **我的 MCP** 页面
2. 点击「添加 MCP 服务」
3. 选择集成类型为「容器」
4. 填写容器配置 JSON：

```json
{
  "mcpServers": {
    "service-name": {
      "command": "npx",
      "args": ["-y", "@modelScope/mcp-server-package@version"]
    }
  }
}
```

5. 填写容器端口号
6. 点击「保存」，系统会自动启动容器并配置

### 端口说明

- **Docker/Kubernetes 部署**：容器端口由系统自动分配，无需手动设置
- **本地部署**：使用推荐端口或手动指定可用端口

## 🔄 方式三：API 转 MCP

这是 Nexent 提供的强大功能，可以将已有的 REST API 快速转换为 MCP 工具，无需编写 MCP Server 代码。

### 适用场景

- 企业内部已有 REST API 接口，希望快速赋予智能体调用能力
- 第三方服务提供 HTTP API 但没有 MCP 适配
- 快速原型验证，需要将 API 能力快速暴露给智能体

### 操作步骤

1. 进入 **智能体开发** → **MCP 配置**
2. 选择集成类型为「API 转换为 MCP」
3. 填写配置：

| 配置项 | 说明 | 示例 |
|--------|------|------|
| **服务名称** | MCP 服务的显示名称 | `company-crm-api` |
| **OpenAPI JSON** | OpenAPI 3.x 规范的 JSON 内容 | （粘贴 JSON） |
| **基础服务 URL** | API 服务的基础地址 | `https://api.example.com` |

4. 点击「添加」完成转换

### OpenAPI 规范要求

转换功能支持 OpenAPI 3.x 规范的以下特性：

- GET/POST/PUT/DELETE 等 HTTP 方法
- Path 参数、Query 参数、Header 参数
- Request Body（JSON 格式）
- 认证信息（Bearer Token、API Key 等）

### 示例：将内部工单系统转换为 MCP

假设您有一个工单系统，OpenAPI 定义如下：

```json
{
  "openapi": "3.0.0",
  "info": {"title": "工单系统", "version": "1.0.0"},
  "paths": {
    "/tickets": {
      "get": {
        "summary": "获取工单列表",
        "parameters": [
          {"name": "status", "in": "query", "schema": {"type": "string"}}
        ]
      },
      "post": {
        "summary": "创建工单",
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "title": {"type": "string"},
                  "description": {"type": "string"}
                }
              }
            }
          }
        }
      }
    }
  }
}
```

转换为 MCP 后，智能体即可通过自然语言调用这些接口，如「查询所有待处理的工单」。

## 🛠️ 管理已接入的 MCP 服务

### 查看服务状态

每张服务卡片会显示以下状态：

| 标识 | 说明 |
|------|------|
| **启用/已启用** | 服务是否启用，禁用后工具不出现在智能体工具选择中 |
| **审核中** | 申请上架待管理员审核 |
| **已上架** | 已在仓库中共享 |
| **审核驳回** | 上架申请未通过 |

### 常用操作

- **编辑**：修改服务配置
- **连通性校验**：测试服务连接状态
- **申请上架**：将服务共享给同租户成员
- **删除**：移除服务（容器化服务会同步清理容器）

## 🤖 在智能体中使用 MCP 工具

### 分配到智能体

1. 进入 **智能体开发** 页面
2. 在「选择智能体的工具」中切换到 **MCP** 页签
3. 找到已添加的 MCP 服务，展开查看工具列表
4. 选择需要的工具，配置必要参数
5. 保存智能体配置

### 工具测试

在分配工具时，可以点击工具卡片的「测试」按钮验证功能：

1. 填写测试参数
2. 点击「执行测试」
3. 查看返回结果

## ⭐ 最佳实践

### 安全建议

1. **保护认证信息**：使用平台的密钥管理功能，避免在配置中明文存储 Token
2. **最小权限原则**：仅申请服务所需的最小权限
3. **定期轮换**：定期更换 API Key 等认证信息

### 性能建议

1. **服务可用性**：确保 MCP 服务稳定可靠，避免拉低智能体响应速度
2. **超时设置**：为耗时操作设置合理的超时时间
3. **错误处理**：利用工具测试功能提前发现并处理问题

### 维护建议

1. **版本管理**：关注 MCP 服务更新，及时升级到稳定版本
2. **日志监控**：监控服务调用日志，发现异常及时处理
3. **依赖管理**：记录服务依赖关系，便于故障排查

## ❓ 常见问题

### Q: MCP 服务连接失败怎么办？

1. 检查服务 URL 是否可访问
2. 确认网络连通性和防火墙配置
3. 验证认证信息是否正确
4. 查看服务是否正常运行

### Q: API 转 MCP 支持哪些认证方式？

当前支持：
- Bearer Token
- API Key（Query/Header）
- Basic Auth

### Q: 如何开发自己的 MCP 服务？

请参阅 [MCP 工具开发](../../backend/tools/mcp) 文档。

## 🔗 相关资源

- [MCP 仓库](../../user-guide/resource-repository/mcp-repository) — 浏览、安装和管理 MCP 服务的详细指导
- [智能体配置](../../user-guide/agent-development/agent-configuration) — 在智能体中使用 MCP 工具
- [MCP 工具开发](../../backend/tools/mcp) — 开发自定义 MCP 服务
- [MCP 生态系统](../../mcp-ecosystem/overview) — 了解更多 MCP 生态
