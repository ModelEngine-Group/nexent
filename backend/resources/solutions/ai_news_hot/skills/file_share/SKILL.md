---
name: file_share
description: >
  Upload a local file to MinIO object storage and return a browser-accessible
  download URL. Use this after create_file to share the generated file with
  the user via a clickable download link.
version: 1.0.0
display_name: "File Share"
---

# File Share

## 能力概述
- 把 `create_file` 生成的本地文件上传到 MinIO 对象存储
- 返回浏览器可直接访问的下载 URL

## 什么时候用
- `create_file` 之后，需要给用户提供下载链接时

## 工作流
1. `create_file(file_path="report.html", content="...")` 创建文件
2. `run_skill_script("file_share", "scripts/upload_and_share.py", "report.html")` 上传 + 获取下载 URL
3. 把返回的 URL 给用户（作为可点击的下载链接）

## 脚本
- `scripts/upload_and_share.py`: 参数为本地文件路径，输出 JSON `{"url": "...", "object_name": "..."}` 或 `{"error": "..."}`
