# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json

import pytest

from nexent.core.agents.resources.replay_files import ReplayFileDirectory
from nexent.core.tools.create_file_tool import CreateFileTool
from nexent.core.tools.delete_file_tool import DeleteFileTool
from nexent.core.tools.read_file_tool import ReadFileTool


def test_real_file_tools_are_isolated_and_cleanup_is_owned():
    initial = {"old.txt":"source", "empty.txt":""}
    base, candidate = ReplayFileDirectory(initial), ReplayFileDirectory(initial)
    try:
        writer = CreateFileTool(init_path=str(base.root), observer=None)
        reader = ReadFileTool(init_path=str(base.root), observer=None)
        delete = DeleteFileTool(init_path=str(base.root), observer=None)
        for tool in (writer, reader, delete):
            candidate.bind(tool, type(tool).__name__)
        result = json.loads(writer.forward("old.txt","changed"))
        assert result["absolute_path"] == "/replay/old.txt"
        assert "changed" in reader.forward(result["absolute_path"])
        delete.forward("empty.txt")
        assert base.read_files() == initial and candidate.read_files() == {"old.txt":"changed"}
        assert candidate.receipt()["complete"]
        with pytest.raises(Exception, match="filename"):
            writer.forward("../other.txt","outside")
        assert candidate.receipt()["writes"] == ["empty.txt","old.txt"]
        assert not candidate.receipt()["complete"]
        with pytest.raises(ValueError):
            candidate.unsupported("unavailable transfer")
        assert not candidate.receipt()["complete"]
    finally:
        base.close()
        candidate.close()
    assert not base.root.exists() and not candidate.root.exists()
