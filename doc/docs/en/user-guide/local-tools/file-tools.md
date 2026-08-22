---
title: File Tools
---

# File Tools

File tools provide safe, workspace-scoped operations for files and folders. All paths must be relative to the workspace root (default `/mnt/nexent`).

## 🧭 Tool List

- `create_directory`: Create directories (auto-create parents, optional permissions)
- `create_file`: Create files and write content (auto-create parents)
- `read_file`: Read file content with metadata
- `list_directory`: Show directory tree
- `move_item`: Move files/folders without overwriting
- `delete_file`: Delete a single file (irreversible)
- `delete_directory`: Recursively delete a directory (irreversible)

## 🧰 Example Use Cases

- Initialize project folders and config files
- Inspect logs or check file size/line counts
- Browse workspace structure before editing
- Move artifacts to backup locations
- Clean up temp files or unused directories

## 🧾 Parameters & Behavior

### Common constraints
- Paths must stay inside the workspace; absolute or escaping paths are blocked.
- Delete/move operations are irreversible—double-check before running.

### Key parameters
- `directory_path` / `file_path` / `source_path` / `destination_path`: required relative paths.
- `permissions` (`create_directory`): octal string, default `755`.
- `encoding` (`create_file` / `read_file`): default `utf-8`.
- `max_depth`, `show_hidden`, `show_size` (`list_directory`): control tree depth, hidden items, and size display.

### Returns
- Success responses include relative/absolute paths, sizes, and existence flags.
- Errors explain boundary checks, existing targets, or permission issues.

## 🛠️ How to Use

1. **Create**: Use `create_directory` or `create_file` with a relative path; set permissions/encoding when needed.
2. **Inspect**: Use `list_directory` to browse; use `read_file` for content and metadata.
3. **Move**: Use `move_item`; it stops if the destination already exists to avoid overwrites.
4. **Delete**: Use `delete_file` or `delete_directory`; confirm the target since deletion cannot be undone.

## 🛡️ Safety & Best Practices

- Operate only inside the workspace; avoid absolute paths or `..` traversal.
- Before deleting, run `list_directory` or `read_file` to confirm the target.
- Large files trigger warnings; consider chunked processing instead of single full reads.

