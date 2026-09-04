# Documentation Development Guide

## 📘 Introduction
We use VitePress to develop and manage our documentation. This guide explains how to add, edit, preview, and build docs in this project with a consistent structure for both Chinese and English.

## 🗂️ Project Structure
```text
/doc
  ├─ package.json
  └─ docs
      ├─ .vitepress
      │   └─ config.mts        # Site & sidebar configuration
      ├─ cn                    # Chinese docs
      ├─ en                    # English docs
      ├─ assets                # Site assets
      ├─ public                # Static public assets
      └─ index.md
```

## 📦 Install Dependencies
From the `doc` directory:

```bash
pnpm install
```

## 💻 Local Development
Start the dev server:

```bash
pnpm run docs:dev
```

After successfully start, visit:

- `http://localhost:5173/`

## ✍️ Add or Edit Docs
- Put Chinese docs under `doc/docs/zh` and English docs under `doc/docs/en`.
- Use kebab-case file names, e.g., `getting-started.md`.
- Routes map to file paths, e.g.:
  - `doc/docs/zh/foo/bar.md` → `/zh/foo/bar`
  - `doc/docs/en/foo/bar.md` → `/en/foo/bar`

## 🧭 Sidebar and Navigation
- The sidebar is configured in `doc/docs/.vitepress/config.mts`.
- An entry for this guide has been added right after "Backend Development": `/zh/docs-development` (Chinese) and `/en/docs-development` (English).
- For new pages, add links in the corresponding locale's sidebar and ensure paths match the file locations.

## 🖼️ Assets
- Prefer `doc/docs/public` for shared assets and reference them using absolute paths, e.g., `/images/logo.png`.
- Page-specific assets can live alongside the page and be referenced via relative paths.

## ✅ Build and Validate
Before committing, build the docs to check for dead links and other issues:

```bash
pnpm run docs:build
```

Preview the production build locally:

```bash
pnpm run docs:preview
```
