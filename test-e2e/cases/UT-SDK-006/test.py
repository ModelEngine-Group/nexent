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












def _schedule(rule_type, *, start, interval=None, cron=None, max_count=None, zone="UTC"):
    from nexent.scheduler.triggers import ScheduleMode, ScheduleSpec

    return ScheduleSpec(
        mode=ScheduleMode.ONCE if rule_type.value == "AT" else ScheduleMode.RECURRING,
        rule_type=rule_type, timezone=zone, start_at=start,
        interval_seconds=interval, cron_expr=cron, max_fire_count=max_count,
    )


@STAGE
@pytest.mark.case_id("UT-SDK-006")
def test_once_interval_and_cron_next_fire_time() -> None:
    from nexent.scheduler.triggers import ScheduleRuleType, compute_next_fire_at

    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    once = _schedule(ScheduleRuleType.AT, start=start)
    assert compute_next_fire_at(once, start, 0) == start
    assert compute_next_fire_at(once, start, 1) is None
    interval = _schedule(ScheduleRuleType.INTERVAL, start=start, interval=300)
    assert compute_next_fire_at(interval, start, 0) == start
    after_first_fire = start + timedelta(seconds=1)
    assert compute_next_fire_at(interval, after_first_fire, 1).minute == 5
    cron = _schedule(ScheduleRuleType.CRON, start=start, cron="0 2 * * *")
    assert compute_next_fire_at(cron, start, 0).hour == 2








class _FakeStorage:
    def __init__(self, payload: bytes = b"payload"):
        self.payload = payload
        self.uploads: list[tuple[str, str, bytes]] = []

    def get_file_stream(self, object_name, bucket):
        return True, BytesIO(self.payload)

    def upload_fileobj(self, file_obj, object_name, bucket):
        self.uploads.append((bucket, object_name, file_obj.read()))
        return True, f"s3://{bucket}/{object_name}"
















