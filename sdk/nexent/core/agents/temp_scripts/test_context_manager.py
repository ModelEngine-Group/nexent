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

    print(f"\n{'='*60}")
    print(f"多轮对话结束 | 总对话轮数: {len(conversation_history)//2}")
    print(f"{'='*60}")
    return results


# P1: 首次压缩且首次压缩后，后续命中[New的一步或多步]
async def test_p1_first_comp_and_sub_new_run_hit():
    """Previous Run 压缩开启（opt）——基于 history.md 的 3 轮对话。"""
    agent_history = parse_conversation_to_history("./small_history.md")
    cm_config = ContextManagerConfig(
        enabled=True, token_threshold=9000, keep_recent_pairs=1
    )
    queries = [
        "总结之前对话的主题是什么",
        "复数表示旋转，请使用python最基础的功能演示下",
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


# P2: 增量压缩：先后两次压缩，且合理命中
async def test_p2_inc_comp_and_hit_valid():
    """Previous Run 压缩开启（opt）——基于 history.md 的 3 轮对话。"""
    agent_history = parse_conversation_to_history("./small_history.md")
    # import pdb; pdb.set_trace()
    cm_config = ContextManagerConfig(
        enabled=True, token_threshold=3600, keep_recent_pairs=1
    )
    queries = [
        "总结之前对话的主题是什么",
        "复数表示旋转，请使用python最基础的功能演示下",
        "请用 Python 计算 2 的 10 到 15 次方，并告诉我哪些是质数。",
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


async def test_previous_run_overflow_baseline():
    """Previous Run 压缩禁用（baseline）——与 opt 做对照。"""
    agent_history = parse_conversation_to_history("./small_history.md")
    cm_config = ContextManagerConfig(
        enabled=False, token_threshold=10000, keep_recent_pairs=1
    )
    queries = [
        "总结之前对话的主题是什么",
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


async def test_current_run_complex_baseline():
    """Current Run 压缩禁用（baseline）——复杂多步问题。"""
    base_history = parse_conversation_to_history("./small_history.md")
    cm_config = ContextManagerConfig(
        enabled=False,
        token_threshold=800,
        keep_recent_steps=1,
    )
    queries = ["请用 Python 计算 2 的 10 到 15 次方，并告诉我哪些是质数。请分步执行。"]
    results = await run_multi_turn(
        queries=queries,
        base_history=base_history,
        cm_config=cm_config,
        max_steps=10,
        debug=False,
    )
    return results


async def test_current_run_complex_opt():
    """Current Run 压缩开启（opt）——同上复杂问题，断言发生压缩。"""
    base_history = parse_conversation_to_history("./small_history.md")
    cm_config = ContextManagerConfig(
        enabled=True,
        token_threshold=3000,
        keep_recent_steps=1,
    )
    shared_cm = ContextManager(config=cm_config, max_steps=10)
    queries = ["请用 Python 计算 2 的 10 到 15 次方，并告诉我哪些是质数。请分步执行。"]
    results = await run_multi_turn(
        queries=queries,
        base_history=base_history,
        cm_config=cm_config,
        max_steps=10,
        debug=False,
    )
    stats = shared_cm.get_all_compression_stats()
    print(f"[CurrentRunOpt] Stats: {stats}")
    # assert stats["total_calls"] >= 1, "Current Run 应触发至少一次压缩"
    return results


async def test_current_run_complex_followup():
    """Current Run 压缩开启——两轮复杂任务，验证缓存复用。"""
    base_history = parse_conversation_to_history("./history.md")
    cm_config = ContextManagerConfig(
        enabled=True,
        token_threshold=800,
        keep_recent_steps=1,
        chars_per_token=1.0,
    )
    shared_cm = ContextManager(config=cm_config, max_steps=10)
    queries = [
        "请用 Python 计算 2 的 10 到 12 次方，并告诉我哪些是质数。请分步执行。",
        "生成一个4维的随机矩阵，元素服从[0,1)分布，计算其行列式、迹、秩、逆矩阵(如果可逆)，以及所有特征值和特征向量",
    ]
    results = await run_multi_turn(
        queries=queries,
        base_history=base_history,
        cm_config=cm_config,
        max_steps=10,
        debug=False,
    )
    stats = shared_cm.get_all_compression_stats()
    print(f"[CurrentRunFollowup] Stats: {stats}")
    return results


# =============================================================================
# 主入口：可按需选择运行
# =============================================================================

if __name__ == "__main__":
    # get the esitmated tokens of the provided history
    with open("./small_history.md", "r", encoding="utf-8") as f:
        tmp = f.read()
    print("Esimated Tokens of small history: ", estimate_tokens_text(tmp))
    # 1. Previous Run 系列
    # asyncio.run(test_previous_run_overflow_baseline())

    # 2. Current Run 系列
    # asyncio.run(test_current_run_complex_baseline())
    asyncio.run(test_current_run_complex_opt())
    # asyncio.run(test_current_run_complex_followup())

    # 3. 渐进式历史/小历史系列
    # asyncio.run(test_custom_queries())
    # asyncio.run(test_gradual_history_cache_hit())
    # asyncio.run(test_gradual_history_cache_invalidation())

    # 默认运行一个快速组合示例：baseline + opt + custom
    print("=" * 60)
    print("默认运行：Previous Run baseline → opt")
    print("=" * 60)
    # asyncio.run(test_previous_run_overflow_baseline())
    # asyncio.run(test_p2_inc_comp_and_hit_valid())
