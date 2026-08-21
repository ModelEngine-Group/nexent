# 知识库预览体验修复 - 技术设计

## 前端样式

在 `frontend/const/knowledgeBase.ts` 中将原有共用的危险操作样式拆分为：

- `ACTION_PREVIEW_TEXT`：中性/主题色文字样式。
- `ACTION_DELETE_TEXT`：红色危险操作样式。

在 `DocumentList.tsx` 中分别应用两个常量。

## 后端 MIME 白名单

在 `backend/services/file_management_service.py` 的 `resolve_preview_file` 中维护直接预览 MIME 集合，并加入 `application/json`。JSON 不进入 Office 转换分支，直接返回原 MinIO 对象。

本次不加入 `application/xml`，避免扩大需求范围。

## 测试设计

- 在 `test/backend/services/test_file_management_service.py` 的直接预览参数化测试中加入 JSON 用例。
- 运行该服务测试文件，确认 JSON 返回原对象和 `application/json`。
- 运行前端类型检查和格式检查，确认样式常量引用正确。
- 如本地前端服务可用，使用浏览器验证按钮颜色和 JSON 文本预览；不修改用户当前工作区的运行服务。
