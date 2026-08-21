# 知识库预览体验修复 - 开发计划

## Phase 概览

| Phase | 名称 | 状态 | 依赖 |
|---|---|---|---|
| Phase 1 | 修复预览操作样式与 JSON MIME | 已完成 | - |
| Phase 2 | 单元测试与前端静态验证 | 已完成 | Phase 1 |

## Phase 1: 修复预览操作样式与 JSON MIME

- 拆分预览和删除按钮样式常量。
- 将 JSON MIME 加入直接预览白名单。
- 保持 XML 和其他未请求格式不变。

## Phase 2: 单元测试与前端静态验证

- 增加 JSON 直接预览单元测试。
- 执行后端相关 pytest。
- 执行前端 type-check/format-check；条件允许时使用浏览器验证用户可见行为。

## 验收标准

[x] 预览按钮使用非红色样式，删除按钮仍为红色样式。
[x] JSON 预览接口返回原对象和 `application/json`。
[x] JSON 前端显示原始文本。
[x] 相关测试和静态检查通过。

## 实现笔记

- 后端服务单测通过：`112 passed`。
- 前端 TypeScript 检查通过；`DocumentList.tsx` 的 Prettier 告警来自 develop 基线，本次保留最小变更，未进行无关格式化。
- Playwright 已验证独立 worktree 的 Next 页面可以编译和加载；真实文档列表需要认证/配置后端，当前临时前端未接入独立后端，因此未执行点击 JSON 文件的端到端验证。
