# Context Manager 方案的端到端测试方案

## 测试工具模块

本项目提供 `test_utils.py` 模块，包含从 `test_multi_run.py` 抽提的可复用组件：

- **Prompt 构建**: `build_system_prompt()`, `build_prompt_templates()`
- **AgentRunInfo 构造**: `build_agent_run_info()`
- **消息流处理**: `run_agent_with_tracking()`, `process_agent_message()`
- **历史记录构建**: `build_mock_history()`, `build_large_history()`

---

## 1. Previous Run-超限测试

### 目标
1. 构造足够多的TaskStep/ActionStep对的AgentMemory超过threshold，然后进行测试，验证效果。
2. 关注压缩后的摘要表示或内容是否合理
3. 继续对话，验证缓存复用是否存在问题
   
### 具体做法
1. 参考 test_multi_run.py，构建多个AgentHistory，并支持while循环继续多轮会话

### 复用示例代码

```python
# -*- coding: utf-8 -*-
"""
Previous Run 超限测试 - 使用 test_utils.py 复用组件
"""
import asyncio
import sys
import os

# 添加路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_utils import (
    build_agent_run_info,
    run_agent_with_tracking,
    build_large_history,
    print_history_stats,
    AgentHistory,
    ContextManagerConfig
)


async def test_previous_run_overflow():
    """
    测试场景：Previous Run 超限
    
    1. 构造大量历史记录（超过 threshold）
    2. 发送查询，观察压缩效果
    3. 继续对话，验证缓存复用
    """
    print("=" * 60)
    print("Previous Run 超限测试")
    print("=" * 60)
    
    # ========== 阶段 1: 构造大量历史记录 ==========
    print("\n[阶段 1] 构造历史记录...")
    
    # 构建 100 条历史消息（50 轮对话）
    history = build_large_history(
        total_messages=100,
        base_content="测试上下文记忆的消息内容"
    )
    print_history_stats(history)
    
    # ========== 阶段 2: 首次查询 - 触发压缩 ==========
    print("\n[阶段 2] 首次查询 - 观察压缩效果...")
    
    # 配置上下文管理器（启用调试模式以观察压缩过程）
    cm_config = ContextManagerConfig(
        enabled=True,
        threshold=20,              # 超过20条消息触发压缩
        compression_ratio=0.5,     # 压缩到50%
        summary_strategy="hierarchical",
        keep_recent_turns=4,       # 保留最近4轮
        enable_cache=True,
        debug_mode=True            # 打印调试信息
    )
    
    query = "请总结我们之前的对话主题是什么？"
    agent_run_info = build_agent_run_info(
        query=query,
        history=history,
        agent_name="memory_test_agent",
        max_steps=5,
        context_manager_config=cm_config
    )
    
    result = await run_agent_with_tracking(agent_run_info, debug=False)
    
    print(f"\n助手回答: {result.final_answer[:200]}...")
    print(f"\n消息统计: {result.message_type_count}")
    print(f"执行步骤: {result.step_count}")
    
    # ========== 阶段 3: 继续对话 - 验证缓存复用 ==========
    print("\n[阶段 3] 继续对话 - 验证缓存复用...")
    
    # 添加刚才的对话到历史
    history.append(AgentHistory(role="user", content=query))
    history.append(AgentHistory(role="assistant", content=result.final_answer))
    
    # 第二轮查询 - 复用相同的 context_manager_config 以验证缓存
    query2 = "你还记得我们第一轮对话中提到的编号是几吗？"
    agent_run_info2 = build_agent_run_info(
        query=query2,
        history=history,
        agent_name="memory_test_agent",
        max_steps=5,
        context_manager_config=cm_config  # 复用配置以验证缓存
    )
    
    result2 = await run_agent_with_tracking(agent_run_info2, debug=False)
    
    print(f"\n助手回答: {result2.final_answer[:200]}...")
    print(f"\n消息统计: {result2.message_type_count}")
    
    # ========== 阶段 4: 验证压缩效果 ==========
    print("\n[阶段 4] 验证要点:")
    print("  1. 检查压缩后的摘要是否保留了关键信息")
    print("  2. 验证第二轮对话是否复用了缓存")
    print("  3. 确认响应时间是否在可接受范围内")
    
    return result, result2


async def test_gradual_history_buildup():
    """
    渐进式历史记录累积测试
    
    模拟真实场景：对话历史逐步累积，观察何时触发压缩
    """
    print("\n" + "=" * 60)
    print("渐进式历史累积测试")
    print("=" * 60)
    
    history = []
    milestones = [10, 20, 50, 100]  # 在以下消息数时进行测试
    
    for target_count in milestones:
        # 补充历史到目标数量
        while len(history) < target_count:
            turn = len(history) // 2 + 1
            history.append(AgentHistory(
                role="user", 
                content=f"第{turn}轮用户问题"
            ))
            history.append(AgentHistory(
                role="assistant", 
                content=f"第{turn}轮助手回答，包含详细信息..."
            ))
        
        print(f"\n--- 测试 {target_count} 条历史记录 ---")
        print_history_stats(history)
        
        # 发送测试查询 - 使用不同的压缩策略进行对比
        query = f"当前历史记录有 {len(history)} 条，你能正常工作吗？"
        
        # 根据历史数量选择不同的配置策略
        if target_count <= 20:
            cm_config = ContextManagerConfig.conservative()  # 保守策略
        elif target_count <= 50:
            cm_config = ContextManagerConfig.default()  # 默认策略
        else:
            cm_config = ContextManagerConfig.aggressive()  # 激进策略
        
        agent_run_info = build_agent_run_info(
            query=query,
            history=history,
            max_steps=3,
            context_manager_config=cm_config
        )
        
        result = await run_agent_with_tracking(agent_run_info)
        print(f"响应长度: {len(result.final_answer)} 字符")
        print(f"消息类型: {result.message_type_count}")


async def main():
    """主函数"""
    print("选择测试模式:")
    print("1. Previous Run 超限测试")
    print("2. 渐进式历史累积测试")
    
    choice = input("\n请输入选择 (1/2): ").strip()
    
    if choice == "1":
        await test_previous_run_overflow()
    elif choice == "2":
        await test_gradual_history_buildup()
    else:
        print("默认执行 Previous Run 超限测试")
        await test_previous_run_overflow()


if __name__ == "__main__":
    asyncio.run(main())
```

