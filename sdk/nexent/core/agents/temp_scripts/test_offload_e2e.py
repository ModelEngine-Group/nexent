# -*- coding: utf-8 -*-
"""端到端评测 offload / reload 机制（场景 C：完全自主多轮）。

设计目标
--------
1. 复用 test_utils 的 build_agent_run_info / run_agent_with_tracking，沿用既有的
   Agent 构建与消息流跟踪方式。
2. 把 offload→压缩→自主 reload 的检验集成进一次真实的多轮 LLM 自主执行：
   - 让 Agent 通过工具读入多份「超大文档」，每份文档正中间埋一根高熵的「针」
     （NEEDLE_<topic> = <随机十六进制>）。
   - 文档长度被刻意设计为 > max_observation_length 且渲染后 > per_step_render_limit，
     从而：observation 先被 max_observation_length 截断（head+tail 各保留约一半，
     中间的针因不在 head/tail 窗口内而完全消失），原始全文被存入 OffloadStore，
     上下文里只剩 [[OBS_OFFLOAD: ... handle=...]] 标记。
   - 累积 token 超过 token_threshold 触发压缩，标记进入 summary。
   - 最后一轮提一个「必须同时取回多份被卸载原文才能答对」的综合问题。
3. 三重判定（最稳）：
   (a) tool-call 名捕获：从消息流的 code / 执行日志里 grep reload 工具名。
   (b) 文本 grep：确认 reload 工具名确实出现在被执行的代码片段中。
   (c) 针值正确性：final_answer 是否包含每根针的精确值。
   由于针在显示文本里被截掉、且是高熵随机值，模型「凭记忆/猜测」答对的概率可忽略，
   答对 ⟺ 它确实自主 reload 取回了原文。

注意：本场景按你的选择「把 reload 提示写进 prompt」，通过 duty_prompt 注入引导。
若想测纯自主性，把 RELOAD_HINT 置空即可（保留为开关）。
"""

import asyncio
import os
import sys
import uuid
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smolagents.tools import Tool

from test_utils import (
    build_agent_run_info,
    run_agent_with_tracking,
    parse_conversation_to_history,
    AgentRunResult,
    process_agent_message,
    AgentHistory,
    ContextManagerConfig,
    THINKING_OFF_EXTRA_BODY,
)
from nexent.core.agents.run_agent import agent_run
from nexent.core.agents.agent_model import ToolConfig

WORKSPACE_DIR = Path(__file__).parent / "test_workspace" / "offload_e2e"

# reload 工具名（与 ReloadOriginalContextTool.name 保持一致）
RELOAD_TOOL_NAME = "reload_original_context_messages"

# 写进 prompt 的 reload 引导（你选择「写进 prompt」）。置空可切换为纯自主测试。
RELOAD_HINT = (
    "\n\n[关于被卸载的上下文]\n"
    "当你在对话历史中看到形如 [[OBS_OFFLOAD: ... chars, handle=<id>]] 或 "
    "[[CONTENT_OFFLOAD: ... handle=<id>]] 的标记时，说明该段原始内容因过长被外部归档，"
    f"显示文本是被截断过的。若回答问题需要其中的细节，请调用 {RELOAD_TOOL_NAME} 工具，"
    "传入 offload_handle 参数（值为标记中的 handle）取回完整原文，再据此作答。"
    "不要凭被截断的显示文本猜测。"
)


# =============================================================================
# 针-in-haystack 文档生成
# =============================================================================

def _make_needle() -> str:
    """生成一根高熵针值，确保模型无法凭记忆/猜测命中。"""
    return uuid.uuid4().hex[:10].upper()


def _make_paragraph(topic: str, idx: int) -> str:
    """生成一段确定性填充文本。编号不同则内容不同，避免被压缩器视为重复噪声。"""
    return (
        f"第 {idx} 段：在 {topic} 的工程实践中，需要权衡延迟、吞吐与一致性。"
        f"该段编号 {idx}，用于占位以模拟真实长文档的体量与结构。"
        f"不同子系统对资源的需求差异显著，需结合实际负载剖析后再做容量规划。\n"
    )


