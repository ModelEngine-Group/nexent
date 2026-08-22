---
title: Multimodal Tools
---

# Multimodal Tools

Multimodal tools analyze text files, images, videos, and audio with model support. URLs can be S3, HTTP, or HTTPS.

## 🧭 Tool List

- `analyze_text_file`: Download and extract text, then analyze per question
- `analyze_image`: Download images and interpret them with a vision-language model
- `analyze_video`: Download videos and analyze them with a video understanding model
- `analyze_audio`: Download audio and analyze it with an audio understanding model

## 🧰 Example Use Cases

- Summarize documents stored in buckets
- Explain screenshots, product photos, or chart images
- Understand video content, such as extracting key frame information, human actions, or scene descriptions
- Analyze audio content, such as transcription, speaker identification, or content summarization
- Produce per-file or per-image/video/audio answers aligned with the input order

## 🧾 Parameters & Behavior

### analyze_text_file
- `file_url_list`: List of URLs (`s3://bucket/key`, `/bucket/key`, `http(s)://`).
- `query`: User question/analysis goal.
- Downloads each file, extracts text, and returns an array of analyses in input order.

### analyze_image
- `image_urls_list`: List of URLs (`s3://bucket/key`, `/bucket/key`, `http(s)://`).
- `query`: User focus/question.
- Downloads each image, runs VLM analysis, and returns an array matching input order.

### analyze_video
- `video_url`: Video URL (`s3://bucket/key`, `/bucket/key`, `http(s)://`).
- `query`: User focus/question.
- Downloads the video, runs video understanding model analysis, and returns the result.

### analyze_audio
- `audio_url`: Audio URL (`s3://bucket/key`, `/bucket/key`, `http(s)://`).
- `query`: User focus/question.
- Downloads the audio, runs audio understanding model analysis, and returns the result.

## ⚙️ Prerequisites

- Configure storage access (e.g., MinIO/S3) and data processing service to fetch files.
- Provide an LLM for `analyze_text_file`, a VLM for `analyze_image`, and a video understanding model for `analyze_video` and `analyze_audio` (must support audio/video input, e.g., Qwen3-Omni series).

## 🛠️ How to Use

1. Prepare accessible URLs for files, images, videos, or audio; confirm permissions.
2. Call the corresponding tool with the URL and question; multiple resources are supported at once.
3. Verify results before using them in follow-up steps.

## 💡 Best Practices

- For large files, preprocess or chunk them to reduce timeouts.
- For multiple images, be explicit about the focus (e.g., “focus on chart trends”) to improve answers.
- If results are empty or errors occur, verify URL accessibility and model readiness.

