# 文档开发指南

## 📘 简介
我们使用 VitePress 进行文档的开发与管理，统一组织中英文内容、侧边栏与导航配置，支持本地开发预览与构建发布。本文档指导你如何在本项目中新增、编辑与校验文档。

## 🗂️ 目录结构
```text
/doc
  ├─ package.json
  └─ docs
      ├─ .vitepress
      │   └─ config.mts        # 站点与侧边栏配置
      ├─ zh                    # 中文文档目录
      ├─ en                    # 英文文档目录
      ├─ assets                # 站点资源
      ├─ public                # 公共静态资源
      └─ index.md
```

## 📦 安装依赖
在 `doc` 目录下执行：

```bash
pnpm install
```

## 💻 本地开发
启动本地开发服务器：

```bash
pnpm vitepress dev docs
```

启动成功后，请通过以下地址访问：

- `http://localhost:5173/`

## ✍️ 新增与编辑文档
- 中文文档放在 `doc/docs/zh`，英文文档放在 `doc/docs/en`。
- 文件命名建议使用小写短横线（kebab-case），例如：`getting-started.md`。
- 页面路径与文件路径一一对应，例如：
  - `doc/docs/zh/foo/bar.md` 将通过 `/zh/foo/bar` 访问；
  - `doc/docs/en/foo/bar.md` 将通过 `/en/foo/bar` 访问。

## 🧭 配置侧边栏与导航
- 侧边栏配置位于 `doc/docs/.vitepress/config.mts`。
- 若新增页面，请在对应语言的 `sidebar` 中添加链接项，注意与文件路径一致。

## 🖼️ 使用资源
- 推荐将公共图片放到 `doc/docs/public`，通过绝对路径引用，例如：`/images/logo.png`。
- 也可以将与页面紧密相关的资源放入同级目录，并使用相对路径引用。

## ✅ 构建与校验
在正式提交前请进行构建，以检查死链（dead links）等问题：

```bash
pnpm run docs:build
```

构建成功后可本地预览：

```bash
pnpm run docs:preview
```