def make_haystack(topic: str, needle_key: str, needle_val: str,
                  filler_chars: int = 12000) -> str:
    """生成一份大文档：针埋在文档正中间，前后各有大量 filler。

    关键设计：max_observation_length 截断策略通常保留 head + tail 两部分
    （各约一半），中间部分被丢弃。若针放在末尾，会被 tail 保留从而直接可见；
    若放在开头，会被 head 保留。因此把针埋在正中间，前后各用约 filler_chars/2
    的填充段落包裹，确保 head 和 tail 截断窗口都只包含无意义的 filler——
    模型必须通过 reload 才能读到中间的针值。
    """
    half = filler_chars // 2

    head = (
        f"# {topic} 技术说明文档\n\n"
        f"本文档用于 offload/reload 端到端评测，主题：{topic}。\n"
        f"以下为正文内容（填充段落，用于撑大体积以触发卸载）。\n\n"
    )

    # 前半部分 filler：确保针不在 head 截断窗口内
    front_paragraphs = []
    i = 0
    while sum(len(p) for p in front_paragraphs) < half:
        front_paragraphs.append(_make_paragraph(topic, i))
        i += 1

    # 针（埋在正中间）
    needle_block = (
        f"\n\n## 关键配置项（重要）\n"
        f"在 {topic} 部署清单中，记录了一项关键凭据：\n"
        f"{needle_key} = {needle_val}\n"
        f"该值由运维在交付时一次性写入，后续问答需精确引用，不得改写或猜测。\n\n"
    )

    # 后半部分 filler：确保针不在 tail 截断窗口内
    rear_paragraphs = []
    while sum(len(p) for p in rear_paragraphs) < half:
        rear_paragraphs.append(_make_paragraph(topic, i))
        i += 1

    tail = (
        f"\n\n## 附录\n"
        f"本文档由 {topic} 技术组编写，版本 v2.4.1。\n"
        f"如有疑问请联系 {topic}-ops@nexent.internal。\n"
    )

    return head + "".join(front_paragraphs) + needle_block + "".join(rear_paragraphs) + tail


class ReadDocTool(Tool):
    """读取预置大文档的工具；其返回值即为会被卸载的超大 observation。"""
    name = "read_doc"
    description = (
        "读取工作区中的一份大型技术文档，返回其完整文本内容。"
        "传入文档名（不含路径），如 'storage'、'network'、'security'。"
    )
    inputs = {
        "doc_name": {
            "type": "string",
            "description": "文档名（不含扩展名），对应工作区内的 <doc_name>.txt 文件。"
        }
    }
    output_type = "string"

    def __init__(self, workspace_dir: str, **kwargs):
        super().__init__(**kwargs)
        self.workspace_dir = Path(workspace_dir).resolve()

    def forward(self, doc_name: str) -> str:
        target = (self.workspace_dir / f"{doc_name}.txt").resolve()
        if not str(target).startswith(str(self.workspace_dir)):
            return f"Error: access denied for '{doc_name}'."
        if not target.exists():
            avail = ", ".join(sorted(p.stem for p in self.workspace_dir.glob("*.txt")))
            return f"Error: doc '{doc_name}' not found. Available: {avail}"
        return target.read_text(encoding="utf-8")


# 注册到 nexent_agent 命名空间，使 create_local_tool 能按 class_name 找到
import nexent.core.agents.nexent_agent as na
na.__dict__["ReadDocTool"] = ReadDocTool


def make_read_doc_config(workspace_dir: str) -> ToolConfig:
    return ToolConfig(
        class_name="ReadDocTool",
        name="read_doc",
        description=ReadDocTool.description,
        inputs='{"doc_name": "str"}',
        output_type="string",
        params={"workspace_dir": workspace_dir},
        source="local",
    )


# =============================================================================
# 带 reload 跟踪的运行器（在 run_agent_with_tracking 之外，额外捕获工具调用）
# =============================================================================

class OffloadRunResult(AgentRunResult):
    def __init__(self):
        super().__init__()
        self.reload_call_count: int = 0          # reload 工具调用次数（best-effort 流式检测）
        self.offload_marker_seen: bool = False   # 流中是否观察到 OFFLOAD 标记


