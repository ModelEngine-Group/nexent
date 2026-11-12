# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Format terminal metadata independently of launcher modules cached before Git sync."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


def beijing_time(value):
    """Format only explicitly timezone-aware saved timestamps."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return "未记录（原时间缺少时区）"
        return parsed.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S +08:00")
    except (AttributeError, TypeError, ValueError):
        return "未记录"


def terminal_context(directory, summary, *, metadata_directory=None):
    """Describe a terminal outcome without mistaking restored config for verified recovery."""
    metadata = Path(metadata_directory) if metadata_directory is not None else Path(directory)

    def snapshot(name):
        try:
            value = json.loads((metadata / name).read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    state, provenance = snapshot("status.json"), snapshot("provenance.json")
    restoration = snapshot("restoration.json")
    retry = snapshot("recovery.json")
    status = summary.get("status") or state.get("status") or "UNKNOWN"
    complete = summary.get("execution_complete")
    execution = "完整" if complete is True else "未完成" if complete is False else "未建立执行批次或未记录"
    reason = summary.get("error") or state.get("error")
    if not reason:
        if status == "PASSED":
            reason = "无"
        elif status == "FAILED":
            reason = "存在未通过用例或资产完整性问题，详见结果明细"
        else:
            reason = "未记录具体原因，请核查启动、执行及恢复日志"
    if state.get("local_restored_and_verified") is True:
        recovery = "Local 配置恢复及部署模式、服务检查通过"
    elif restoration.get("status") == "RESTORED":
        recovery = "Local 配置已还原；环境恢复检查未通过或尚未完成，环境可用性未验证"
    elif retry.get("status") == "PREPARED_FOR_REDEPLOY":
        recovery = "Local 配置已还原；待重新部署及恢复验证，前批恢复标记仍待处理"
    elif provenance.get("deployment_campaign") or (metadata / "deployment-plan.json").exists():
        recovery = "Local 恢复未完成或未验证，请检查恢复记录；不能认为环境已恢复可用"
    else:
        recovery = "未记录恢复验证证据；不据此判断环境已恢复可用"
    lines = ["## 终态与环境恢复", "", f"- 记录ID：`{metadata.name}`", f"- 批次终态：{status}",
             f"- 代码版本：`{provenance.get('head') or state.get('head') or '未记录'}`",
             f"- 开始时间：{beijing_time(state.get('started_at'))}",
             f"- 结束时间：{beijing_time(summary.get('finished_at') or state.get('finished_at'))}",
             f"- 执行完整性：{execution}", f"- 未完成或未通过原因：{reason}", f"- 环境恢复状态：{recovery}"]
    if "planned" in summary:
        lines += [f"- 结果记录：{summary.get('recorded', '未记录')} / {summary['planned']}",
                  "- 用例结果：" + ", ".join(f"{key}={value}" for key, value in sorted(summary.get("counts", {}).items()))]
    if state.get("batch"):
        lines += [f"- 关联执行批次：`{state['batch']}`"]
    return lines + [""]
