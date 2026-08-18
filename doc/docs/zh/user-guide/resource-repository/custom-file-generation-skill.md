---
title: 自定义文件生成 Skill 指南
---

# 自定义文件生成 Skill 指南

本文面向需要扩展文件生成能力的开发者。Nexent 的文件生成 Skill 可将生成结果作为 artifact 上传，并以附件形式推送到对话前端、保存到会话历史。

[`create-docx`](./create-docx.md) 提供了 Word 文档构建的基础脚本，可作为扩展 Word 文档能力的参考。您也可以按本文约定开发用于生成或导出其他文件类型的 Skill，例如 Markdown、PDF、表格、演示文稿、图片、音频、视频、压缩包、代码和数据集。

## 适用场景

当 Skill 的某个脚本需要生成可供用户下载或预览的最终文件时，应按照本文声明文件输出。仅执行分析、修改工作目录中的中间文件或返回文本结果的脚本，不应声明为文件生成脚本。

## 工作原理

文件从生成到前端显示经过以下步骤：

1. 在 `SKILL.md` 的 `script_outputs` 中声明允许产出文件的脚本、artifact 类型和 MIME 类型。
2. 智能体通过 `run_skill_script` 执行该脚本。
3. 脚本生成文件并返回成功 JSON，其中包含 `artifacts` 数组。
4. Nexent SDK 检查脚本是否已声明、artifact 是否完整、文件是否存在、文件大小是否一致，以及 MIME 类型是否已声明。
5. 校验通过的 artifact 以 `skill_artifact` 结构化事件发布。
6. 后端上传文件到对象存储，并发送 `skill_files` 流事件、写入会话附件。
7. 前端根据 MIME 类型和文件名提供下载或预览入口。

普通文本、执行日志和脚本标准输出中的 JSON 不会被自动转换为文件附件。只有通过 `skill_artifact` 事件发布的结果才会显示在附件区域。

## 技能包结构

以 ZIP 包上传包含脚本的 Skill。推荐目录结构如下：

```text
report-generator/
├── SKILL.md
├── scripts/
│   ├── generate_report.py
│   └── publish_report.py
├── requirements.txt
└── examples.md
```

`SKILL.md` 位于技能根目录。`script_outputs` 中的脚本路径相对技能根目录，统一使用正斜杠，例如 `scripts/generate_report.py`。

## 声明文件输出

文件生成能力由 `script_outputs` 声明。键为脚本相对路径，值定义该脚本可发布的 artifact 类型和 MIME 类型。

```yaml
---
name: report-generator
description: Generate downloadable reports from structured input.
script_outputs:
  scripts/generate_report.py:
    kind: file
    mime_types:
      - application/pdf
---
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| 脚本路径 | 是 | 相对 Skill 根目录的路径，必须与 `run_skill_script` 传入的路径匹配。 |
| `kind` | 是 | 文件交付固定填写为 `file`。 |
| `mime_types` | 建议必填 | 该脚本允许发布的 MIME 类型列表；运行时 artifact 的 `mime_type` 必须在此列表中。 |

同一脚本可以声明多个 MIME 类型，例如同时支持 CSV 和 XLSX：

```yaml
script_outputs:
  scripts/export_data.py:
    kind: file
    mime_types:
      - text/csv
      - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
```

声明路径和调用路径在比较前会去除开头的 `./` 并统一为正斜杠。因此 `scripts/generate_report.py` 和 `./scripts/generate_report.py` 都可以匹配同一声明；仍建议始终使用 `scripts/...`，避免文档与实现不一致。

## 返回 artifact

已声明的文件生成脚本必须在成功时输出 JSON 对象。顶层 `status` 必须为 `success`，生成文件放入 `artifacts` 数组。

```json
{
  "status": "success",
  "artifacts": [
    {
      "kind": "file",
      "absolute_path": "/mnt/nexent/output/monthly-report.docx",
      "file_name": "monthly-report.docx",
      "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "file_size_bytes": 12800
    }
  ]
}
```

### 顶层字段

| 字段 | 必填 | 要求 |
| --- | --- | --- |
| `status` | 是 | 必须为字符串 `success`。其他值不会发布 artifact。 |
| `artifacts` | 是 | 必须为数组，可包含一个或多个文件 artifact。 |

可增加 `message`、`file_path` 等供模型阅读的字段，但附件发布只读取 `artifacts`。

### artifact 字段

| 字段 | 必填 | 要求 |
| --- | --- | --- |
| `kind` | 是 | 固定为字符串 `file`。 |
| `absolute_path` | 是 | 已生成文件的绝对路径，必须位于 Nexent 允许上传的工作目录。 |
| `file_name` | 是 | 前端显示和下载使用的文件名，不能为空。 |
| `mime_type` | 是 | 文件真实 MIME 类型，必须符合脚本声明的 `mime_types`。 |
| `file_size_bytes` | 是 | 非负整数，必须等于文件实际字节大小。 |

`file_size_bytes` 不能是布尔值、字符串或估算值。SDK 会在发布前读取磁盘文件大小并进行精确比较。

## Python 脚本示例

以下示例创建文本报告，并打印符合契约的 JSON。生成其他格式时，使用相应的文件生成库和 MIME 类型。

```python
from __future__ import annotations

