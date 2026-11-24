# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Isolated UTF-8 files for native file-tool trials; one directory per execution."""
import hashlib
import json
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory
from threading import Lock


FILE_CLASSES = {"CreateFileTool", "ReadFileTool", "DeleteFileTool"}
MAX_FILES = 32
MAX_BYTES = 256 * 1024


def file_name(value):
    if (not isinstance(value, str) or not value or len(value) > 128 or value.startswith(".")
            or value.endswith((" ", ".")) or PureWindowsPath(value).is_reserved()
            or any(ord(c) < 32 or c in '/\\:*?"<>|' for c in value)):
        raise ValueError("Choose a portable filename without directories")
    return value


def validate_files(files):
    if len(files) > MAX_FILES or len({name.casefold() for name in files}) != len(files):
        raise ValueError("Choose up to 32 distinct filenames")
    size = 0
    for name, content in files.items():
        file_name(name)
        size += len(content.encode("utf-8"))
    if size > MAX_BYTES:
        raise ValueError("Replay text files exceed the total byte limit")
    return files


def files_digest(files):
    return hashlib.sha256(json.dumps(files, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


class ReplayFileDirectory:
    def __init__(self, initial):
        validate_files(initial)
        self.temp = TemporaryDirectory(prefix="nexent-file-trial-")
        self.root = Path(self.temp.name)
        self.input_paths = {}
        self.input_names = {}
        self.bound = set()
        self.writes = set()
        self.writes_by_tool = {}
        self.unsupported_call = False
        self.lock = Lock()
        try:
            for name, value in initial.items():
                (self.root / name).write_bytes(value.encode())
            self.initial_digest = files_digest(self.read_files())
            if self.initial_digest != files_digest(initial):
                raise ValueError("Replay file reset failed")
        except BaseException:
            self.close()
            raise

    def close(self):
        self.temp.cleanup()

    def read_files(self):
        files = {}
        remaining = MAX_BYTES
        for path in self.root.iterdir():
            name = file_name(path.name)
            if len(files) >= MAX_FILES or path.is_symlink() or not path.is_file():
                raise ValueError("Unexpected entry in the replay files")
            with path.open("rb") as source:
                data = source.read(remaining + 1)
            if len(data) > remaining:
                raise ValueError("Replay result exceeds the file budget")
            files[name] = data.decode()
            remaining -= len(data)
        return validate_files(files)

    def bind(self, tool, class_name):
        if class_name not in FILE_CLASSES or type(tool).__name__ != class_name:
            raise ValueError("Unsupported replay file binding")

        def resolve(path):
            if class_name == "ReadFileTool" and isinstance(path, str) and path in self.input_paths:
                target = self.input_paths[path]
                if target.is_symlink() or not target.is_file():
                    self.unsupported_call = True
                    raise ValueError("Prepared replay input is unavailable")
                return str(target)
            try:
                name = file_name(path.removeprefix("/replay/") if isinstance(path, str) else path)
            except ValueError:
                self.unsupported_call = True
                raise
            target = self.root / name
            if target.is_symlink():
                self.unsupported_call = True
                raise ValueError("Invalid replay file")
            if class_name != "ReadFileTool":
                with self.lock:
                    if len(self.writes) >= MAX_FILES and name not in self.writes:
                        self.unsupported_call = True
                        raise ValueError("Too many modified files")
                    self.writes.add(name)
                    self.writes_by_tool.setdefault(tool.name, set()).add(name)
            return str(target)

        tool.init_path = str(self.root)
        tool.workspace_mapping = self
        tool._validate_path = resolve
        self.bound.add(class_name)

    def add_input(self, relative_path, local_path, displayed_path):
        """Expose one prepared attachment to the read tool without adding it to writable state."""
        target = Path(local_path)
        if target.is_symlink() or not target.is_file():
            raise ValueError("Prepared replay input is unavailable")
        for alias in (relative_path, f"/{relative_path}", str(target), displayed_path, f"/replay/{relative_path}"):
            self.input_paths[alias] = target
        self.input_names[target] = relative_path

    def unsupported(self, *args, **kwargs):
        self.unsupported_call = True
        raise ValueError("This operation requires a different replay state adapter")

    def relative_path(self, path):
        path = Path(path)
        return self.input_names[path] if path in self.input_names else path.relative_to(self.root).as_posix()

    def to_container(self, path):
        return "/replay/" + self.relative_path(path)

    def receipt(self):
        return {"initial_digest": self.initial_digest, "files": self.read_files(), "complete": not self.unsupported_call,
                "writes_by_tool": {tool: sorted(names) for tool, names in self.writes_by_tool.items()},
                "bound": sorted(self.bound), "writes": sorted(self.writes)}
