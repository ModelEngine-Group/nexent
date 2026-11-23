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
@pytest.mark.case_id("UT-SDK-002")
def test_skill_manifest_round_trip_decoding_and_script_trust_boundary(tmp_path) -> None:
    """Manifest/SKILL.md parsing, strict utf-8-sig -> gb18030 decoding, manager
    cache, and resolve_skill_script rejecting escapes / unknown extensions."""
    from nexent.skills.skill_loader import SkillLoader
    from nexent.skills.skill_manager import SkillManager, SkillScriptNotFoundError

    parsed = SkillLoader.parse(
        "---\nname: sample\ndescription: 'does: work'\ntags: [one, two]\nallowed-tools: [Read]\n---\n# Steps"
    )
    assert parsed["name"] == "sample" and parsed["tags"] == ["one", "two"]
    assert parsed["allowed_tools"] == ["Read"]
    rendered = SkillLoader.to_skill_md(parsed)
    assert SkillLoader.parse(rendered)["content"] == "# Steps"
    _reset_skill_manager()
    assert SkillManager(str(tmp_path)) is SkillManager(str(tmp_path / "ignored"))
    _reset_skill_manager()

    # Step 9 + assertion 5: SKILL.md/script text is decoded strictly with the
    # utf-8-sig -> gb18030 fallback chain, and undecodable bytes raise explicitly.
    from nexent.core.tools.read_skill_md_tool import _read_text_file

    skill_root = tmp_path / "skills"
    tenant = skill_root / "tenant-a"
    (tenant / "gbk-skill").mkdir(parents=True)
    gbk_body = "---\nname: gbk-skill\ndescription: GB18030 \u7f16\u7801\u7684\u6280\u80fd\u8bf4\u660e\n---\n\u6b63\u6587\uff1a\u6280\u80fd\u811a\u672c"
    (tenant / "gbk-skill" / "SKILL.md").write_bytes(gbk_body.encode("gb18030"))
    assert _read_text_file(str(tenant / "gbk-skill" / "SKILL.md")) == gbk_body
    loaded_gbk = SkillLoader.load(str(tenant / "gbk-skill" / "SKILL.md"))
    assert loaded_gbk["name"] == "gbk-skill"
    assert "GB18030 \u7f16\u7801\u7684\u6280\u80fd\u8bf4\u660e" in loaded_gbk["description"]

    (tenant / "bom-skill").mkdir()
    (tenant / "bom-skill" / "SKILL.md").write_bytes(b"\xef\xbb\xbf" + gbk_body.encode("utf-8"))
    assert _read_text_file(str(tenant / "bom-skill" / "SKILL.md")) == gbk_body
    assert SkillLoader.load(str(tenant / "bom-skill" / "SKILL.md"))["name"] == "gbk-skill"

    bad_bytes = b"\xf8\xf9\xfa\xfb\xfc\xfd\xfe\xff" * 32
    (tenant / "bad-skill").mkdir()
    (tenant / "bad-skill" / "SKILL.md").write_bytes(bad_bytes)
    with pytest.raises(UnicodeError):
        _read_text_file(str(tenant / "bad-skill" / "SKILL.md"))
    with pytest.raises(ValueError, match="YAML frontmatter"):
        SkillLoader.load(str(tenant / "bad-skill" / "SKILL.md"))

    # Assertion 5 second half: resolve_skill_script rejects escaping paths,
    # files outside the skill root and non .py/.sh extensions explicitly.
    manager = SkillManager(str(skill_root))
    skill_dir = tenant / "runner"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: runner\ndescription: script trust boundary\n---\nbody", encoding="utf-8"
    )
    (skill_dir / "scripts" / "ok.py").write_text("print('ok')\n", encoding="utf-8")
    (skill_dir / "scripts" / "ok.sh").write_text("echo ok\n", encoding="utf-8")
    (skill_dir / "scripts" / "notes.txt").write_text("text", encoding="utf-8")

    local_dir, full_path, normalized = manager.resolve_skill_script(
        "runner", "scripts/ok.py", tenant_id="tenant-a"
    )
    assert normalized.replace("\\", "/") == "scripts/ok.py" and full_path.replace("\\", "/").endswith("ok.py")
    assert local_dir == str(skill_dir.resolve())
    _, _, normalized_sh = manager.resolve_skill_script(
        "runner", "./scripts/ok.sh", tenant_id="tenant-a"
    )
    assert normalized_sh.replace("\\", "/").endswith("ok.sh")

    with pytest.raises(SkillScriptNotFoundError, match="escapes"):
        manager.resolve_skill_script("runner", "../escape.py", tenant_id="tenant-a")
    with pytest.raises(SkillScriptNotFoundError):
        manager.resolve_skill_script("runner", "/etc/passwd.py", tenant_id="tenant-a")
    with pytest.raises(SkillScriptNotFoundError):
        manager.resolve_skill_script("runner", "scripts/missing.py", tenant_id="tenant-a")
    with pytest.raises(ValueError, match="Unsupported script type"):
        manager.resolve_skill_script("runner", "scripts/notes.txt", tenant_id="tenant-a")
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
















