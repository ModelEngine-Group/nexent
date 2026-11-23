"""D1 SDK unit contracts. All I/O clients are fakes owned by the test."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
import sys
import types
from io import BytesIO

import pytest


STAGE = pytest.mark.stage("D1")


def _data_process_classes():
    """Import focused processors without loading optional OCR/image dependencies."""
    from shared.config import repo_root

    package_name = "nexent.data_process"
    package = types.ModuleType(package_name)
    package.__path__ = [str(repo_root() / "sdk" / "nexent" / "data_process")]
    sys.modules[package_name] = package
    json_module = importlib.import_module(f"{package_name}.json_chunk_processor")
    excel_module = importlib.import_module(f"{package_name}.openpyxl_processor")
    return json_module.JSONChunkProcessor, excel_module.OpenPyxlProcessor


def _reset_skill_manager() -> None:
    from nexent.skills.skill_manager import SkillManager

    SkillManager._instance = None






@STAGE
@pytest.mark.case_id("UT-SDK-003")
def test_skill_loader_rejects_invalid_manifest_and_path_escape(tmp_path) -> None:
    from nexent.skills.skill_loader import SkillLoader
    from nexent.skills.skill_manager import SkillManager

    with pytest.raises(ValueError, match="frontmatter"):
        SkillLoader.parse("plain markdown")
    with pytest.raises(ValueError, match="name"):
        SkillLoader.parse("---\ndescription: missing name\n---\nbody")
    _reset_skill_manager()
    manager = SkillManager(str(tmp_path))
    for unsafe in ("../escape", "a/b", "C:\\escape", "", ".."): 
        with pytest.raises(ValueError):
            manager.resolve_skill_dir(unsafe, tenant_id="tenant")
    _reset_skill_manager()






def _schedule(rule_type, *, start, interval=None, cron=None, max_count=None, zone="UTC"):
    from nexent.scheduler.triggers import ScheduleMode, ScheduleSpec

    return ScheduleSpec(
        mode=ScheduleMode.ONCE if rule_type.value == "AT" else ScheduleMode.RECURRING,
        rule_type=rule_type, timezone=zone, start_at=start,
        interval_seconds=interval, cron_expr=cron, max_fire_count=max_count,
    )










class _FakeStorage:
    def __init__(self, payload: bytes = b"payload"):
        self.payload = payload
        self.uploads: list[tuple[str, str, bytes]] = []

    def get_file_stream(self, object_name, bucket):
        return True, BytesIO(self.payload)

    def upload_fileobj(self, file_obj, object_name, bucket):
        self.uploads.append((bucket, object_name, file_obj.read()))
        return True, f"s3://{bucket}/{object_name}"
