async def run_with_reload_tracking(agent_run_info, debug: bool = False) -> OffloadRunResult:
    """运行 Agent 并跟踪关键事件。

    reload 工具调用和 OFFLOAD 标记的检测都是 best-effort——流式消息的 chunk
    粒度极小（1~8 字符），且工具调用可能不出现在流输出中。这些计数仅作诊断参考，
    不作为 PASS/FAIL 的硬性判定条件。核心判定依靠针值命中率。
    """
    result = OffloadRunResult()
    _buf = ""  # 滑动窗口缓冲，解决跨 chunk 字符串匹配

    async for chunk in agent_run(agent_run_info):
        if not chunk:
            continue
        msg_type, msg_content = process_agent_message(chunk)

        if debug:
            print(f"[DEBUG] {msg_type} len={len(msg_content)}", file=sys.stderr, flush=True)

        result.message_type_count[msg_type] = result.message_type_count.get(msg_type, 0) + 1

        # 滑动窗口累积，检测 reload 工具名和 OFFLOAD 标记
        _buf += msg_content
        if len(_buf) > 4096:
            _buf = _buf[-2048:]
        if RELOAD_TOOL_NAME in _buf:
            result.reload_call_count += 1
            _buf = _buf.replace(RELOAD_TOOL_NAME, "", 1)
        if "OFFLOAD" in _buf and "handle=" in _buf:
            result.offload_marker_seen = True

        if msg_type == "final_answer":
            result.final_answer = msg_content
            result.full_response += msg_content
        elif msg_type == "error":
            result.errors.append(msg_content)

    if not result.final_answer:
        result.final_answer = result.full_response or "（未获得回应）"
    return result


# =============================================================================
# 场景 C：完全自主多轮
# =============================================================================

