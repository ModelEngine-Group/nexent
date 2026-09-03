# Skill Integration

Skill is the core mechanism for extending Agent capabilities on the Nexent platform. Nexent supports importing externally developed skill packages, and also lets you leverage the platform's natural-language generation features to create new skills quickly.

## Integration Methods Overview

Nexent supports multiple Skill integration methods:

| Method | Use Case | File Requirements |
|--------|----------|-------------------|
| **Upload SKILL.md** | Single-file skill, simple scenarios | `.md` file containing YAML Front Matter |
| **Upload ZIP Package** | Multi-file skill with scripts and resources | ZIP package containing `SKILL.md` |

## Upload Skill File

### Single-File Skill (.md)

Suitable for simple skills that do not contain scripts or extra resources.

**File Requirements**:
- File name: `SKILL.md` (or any file name)
- Encoding: UTF-8
- Contains YAML Front Matter with required fields: `name`, `description`

**Basic SKILL.md Structure**:

```markdown
---
name: csv-analyzer
description: |
  Analyze CSV files and generate data-quality reports. Use this when a user uploads a CSV file and needs a data check.
tags:
  - data-analysis
  - csv
---

# CSV Data Quality Report

## Function Description

This skill analyzes the data quality of CSV files, including:
- Missing-value statistics
- Duplicate data detection
- Field type analysis

## Usage Example

When a user provides a CSV file, the skill runs a data quality check automatically.
```

### Multi-File Skill (.zip)

Suitable for complex skills that bundle auxiliary content such as scripts and resource files.

**File Structure**:

```
skill-name.zip
├── SKILL.md              # Required: skill definition file
├── config/
│   ├── config.yaml       # Optional: parameter default values
│   └── schema.yaml       # Optional: parameter type definitions
├── scripts/
│   └── analyze.py        # Optional: Python script
├── examples.md           # Optional: usage examples
└── assets/               # Optional: static resources
```

### Steps

1. Navigate to **Skill Repository** → **My Skills** page
2. Click "Create Skill"
3. Select "Upload Skill File"
4. Drag or select a `.md` / `.zip` file
5. The system parses the skill and displays its information automatically
6. Review the parsed result, then click "Create" to confirm

### Notes

- `SKILL.md` must contain valid YAML Front Matter
- The `name` field must not conflict with an existing skill
- `SKILL.md` inside the ZIP package can be located in the root directory or a subdirectory
- Importing will not overwrite a skill with the same name

## SKILL.md Format Reference

Regardless of which integration method is used, the final result is a skill definition in SKILL.md format. Understanding the format helps create higher-quality skills.

### YAML Front Matter

```yaml
---
name: skill-name                    # Required: skill name (English only, lowercase, hyphen-separated)
description: |                     # Required: function description (recommended 1-3 sentences)
  A description that explains what this skill does and when it should be used.
  Recommended to write in the third person.
tags:                              # Optional: tag list
  - tag1
  - tag2
---
```

### Parameter Definition (schema.yaml)

If the skill requires users to fill in parameters, create `config/schema.yaml`:

```yaml
query:
  type: string
  required: true
  description: "Search query string"
  description_zh: "Search keyword"
  default: ""

top_k:
  type: number
  required: false
  description: "Number of results to return"
  description_zh: "Number of returned results"
  default: 3
```

Supported types: `string`, `number`, `boolean`, `array`, `object`

### Parameter Default Values (config.yaml)

```yaml
# Initial working path
init_path: "/mnt/nexent"

# Maximum number of returned items
top_k: 5
```

### Special Tags

#### `<reference>`: Load Files On Demand

```markdown
<reference path="examples.md" />
```

#### `<use_script>`: Declare Bundled Scripts

```markdown
<use_script path="scripts/analyze.py" />
```

#### `<code>`: Show Code Examples

```markdown
<code>
result = run_skill_script(
    "csv-analyzer",
    "scripts/analyze.py",
    {"--file": "/path/to/data.csv"}
)
</code>
```

### Helper Functions

The following functions are available in skills:

- `run_skill_script(skill_name, script_path, params)`: Execute scripts inside a skill package
- `read_skill_md(skill_name, files)`: Read files inside a skill package

## Using Skills in Agents

### Assigning a Skill to an Agent

1. Navigate to **Agent Development** page
2. In "Select Agent's Tools", switch to the **Skills** tab
3. Click "Select Skill"
4. Find and select the target skill
5. If there are required parameters, configure them and save

### Differences Between Skills and Tools

| Dimension | Tool | Skill |
|-----------|------|-------|
| Granularity | A single atomic operation | A combination of multiple tools, configuration, and documentation |
| Token cost | Consumes context on every turn | Only loaded when activated |
| Parameters | Fixed parameter schema | Customizable parameter templates |
| Distribution | Code-level | ZIP package distribution, plug-and-play |

## FAQ

### Q: Uploading a ZIP package fails with "Missing SKILL.md"

Make sure `SKILL.md` exists at the root of the ZIP package instead of being placed in a subfolder.

### Q: The skill description doesn't take effect

The skill description should be written in the YAML Front Matter `description` field, not in the Markdown body.

## Related Resources

- [Agent Configuration](../../user-guide/agent-development/agent-configuration) — Use Skills in Agents
- [Skill System Overview](../../backend/skills/overview) — Deep dive into the Skill mechanism
