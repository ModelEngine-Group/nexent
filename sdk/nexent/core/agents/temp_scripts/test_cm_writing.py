import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_utils import (
    build_agent_run_info,
    run_agent_with_tracking,
    parse_conversation_to_history,
    print_history_stats,
    AgentHistory,
    ContextManagerConfig,
)
from nexent.core.agents.agent_context import ContextManager
from nexent.core.utils.token_estimation import estimate_tokens_text

async def run_multi_turn(
    queries: list[str],
    base_history: list[AgentHistory],
    cm_config: ContextManagerConfig,
    max_steps: int = 5,
    debug: bool = False,
) -> list:
    """
    执行自定义多轮对话测试。

    每轮对话会基于累积的 conversation_history（包含 base_history + 前几轮对话）
    运行 Agent，并将当前轮的 query 与 assistant 回复追加到 history 中，
    供下一轮使用。

    当 cm_config.enabled 为 True 时，会创建一个 conversation 级别的 ContextManager
    并在多轮之间复用，以验证跨 run 的摘要缓存机制。
    """
    conversation_history = list(base_history)  # 深拷贝避免污染原始历史
    results = []

    # 创建 conversation 级别的 ContextManager（若启用）
    shared_cm = None
    if cm_config and cm_config.enabled:
        shared_cm = ContextManager(config=cm_config, max_steps=max_steps)

    print(f"\n{'='*60}")
    print(
        f"开始多轮对话测试 | context_manager={'启用' if cm_config.enabled else '禁用(baseline)'}"
    )
    print(f"初始历史轮数: {len(base_history)//2} | 预定义 query 数: {len(queries)}")
    print(f"{'='*60}")

    for turn_idx, query in enumerate(queries, start=1):
        print(f"\n--- 第 {turn_idx}/{len(queries)} 轮 ---")
        print(f"用户: {query}")

        agent_run_info = build_agent_run_info(
            query,
            conversation_history,
            max_steps=max_steps,
            context_manager_config=cm_config,
        )

        # 挂载 conversation 级别的 ContextManager，实现跨 run 复用
        if shared_cm is not None:
            agent_run_info.context_manager = shared_cm

        result = await run_agent_with_tracking(agent_run_info, debug=debug)
        results.append(result)

        print(f"助手: {result.final_answer[:200]}...")
        print(f"[本轮统计] {result.message_type_count}")

        # 将本轮对话追加到累积历史
        conversation_history.append(AgentHistory(role="user", content=query))
        conversation_history.append(
            AgentHistory(role="assistant", content=result.final_answer)
        )

    # 打印 ContextManager 缓存统计（若启用）
    if shared_cm is not None:
        print(f"\n[ContextManager 全局统计]")
        print(f"  {shared_cm.get_all_compression_stats()}")
        store = shared_cm.offload_store
        print(f"\n[Offload Store]")
        print(f"  entries={len(store)}  reload_hits={store.reload_hits}  reload_misses={store.reload_misses}")
        active = store.list_active()
        if active:
            print(f"  active handles ({len(active)}):")
            for h, d in active:
                print(f"    handle={h[:8]}... desc={d[:80]}...")
        else:
            print(f"  (no active entries)")

    print(f"\n{'='*60}")
    print(f"多轮对话结束 | 总对话轮数: {len(conversation_history)//2}")
    print(f"{'='*60}")
    return results

# P1: 首次压缩且首次压缩后，后续命中[New的一步或多步]
async def test_writing_baseline():
    """Previous Run 压缩开启（opt）——基于 history.md 的 3 轮对话。"""
    agent_history = []
    cm_config = ContextManagerConfig(
        enabled=False, token_threshold=12000, keep_recent_pairs=1
    )
    queries = [
        "用小猫、小狗、人作为角色，用宇宙、银河、星球作为场景，用远航作为故事背景，写一个情感交织、情节跌宕、来回拉扯的长篇小说。约500字。",
        "扩写到5k字。",
    "增加一些历史的情节。",
    "再增加一些关于家庭的成分。",
    "让情节热烈一点。" ,
    "总结上述内容",
    "自我介绍"

    ]
    results = await run_multi_turn(
        queries=queries,
        base_history=agent_history,
        cm_config=cm_config,
        max_steps=5,
        debug=False,
    )
    print_history_stats(agent_history)
    return results


async def test_writing_opt():
    """Current Run 压缩开启（opt）——同上复杂问题，断言发生压缩。"""
    base_history = []
    cm_config = ContextManagerConfig(
        enabled=True,
        token_threshold=12000,
        keep_recent_pairs=1,
        enable_reload=True,
        per_step_render_limit=3200,
        max_offload_entry_chars=60000,
        max_observation_length=1000,
    )
    queries = [
        "用小猫、小狗、人作为角色，用宇宙、银河、星球作为场景，用远航作为故事背景，写一个情感交织、情节跌宕、来回拉扯的长篇小说。约500字。",
        "扩写到5k字。",
    "增加一些历史的情节。",
    "再增加一些关于家庭的成分。",
    "让情节热烈一点。" ,
    "总结上述内容",
    "自我介绍"
    ]
    results = await run_multi_turn(
        queries=queries,
        base_history=base_history,
        cm_config=cm_config,
        max_steps=10,
        debug=False,
    )
    return results

if __name__ == "__main__":


    # 默认运行一个快速组合示例：baseline + opt + custom
    print("=" * 60)
    print("默认运行：Previous Run baseline → opt")
    print("=" * 60)
    # asyncio.run(test_previous_run_overflow_baseline())
    # asyncio.run(test_writing_baseline())
    asyncio.run(test_writing_opt())