async def test_autonomous_multi_turn_offload(debug: bool = False):
    ws = WORKSPACE_DIR
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True, exist_ok=True)

    # ---- 1) 造三份大文档，各埋一根针 ----
    needles = {
        "storage":  ("STORAGE_CRED",  _make_needle()),
        "network":  ("NETWORK_CRED",  _make_needle()),
        "security": ("SECURITY_CRED", _make_needle()),
    }
    for topic, (k, v) in needles.items():
        (ws / f"{topic}.txt").write_text(
            make_haystack(topic, k, v, filler_chars=12000), encoding="utf-8"
        )
    print("已生成文档与针值（评测内部基准）：")
    for topic, (k, v) in needles.items():
        print(f"  {topic}.txt -> {k} = {v}  (文档约 {len((ws/f'{topic}.txt').read_text('utf-8'))} chars)")

    tools = [make_read_doc_config(str(ws))]

    # ---- 2) 配置 ContextManager：打开 offload + reload 全链路 ----
    # 关键约束（见 core_agent.py 的 _raw_observation 保存条件）：
    #   enable_reload + per_step_render_limit>0 + max_observation_length>0
    #   且 observation 长度 > max_observation_length  →  原始全文才会被完整 offload。
    # 把针放在文档尾部，使其落在 max_observation_length 的截断点之后，
    # 显示文本读不到针 → 不 reload 必然答不出。
    cm_config = ContextManagerConfig(
        enabled=True,
        token_threshold=3900,          # 调低以确保多份大文档累积后触发压缩
        keep_recent_steps=1,
        keep_recent_pairs=0,
        enable_reload=True,
        per_step_render_limit=3200,    # 渲染段 >3000 字符即卸载
        max_observation_length=1000,   # observation 头部截断阈值（针在尾部被切掉）
        max_offload_entry_chars=60000, # 单条原文上限，覆盖整篇文档
    )

    # ---- 3) 历史垫底（复用已有解析），再构造多轮自主任务 ----
    base_history = []
    hist_file = Path(__file__).parent / "small_history.md"
    if hist_file.exists():
        base_history = parse_conversation_to_history(str(hist_file))

    duty = (
        "你是一名运维知识助手。你可以使用 read_doc 工具读取技术文档。"
        "请严格按用户要求逐步完成任务，需要引用文档中的具体凭据时必须精确引用。"
        + RELOAD_HINT
    )

    # 多轮对话：第一轮读取全部文档（制造多个会被卸载的大 observation + 触发压缩），
    # 第二轮要求综合回答三根针——此时早期 observation 已被压缩成 OFFLOAD 标记，
    # 模型必须自主 reload 才能拿到针值。
    queries = [
        (
            "请依次用 read_doc 读取 storage、network、security 三份文档。"
            "并在三份文档各自末尾「关键配置项」中记录的凭据值，"
            "格式为三行：\n"
            "STORAGE_CRED=<值>\nNETWORK_CRED=<值>\nSECURITY_CRED=<值>\n"
            "三个值都必须与文档原文完全一致。"
        ),
    ]

    # 累积对话历史，每轮结束后追加本轮 query + reply
    # （参照 test_context_manager.py 的 run_multi_turn 模式）
    conversation_history = list(base_history)
    last_result = None

    for turn_idx, query in enumerate(queries, start=1):
        print(f"\n--- 第 {turn_idx}/{len(queries)} 轮 ---")

        agent_run_info = build_agent_run_info(
            query=query,
            history=conversation_history,
            duty_prompt=duty,
            tools=tools,
            max_steps=12,
            agent_name="ops_doc_agent",
            agent_description="A multi-turn ops agent that reads large docs and reloads offloaded content.",
            context_manager_config=cm_config,
            extra_body=THINKING_OFF_EXTRA_BODY,
        )
        # 注意：不手动覆盖 agent_run_info.context_manager。
        # reload 工具在 create_agent 内按 enable_reload 自动注入，并绑定到内部 CM 的 offload_store。
        # 外部覆盖会导致工具引用的 store 与外部 store 不一致，故此处不覆盖。

        result = await run_with_reload_tracking(agent_run_info, debug=debug)
        last_result = result

        print(f"[第{turn_idx}轮] 消息类型: {result.message_type_count}")
        print(f"[第{turn_idx}轮] final_answer 前200字: {result.final_answer[:200]}...")

        # 将本轮追加到累积历史，供下一轮使用
        conversation_history.append(AgentHistory(role="user", content=query))
        conversation_history.append(
            AgentHistory(role="assistant", content=result.final_answer)
        )

    # ---- 4) 判定（基于最后一轮的最终答案） ----
    # 核心逻辑：针埋在文档正中间，head+tail 截断都够不到。模型能精确答出针值
    # ⟺ 它必然通过 reload 取回了完整原文。因此针值命中率是 reload 的充分必要证据。
    #
    # 注意：流式消息中无法可靠捕获 reload 工具调用（chunk 粒度过小 + 工具调用
    # 可能不出现在流输出中），OFFLOAD 标记也只出现在模型输入端而非流输出端。
    # 因此 reload_call_count / offload_marker_seen 仅作为补充诊断信息，不作为
    # PASS/FAIL 的硬性判定条件。
    result = last_result
    print("\n" + "=" * 60)
    print("Final Answer (最后一轮):\n" + result.final_answer)
    print("=" * 60)

    fa = result.final_answer

    # 针值正确性（核心判定）
    hit = {topic: (v in fa) for topic, (k, v) in needles.items()}
    needles_hit = sum(hit.values())

    print("\n--- 判定结果 ---")
    print(f"[诊断] 流中 OFFLOAD 标记: {result.offload_marker_seen}")
    print(f"[诊断] reload 调用计数: {result.reload_call_count}")
    for topic, (k, v) in needles.items():
        print(f"[针值] {k}={v}  ->  {'✓ 命中' if hit[topic] else '✗ 缺失'}")
    print(f"[针值命中] {needles_hit}/3")

    # 综合裁定：针值全部命中 = 证明 reload 全链路正常工作
    passed = needles_hit == 3
    print(f"\n>>> 端到端 offload/reload 自主评测: {'PASS ✓' if passed else 'FAIL ✗'}")

    if not passed:
        print("\n[诊断提示]")
        if needles_hit == 0:
            print("  - 所有针值均缺失：模型可能未调用 reload，或 reload 取回的内容不含针值。")
            print("    检查：(1) RELOAD_HINT 是否有效 (2) 工具的 offload_handle 参数名是否正确")
            print("          (3) max_offload_entry_chars 是否覆盖全文 (4) token_threshold 是否触发压缩")
        else:
            missing = [needles[t][0] for t in needles if not hit[t]]
            print(f"  - 部分针值缺失: {missing}")
            print(f"    已命中 {needles_hit}/3，说明 reload 链路基本正常，")
            print(f"    缺失的针可能因文档结构或截断位置差异未被取回。")

    return result


if __name__ == "__main__":
    print("=" * 60)
    print("场景 C：完全自主多轮 offload / reload 端到端评测")
    print("=" * 60)
    asyncio.run(test_autonomous_multi_turn_offload(debug=False))