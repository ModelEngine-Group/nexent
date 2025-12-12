---
title: Multimodal Tools
---

# Multimodal Tools

Multimodal tools analyze text files and images with model support. URLs can be S3, HTTP, or HTTPS.

## 🧭 Tool List

- `analyze_text_file`: Download and extract text, then analyze per question
- `analyze_image`: Download images and interpret them with a vision-language model

## 🧰 Example Use Cases

- Summarize documents stored in buckets
- Explain screenshots, product photos, or chart images
- Produce per-file or per-image answers aligned with the input order

## 🧾 Parameters & Behavior

### analyze_text_file
- `file_url_list`: List of URLs (`s3://bucket/key`, `/bucket/key`, `http(s)://`).
- `query`: User question/analysis goal.
- Downloads each file, extracts text, and returns an array of analyses in input order.

### analyze_image
- `image_urls_list`: List of URLs (`s3://bucket/key`, `/bucket/key`, `http(s)://`).
- `query`: User focus/question.
- Downloads each image, runs VLM analysis, and returns an array matching input order.

## ⚙️ Prerequisites

- Configure storage access (e.g., MinIO/S3) and data processing service to fetch files.
- Provide an LLM for `analyze_text_file` and a VLM for `analyze_image`.

## 🛠️ How to Use

1. Prepare accessible URLs and confirm permissions.
2. Call the corresponding tool with the URL list and question; multiple resources are supported at once.
3. Use results in the same order as inputs for display or follow-up steps.

## 💡 Best Practices

- For large files, preprocess or chunk them to reduce timeouts.
- For multiple images, be explicit about the focus (e.g., “focus on chart trends”) to improve answers.
- If results are empty or errors occur, verify URL accessibility and model readiness.

