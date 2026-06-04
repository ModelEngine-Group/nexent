# -*- coding: utf-8 -*-
"""Offload/reload 端到端价值验证。

场景
----
1. 预加载长历史（long_inventory_history.md, ~5000 tokens）
2. Turn 1 执行 Python 代码，生成 ~8000 字符的随机输出（含隐藏凭据值）
   历史 + Turn 1 输出超过 token_threshold → 压缩触发 → Turn 1 输出被 offload
3. Turn 2 问凭据值。LLM 不能重新执行（随机种子丢失）。
   压缩 summary 不会包含长随机字符串细节 → 必须 reload。
4. Turn 3:Turn 2 的 reload 输出本身可能超过 per_step_render_limit，若被再次 offload 则会在
   inventory 中产生「内容雷同但 handle 不同」的重复条目，造成上下文污染。Turn 3 这里是无关query, 检验下offload

"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_utils import (
    build_agent_run_info,
    run_agent_with_tracking,
    parse_conversation_to_history,
    ContextManagerConfig,
    AgentHistory,
)
from nexent.core.agents.agent_context import ContextManager

# 凭据值（与 long_inventory_history.md 中一致，作为验证锚点）
NEEDLE_PW = "KX9mP2vR7qW4nL8jF3hT6yB1dC5sA0gU"
NEEDLE_TOKEN = "tok_8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d"  # REDIS_CLUSTER_TOKEN

TURN1_CODE = (
    'import random, hashlib\n'
    'random.seed(42)\n'
    'secret_pw = hashlib.md5(str(random.random()).encode()).hexdigest()[:12].upper()\n'
    'secret_mac = ":".join(f"{random.randint(0,255):02x}" for _ in range(6))\n'
    'print("=== 服务器健康检查报告 ===")\n'
    'for i in range(80):\n'
    '    cpu = random.randint(5, 99)\n'
    '    mem = random.randint(10, 99)\n'
    '    disk = random.randint(15, 99)\n'
    '    uptime = random.randint(1, 365)\n'
    '    mac = ":".join(f"{random.randint(0,255):02x}" for _ in range(6))\n'
    '    status = "CRITICAL" if disk > 90 or cpu > 95 else ("WARNING" if disk > 80 else "OK")\n'
    '    print(f"server-{i:03d}: cpu={cpu}% mem={mem}% disk={disk}% status={status} uptime={uptime}d mac={mac}")\n'
    'print()\n'
    'print("--- 本次运行生成的凭据 ---")\n'
    'print(f"APP_GENERATED_SECRET={secret_pw}")\n'
    'print(f"server-042\\u5907\\u7528 MAC={secret_mac}")\n'
).strip()


async def test_offload_reload_value(debug: bool = False):
    print("=" * 60)
    print("Offload/Reload E2E: Must-Reload Scenario")
    print("=" * 60)

    cm_config = ContextManagerConfig(
        enabled=True,
        token_threshold=3600,           # 极低阈值，确保历史即触发压缩
        keep_recent_steps=1,
        keep_recent_pairs=0,
        per_step_render_limit=1200,     # 超过 2500 字符触发 offload
        enable_reload=True,
        max_offload_entry_chars=50000,
        max_observation_length=900,
        chars_per_token=1.2,
    )
    shared_cm = ContextManager(config=cm_config, max_steps=12)
    store = shared_cm.offload_store

    # 预加载长历史 → 已有 context 压力
    hist_path = os.path.join(os.path.dirname(__file__), "long_inventory_history.md")
    base_history = parse_conversation_to_history(hist_path) if os.path.exists(hist_path) else []
    conversation = list(base_history)
    print(f"[Setup] base history: {len(base_history)} msgs")

    # ── Turn 1: 生成不可复现的大输出 ──
    t1 = (
        "请直接执行下面这段 Python 代码，不要修改它。执行完毕后告诉我总共生成了多少行输出：\n\n"
        f"```python\n{TURN1_CODE}\n```"
    )
    print(f"\n[Turn 1] 执行 Python 生成 ~{len(TURN1_CODE)} 字符的健康检查报告...")

    info1 = build_agent_run_info(
        query=t1, history=conversation, tools=[],
        max_steps=5, agent_name="ops",
        agent_description="运维 Agent，可执行代码和从压缩档案中恢复历史输出。",
        context_manager_config=cm_config,
    )
    info1.context_manager = shared_cm
    r1 = await run_agent_with_tracking(info1, debug=False)
    print(f"[Turn 1] Steps={r1.step_count}, Store entries={len(store)}")
    conversation.append(AgentHistory(role="user", content=t1))
    conversation.append(AgentHistory(role="assistant", content=r1.final_answer))

    # ── 填充轮次: 确保压缩确实触发 ──
    for fi, fq in enumerate([
        "请解释服务器健康检查中 CPU、内存、磁盘三个指标的意义",
        "磁盘使用率过高时有哪些常见的排查思路",
    ]):
        inf = build_agent_run_info(
            query=fq, history=conversation, tools=[],
            max_steps=3, agent_name="ops",
            agent_description="运维 Agent。",
            context_manager_config=cm_config,
        )
        inf.context_manager = shared_cm
        rf = await run_agent_with_tracking(inf, debug=False)
        print(f"[Filler {fi+1}] Steps={rf.step_count}, Store={len(store)}")
        conversation.append(AgentHistory(role="user", content=fq))
        conversation.append(AgentHistory(role="assistant", content=rf.final_answer))

    # ── Turn 2: 必须 reload ──
    t2 = (
        "在最早加载的服务器健康检查报告中，末尾有一个「关键配置项」部分。"
        "请输出其中 DATABASE_MASTER_PASSWORD 的值。"
    )
    print(f"\n[Turn 2] 问针值（必须 reload）...")

    info2 = build_agent_run_info(
        query=t2, history=conversation, tools=[],
        max_steps=5, agent_name="ops",
        agent_description="运维 Agent，可从压缩档案中恢复历史输出。",
        context_manager_config=cm_config,
    )
    info2.context_manager = shared_cm
    r2 = await run_agent_with_tracking(info2, debug=False)

    print(f"\n[Turn 2] Answer:\n{r2.final_answer}")
    print(f"[Turn 2] Steps={r2.step_count}")

    conversation.append(AgentHistory(role="user", content=t2))
    conversation.append(AgentHistory(role="assistant", content=r2.final_answer))

    # ── Turn 3: 无关 filler，验证 reload 输出未被重复 offload ──
    t3 = "谢谢你的回答。请再确认一下你的系统是否正常工作。"
    store_before_t3 = len(store)
    print(f"\n[Turn 3] filler（检查 inventory 是否含多余 handle）...")
    print(f"         store before: {store_before_t3} entries")

    info3 = build_agent_run_info(
        query=t3, history=conversation, tools=[],
        max_steps=3, agent_name="ops",
        agent_description="运维 Agent。",
        context_manager_config=cm_config,
    )
    info3.context_manager = shared_cm
    r3 = await run_agent_with_tracking(info3, debug=False)

    store_after_t3 = len(store)
    active_t3 = store.list_active()
    print(f"[Turn 3] Steps={r3.step_count}")
    print(f"         store after: {store_after_t3} entries (delta: {store_after_t3 - store_before_t3})")
    for h, d in active_t3:
        print(f"           handle={h[:8]}... desc={d[:80]}...")

    # 验证：Turn 2 的 reload 输出不应该产生新的 offload 条目
    duplicate_free = store_after_t3 == store_before_t3
    print(f"         no duplicate from reload: {'✓' if duplicate_free else '✗ (多了 ' + str(store_after_t3 - store_before_t3) + ' 条)'}")

    # ── 验证 ──
    print(f"\n{'=' * 60}")
    print(f"offload: store={len(store)} entries")
    print(f"reload:  hits={store.reload_hits} misses={store.reload_misses}")
    print(f"needle: PW={'✓' if NEEDLE_PW in r2.final_answer else '✗'}")
    print(f"compress: {shared_cm.get_all_compression_stats()}")

    ok = (NEEDLE_PW in r2.final_answer and store.reload_hits > 0)
    print(f"\n>>> {'PASS ✓' if ok else 'FAIL ✗ (针值命中但reload=0)'}")
    return ok


if __name__ == "__main__":
    success = asyncio.run(test_offload_reload_value())
    sys.exit(0 if success else 1)