import json
from pathlib import Path

MIME_TYPE = "text/plain"


def main() -> None:
    output_path = Path("/mnt/nexent/output/summary.txt")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("Generated report\n", encoding="utf-8")

    print(json.dumps({
        "status": "success",
        "artifacts": [{
            "kind": "file",
            "absolute_path": str(output_path.resolve()),
            "file_name": output_path.name,
            "mime_type": MIME_TYPE,
            "file_size_bytes": output_path.stat().st_size,
        }],
    }))


if __name__ == "__main__":
    main()
```

对应的 `SKILL.md` 必须声明该脚本：

```yaml
script_outputs:
  scripts/generate_summary.py:
    kind: file
    mime_types:
      - text/plain
```

## 在 SKILL.md 中指导智能体

Frontmatter 用于运行时校验，`SKILL.md` 正文用于指导智能体选择和调用脚本。对于文件生成脚本，正文应说明何时调用、通过 `params` 传递哪些参数，以及需要直接返回脚本的 `artifacts` 结果。

如果 Skill 包含编辑脚本和最终导出脚本，只将最终导出脚本声明为 `kind: file`。编辑脚本可以修改工作文件，但不应直接生成附件；完成编辑后，调用已声明的导出或发布脚本。

## 常用 MIME 类型

| 文件类型 | MIME 类型 |
| --- | --- |
| PDF | `application/pdf` |
| DOCX | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| XLSX | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| PPTX | `application/vnd.openxmlformats-officedocument.presentationml.presentation` |
| CSV | `text/csv` |
| JSON | `application/json` |
| ZIP | `application/zip` |
| PNG | `image/png` |
| JPEG | `image/jpeg` |
| Markdown | `text/markdown` |
| 纯文本 | `text/plain` |

确保文件扩展名、实际文件内容和 `mime_type` 三者一致。前端将结合 MIME 类型和文件名选择附件图标、下载及预览行为。

## 常见问题

| 问题 | 结果 | 处理方式 |
| --- | --- | --- |
| 脚本未在 `script_outputs` 中声明 | SDK 不发布 artifact | 添加完全匹配的脚本路径及 `kind: file`。 |
| `kind` 不是 `file` | SDK 忽略 artifact | 将脚本声明和 artifact 字段均设为 `file`。 |
| `status` 不是 `success` | SDK 忽略 artifact | 仅在文件成功写入后返回成功状态。 |
| 缺少必填 artifact 字段 | SDK 忽略该 artifact | 返回完整的五个字段。 |
| 文件不存在 | SDK 忽略 artifact | 在输出 JSON 前确认文件已写入。 |
| 文件大小不匹配 | SDK 忽略 artifact | 使用实际的 `stat().st_size` 填充字段。 |
| MIME 未声明 | SDK 忽略 artifact | 将实际 MIME 类型加入该脚本的 `mime_types`。 |
| 路径不允许上传 | 后端拒绝上传 | 将输出写入 Nexent 允许上传的工作目录。 |
| 仅打印路径或日志 JSON | 不会生成附件 | 返回完整的 `artifacts` 数组。 |

## 发布前检查清单

- [ ] `SKILL.md` 使用 `script_outputs`，不使用 Skill 级旧输出字段。
- [ ] 每个可交付文件的脚本路径都已声明为 `kind: file`。
- [ ] 每个脚本的 `mime_types` 包含所有可能输出的实际 MIME 类型。
- [ ] 脚本仅在文件写入完成后输出 `status: success`。
- [ ] 每个 artifact 含 `kind`、`absolute_path`、`file_name`、`mime_type` 和 `file_size_bytes`。
- [ ] `file_size_bytes` 与磁盘实际大小完全一致。
- [ ] 输出路径位于运行环境允许上传的目录。
- [ ] 使用真实对话验证前端能接收并显示附件。

## 相关文档

- [create-docx 官方技能](./create-docx.md)
- [官方技能](./official-skills.md)
- [Skill 仓库](./skill-repository.md)
- [技能系统概览](/zh/backend/skills/overview)
- [智能体配置](../agent-development/agent-configuration.md)
