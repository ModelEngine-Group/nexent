---
title: Custom File Generation Skill Guide
---

# Custom File Generation Skill Guide

This guide is for developers who want to extend file generation capabilities. A Nexent file generation skill can upload its results as an artifact, push them to the conversation frontend as attachments, and save them to the conversation history.

[`create-docx`](./create-docx.md) provides base scripts for building Word documents and can serve as a reference for extending Word capabilities. You can also develop skills that generate or export other file types following the conventions in this guide — for example Markdown, PDF, spreadsheets, presentations, images, audio, video, archives, code, and datasets.

## When to use this

Declare file output as described here whenever a skill script produces a final file that users can download or preview. Scripts that only perform analysis, modify intermediate files in the working directory, or return text results should not be declared as file-generation scripts.

## How it works

Files go through the following steps from generation to frontend display:

1. Declare the scripts that may produce files, along with artifact kinds and MIME types, in `script_outputs` inside `SKILL.md`.
2. The agent executes the script through `run_skill_script`.
3. The script generates the file and returns a success JSON containing an `artifacts` array.
4. The Nexent SDK checks whether the script is declared, whether the artifact is complete, whether the file exists, whether the file size matches, and whether the MIME type is declared.
5. Validated artifacts are published as a structured `skill_artifact` event.
6. The backend uploads the file to object storage, sends a `skill_files` stream event, and writes the conversation attachment.
7. The frontend provides download or preview entries based on the MIME type and file name.

Plain text, execution logs, and JSON printed to script stdout are not automatically converted into attachments. Only results published through the `skill_artifact` event appear in the attachment area.

## Skill package structure

Upload skills containing scripts as a ZIP package. The recommended directory layout:

```text
report-generator/
├── SKILL.md
├── scripts/
│   ├── generate_report.py
│   └── publish_report.py
├── requirements.txt
└── examples.md
```

`SKILL.md` sits at the skill root. Script paths inside `script_outputs` are relative to the skill root and always use forward slashes, e.g. `scripts/generate_report.py`.

## Declaring file output

File generation capability is declared through `script_outputs`. The key is the script's relative path; the value defines the artifact kinds and MIME types the script may publish.

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

| Field | Required | Description |
| --- | --- | --- |
| Script path | Yes | Path relative to the skill root; must match the path passed to `run_skill_script`. |
| `kind` | Yes | Fixed value `file` for file delivery. |
| `mime_types` | Strongly recommended | MIME types the script may publish; an artifact's runtime `mime_type` must be in this list. |

A single script can declare multiple MIME types, for example CSV and XLSX:

```yaml
script_outputs:
  scripts/export_data.py:
    kind: file
    mime_types:
      - text/csv
      - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
```

Declared paths and invoked paths are compared after stripping a leading `./` and normalizing to forward slashes, so `scripts/generate_report.py` and `./scripts/generate_report.py` both match the same declaration. We still recommend always using `scripts/...` to keep documentation and implementation consistent.

## Returning artifacts

A declared file-generation script must output a JSON object on success. The top-level `status` must be `success`, with generated files placed in the `artifacts` array.

```json
{
  "status": "success",
  "artifacts": [
    {
      "kind": "file",
      "absolute_path": "/mnt/nexent/workdir/user/run/outputs/monthly-report.docx",
      "file_name": "monthly-report.docx",
      "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "file_size_bytes": 12800
    }
  ]
}
```

### Top-level fields

| Field | Required | Requirement |
| --- | --- | --- |
| `status` | Yes | Must be the string `success`. Any other value prevents artifact publication. |
| `artifacts` | Yes | Must be an array with one or more file artifacts. |

You may add fields such as `message` or `file_path` for the model to read, but attachment publication reads only `artifacts`.

### Artifact fields

| Field | Required | Requirement |
| --- | --- | --- |
| `kind` | Yes | Fixed string `file`. |
| `absolute_path` | Yes | Absolute path of the generated file; must be inside the working directory Nexent allows for uploads. |
| `file_name` | Yes | File name used for display and download in the frontend; must not be empty. |
| `mime_type` | Yes | The file's real MIME type; must match the script's declared `mime_types`. |
| `file_size_bytes` | Yes | Non-negative integer equal to the file's actual size in bytes. |

`file_size_bytes` must not be a boolean, a string, or an estimate. The SDK reads the file size from disk and compares it exactly before publishing.

## Python script example

The following example creates a text report in the current workspace and prints contract-compliant JSON. When generating other formats, use the appropriate file generation libraries and MIME types.

```python
from __future__ import annotations

import json
import os
from pathlib import Path

MIME_TYPE = "text/plain"


def main() -> None:
    workspace = Path(os.environ.get("NEXENT_WORKSPACE") or Path.cwd())
    output_dir = Path(os.environ.get("NEXENT_OUTPUT_DIR") or workspace / "outputs")
    output_path = output_dir / "summary.txt"
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

The corresponding `SKILL.md` must declare the script:

```yaml
script_outputs:
  scripts/generate_summary.py:
    kind: file
    mime_types:
      - text/plain
```

## Guiding the agent in SKILL.md

Frontmatter is used for runtime validation; the `SKILL.md` body guides the agent in choosing and invoking scripts. For file-generation scripts, the body should explain when to invoke the script, which parameters to pass via `params`, and that the script's `artifacts` result must be returned directly.

If the skill contains both editing scripts and a final export script, declare only the final export script as `kind: file`. Editing scripts may modify working files but should not produce attachments directly; after editing, invoke the declared export or publish script.

## Common MIME types

| File type | MIME type |
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
| Plain text | `text/plain` |

Keep the file extension, actual file content, and `mime_type` consistent. The frontend combines the MIME type and file name to choose the attachment icon, download, and preview behavior.

## FAQ

| Problem | Result | How to fix |
| --- | --- | --- |
| Script not declared in `script_outputs` | SDK does not publish the artifact | Add the exact script path with `kind: file`. |
| `kind` is not `file` | SDK ignores the artifact | Set both the script declaration and artifact field to `file`. |
| `status` is not `success` | SDK ignores the artifact | Return success only after the file is written. |
| Missing required artifact fields | SDK ignores the artifact | Return all five fields. |
| File does not exist | SDK ignores the artifact | Confirm the file is written before outputting the JSON. |
| File size mismatch | SDK ignores the artifact | Fill the field with the actual `stat().st_size`. |
| MIME not declared | SDK ignores the artifact | Add the actual MIME type to the script's `mime_types`. |
| Path not allowed for upload | Backend rejects the upload | Write outputs to a working directory Nexent allows for uploads. |
| Only paths or log JSON printed | No attachment is generated | Return the complete `artifacts` array. |

## Pre-publication checklist

- [ ] `SKILL.md` uses `script_outputs`, not the legacy skill-level output fields.
- [ ] Every script that delivers a file is declared with `kind: file`.
- [ ] Each script's `mime_types` includes all actual MIME types it may output.
- [ ] Scripts output `status: success` only after files are fully written.
- [ ] Every artifact contains `kind`, `absolute_path`, `file_name`, `mime_type`, and `file_size_bytes`.
- [ ] `file_size_bytes` exactly matches the on-disk size.
- [ ] Output paths are inside directories allowed for upload in the runtime environment.
- [ ] Verified in a real conversation that the frontend receives and displays the attachment.

## Related documents

- [create-docx Official Skill](./create-docx.md)
- [Official Skills](./official-skills.md)
- [Skill Space](./skill-repository.md)
- [Skills System Overview](/en/backend/skills/overview)
- [Agent Configuration](../agent-configuration.md)