### 复用组件说明

| 函数/类 | 来源 | 用途 |
|---------|------|------|
| `build_agent_run_info()` | test_utils.py | 快速构建 AgentRunInfo（支持 context_manager_config） |
| `run_agent_with_tracking()` | test_utils.py | 运行 Agent 并收集统计 |
| `build_large_history()` | test_utils.py | 批量生成大量历史记录 |
| `print_history_stats()` | test_utils.py | 打印历史记录统计 |
| `AgentHistory` | test_utils.py | 历史记录数据模型 |
| `ContextManagerConfig` | test_utils.py | 上下文管理器配置类 |

### Context Manager 配置示例

```python
from test_utils import ContextManagerConfig, build_agent_run_info

# 方式 1: 使用默认配置
agent_run_info = build_agent_run_info(
    query="测试查询",
    history=history
)

# 方式 2: 自定义上下文管理器配置
cm_config = ContextManagerConfig(
    enabled=True,
    threshold=20,              # 超过20条消息触发压缩
    compression_ratio=0.5,     # 压缩到50%
    summary_strategy="hierarchical",  # 分层摘要
    keep_recent_turns=4,       # 保留最近4轮对话
    enable_cache=True,         # 启用缓存
    debug_mode=True            # 打印调试信息
)

agent_run_info = build_agent_run_info(
    query="测试查询",
    history=history,
    context_manager_config=cm_config
)

# 方式 3: 使用预设配置
# 激进压缩（适合超长对话）
cm_config = ContextManagerConfig.aggressive()

# 保守压缩（适合需要精确记忆的对话）
cm_config = ContextManagerConfig.conservative()
```