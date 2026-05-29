import asyncio
import os
import sys
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smolagents.tools import Tool

from test_utils import (
    build_agent_run_info,
    run_agent_with_tracking,
    parse_conversation_to_history,
    print_history_stats,
    AgentHistory,
    ContextManagerConfig,
)
from nexent.core.agents.agent_context import ContextManager

# Fixed workspace directory for persisting test files across runs
WORKSPACE_DIR = Path(__file__).parent / "test_workspace"

# =============================================================================
# Custom Tool Definitions
# =============================================================================

class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "Read the contents of a file from the workspace directory. "
        "Provide a relative file path and get the file's text content back."
    )
    inputs = {
        "file_path": {
            "type": "string",
            "description": "Relative path to the file within the workspace directory."
        }
    }
    output_type = "string"

    def __init__(self, workspace_dir: str, **kwargs):
        super().__init__(**kwargs)
        self.workspace_dir = Path(workspace_dir).resolve()

    def forward(self, file_path: str) -> str:
        target = (self.workspace_dir / file_path).resolve()
        # Security: ensure the resolved path stays within workspace_dir
        if not str(target).startswith(str(self.workspace_dir)):
            return f"Error: Access denied. Path '{file_path}' is outside the workspace directory."
        if not target.exists():
            return f"Error: File not found at '{file_path}'."
        if target.is_dir():
            files = sorted(target.iterdir())
            listing = "\n".join(f"  {'[DIR] ' if f.is_dir() else '       '}{f.name}" for f in files)
            return f"Directory listing for '{file_path}':\n{listing}" if listing else f"Directory '{file_path}' is empty."
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"Error: '{file_path}' is not a readable text file."


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Write content to a file in the workspace directory. "
        "Provide a relative file path and the content to write. "
        "Parent directories will be created if they don't exist."
    )
    inputs = {
        "file_path": {
            "type": "string",
            "description": "Relative path to the file within the workspace directory."
        },
        "content": {
            "type": "string",
            "description": "The text content to write to the file."
        }
    }
    output_type = "string"

    def __init__(self, workspace_dir: str, **kwargs):
        super().__init__(**kwargs)
        self.workspace_dir = Path(workspace_dir).resolve()

    def forward(self, file_path: str, content: str) -> str:
        target = (self.workspace_dir / file_path).resolve()
        # Security: ensure the resolved path stays within workspace_dir
        if not str(target).startswith(str(self.workspace_dir)):
            return f"Error: Access denied. Path '{file_path}' is outside the workspace directory."
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        size = target.stat().st_size
        return f"Successfully wrote {size} bytes to '{file_path}'."


# =============================================================================
# Chain Tool: Read → LLM Analyze → Write  (all internal, no content duplication)
# =============================================================================

class ReadAnalyzeWriteTool(Tool):
    """Chain tool that wraps read→analyze→write into a single call.

    The LLM analysis happens INSIDE this tool (not in the agent's code block),
    and the write is done silently — neither step produces redundant copies
    of the analysis content in the agent's conversation context.

    This is the Chain pattern: a fixed pipeline executed outside the ReAct loop.
    """

    name = "read_analyze_write"
    description = (
        "Read a file, analyze its content, and write the analysis to another file. "
        "Use this for fixed read→analyze→write pipelines. "
        "Provide the input file path, output file path, and a description of "
        "what analysis to perform. The analysis is done with LLM internally."
    )
    inputs = {
        "input_file": {
            "type": "string",
            "description": "Relative path of the file to read and analyze."
        },
        "output_file": {
            "type": "string",
            "description": "Relative path of the file to write the analysis to."
        },
        "instruction": {
            "type": "string",
            "description": "What analysis or transformation to perform on the file content."
        }
    }
    output_type = "string"

    def __init__(self, workspace_dir: str, model_callable=None, **kwargs):
        super().__init__(**kwargs)
        self.workspace_dir = Path(workspace_dir).resolve()
        self.model_callable = model_callable

    def _resolve(self, relpath: str) -> Path:
        target = (self.workspace_dir / relpath).resolve()
        if not str(target).startswith(str(self.workspace_dir)):
            raise ValueError(f"Access denied: '{relpath}' is outside workspace.")
        return target

    def forward(self, input_file: str, output_file: str, instruction: str) -> str:
        # ---- Step 1: Read (Python, not LLM) ----
        try:
            input_path = self._resolve(input_file)
        except ValueError as e:
            return f"Error: {e}"
        if not input_path.exists():
            return f"Error: File not found at '{input_file}'."
        content = input_path.read_text(encoding="utf-8")

        # ---- Step 2: Analyze (LLM call, outside agent's code block) ----
        if self.model_callable is None:
            return "Error: No model available for chain analysis."

        analysis_prompt = (
            f"请根据以下指令分析文件内容。直接输出分析结果，不要输出其他内容。\n\n"
            f"=== 文件内容 ===\n{content}\n=== 文件结束 ===\n\n"
            f"分析指令: {instruction}"
        )
        analysis = self.model_callable(analysis_prompt)

        # ---- Step 3: Write (Python, LLM never sees this) ----
        try:
            output_path = self._resolve(output_file)
        except ValueError as e:
            return f"Error: {e}"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(analysis, encoding="utf-8")

        return f"Analysis complete. Written to '{output_file}'.\n\n{analysis}"


def make_llm_callable():
    """Create a simple LLM completion callable using the same env config as tests."""
    from openai import OpenAI

    client = OpenAI(
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_API_URL"),
    )
    model = os.getenv("LLM_MODEL_NAME")

    def call(prompt: str) -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        return response.choices[0].message.content

    return call


# =============================================================================
# Register tools into nexent_agent's namespace so create_local_tool can find them
# =============================================================================

import nexent.core.agents.nexent_agent as na
na.__dict__["ReadFileTool"] = ReadFileTool
na.__dict__["WriteFileTool"] = WriteFileTool
na.__dict__["ReadAnalyzeWriteTool"] = ReadAnalyzeWriteTool

# =============================================================================
# ToolConfig factories
# =============================================================================

from nexent.core.agents.agent_model import ToolConfig


def make_read_tool_config(workspace_dir: str) -> ToolConfig:
    return ToolConfig(
        class_name="ReadFileTool",
        name="read_file",
        description=ReadFileTool.description,
        inputs='{"file_path": "str"}',
        output_type="string",
        params={"workspace_dir": workspace_dir},
        source="local",
    )


def make_write_tool_config(workspace_dir: str) -> ToolConfig:
    return ToolConfig(
        class_name="WriteFileTool",
        name="write_file",
        description=WriteFileTool.description,
        inputs='{"file_path": "str", "content": "str"}',
        output_type="string",
        params={"workspace_dir": workspace_dir},
        source="local",
    )


def make_read_analyze_write_tool_config(workspace_dir: str, model_callable=None) -> ToolConfig:
    return ToolConfig(
        class_name="ReadAnalyzeWriteTool",
        name="read_analyze_write",
        description=ReadAnalyzeWriteTool.description,
        inputs='{"input_file": "str", "output_file": "str", "instruction": "str"}',
        output_type="string",
        params={"workspace_dir": workspace_dir, "model_callable": model_callable},
        source="local",
    )


# =============================================================================
# Test Scenarios
# =============================================================================

async def test_read_file():
    """Test agent using read_file to read a known file in the workspace."""
    ws = WORKSPACE_DIR / "test_read_file"
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True, exist_ok=True)

    # Pre-create files for the agent to read
    (ws / "sample.txt").write_text("Hello from the custom read_file tool!\nLine 2.", encoding="utf-8")
    (ws / "data.json").write_text('{"key": "value", "count": 42}', encoding="utf-8")

    print(f"\nWorkspace: {ws}")
    print("Pre-created files: sample.txt, data.json")

    tools = [make_read_tool_config(str(ws)), make_write_tool_config(str(ws))]

    agent_run_info = build_agent_run_info(
        query="请用 read_file 读取 sample.txt 的内容，然后用 write_file 把内容复制到 copy.txt（只复制文本内容，不要改动）。",
        history=[],
        tools=tools,
        max_steps=5,
        agent_name="file_agent",
        agent_description="A file operation agent that can read and write files in the workspace.",
    )

    result = await run_agent_with_tracking(agent_run_info, debug=False)
    print(f"\nFinal Answer:\n{result.final_answer}")
    print(f"Message counts: {result.message_type_count}")

    # Verify that copy.txt was actually created
    copy_path = ws / "copy.txt"
    if copy_path.exists():
        print(f"\n[OK] copy.txt created, content:\n{copy_path.read_text('utf-8')}")
    else:
        print(f"\n[FAIL] copy.txt was NOT created.")


async def test_read_ana_file():
    """Test agent using read_file to read a known file in the workspace."""
    ws = WORKSPACE_DIR / "test_read_ana_file"
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True, exist_ok=True) 
    # Pre-create files for the agent to read 
    content = \
    """
    项目来源：大模型 Agent 正在从对话式助手向长期任务执行、跨工具操作与多主体协作演进（如 OpenClaw、Hermes、OpenHands）。随着 Agent 
    进入生产环境，核心瓶颈逐渐从模型单步推理转向上下文资源管理：长期运行会持续产生任务状态、计划、证据、记忆、技能等异构资源，并带来
    上下文膨胀、信息噪声、证据过期、检索漂移与成本失控等问题；多 Agent 协作还要求资源在不同角色间共享、隔离、复用，处理并发修改、状态
    冲突与一致性维护。现有基于内存、向量库或日志的方案缺乏系统性，难以支撑上下文建模、分层加载、生命周期治理、上下文组装与冲突检测。
    现有合作项目拟构建面向生产级 Agent 的上下文文件系统 AGFS，系统管理 Agent 运行中产生、变化与复用的上下文资源。
    市场环境：2025年是AI Agent元年，2026年Agent则从概念走向交付，进入“可长期执行任务、跨系统协作”的生产化阶段。市场需求不再只是模型能力，
    而是围绕上下文、状态、权限、记忆和工具调用的基础设施能力。OpenAI发布支持百万token上下文和自主校验的GPT-5.5及Workspace Agents；微软
    深化Agent间协作与记忆能力，支持MCP跨系统标准；Salesforce、ServiceNow等巨头全面重构Agent-first产品线。AI Agent正从辅助工具进化为新
    型数字劳动力，重新定义企业软件的协作底层逻辑，预计到2035年将驱动超4500亿美元企业应用收入。IDC预测，到2030年全球活跃Agent数量将超22亿。
    友商或业界标杆情况等：目前相关友商和开源项目开始围绕“Agent 上下文/文件系统化”形成早期竞争格局。OpenViking 是较直接的竞品，定位为面向
    AI Agent 的开源 Context Database，主张用文件系统范式统一管理 memory、resources、skills，并支持层级化上下文供给和自演进；c4pt0r/agfs
    则以 Plan 9“万物皆文件”为理念，将消息队列、数据库、对象存储、KV 等后端服务抽象为文件操作，适合多 Agent 任务分发和工具接口统一；Turso 
    的 AgentFS 更偏安全隔离和可审计运行环境，用 SQLite-backed filesystem 支撑 Agent 使用真实 CLI 工具、保留操作日志和可恢复状态；AIGNE
    Framework 的 AFS 则是框架内虚拟文件系统，提供对本地文件、对话历史、用户画像等后端的一致访问接口。总体看，友商已验证“Agent 需要文件系统
    式上下文底座”这一方
    """
    (ws / "sample.txt").write_text(content, encoding="utf-8")
    (ws / "data.json").write_text('{"key": "value", "count": 42}', encoding="utf-8")
    print(f"\nWorkspace: {ws}")

    tools = [make_read_tool_config(str(ws)), make_write_tool_config(str(ws))]

    cm_config = ContextManagerConfig(
        enabled=True,
        token_threshold=8000,
        keep_recent_steps=2,
    )
    shared_cm = ContextManager(config=cm_config, max_steps=5)

    agent_run_info = build_agent_run_info(
        query="请用 read_file 读取 sample.txt 的内容，然后对其内容进行分析和总结，请直接调用 write_file 工具将分析结果写入文件 ana.txt，不要在调用工具前打印或输出分析的具体内容，只需简单说明你正在做什么即可。" ,
        history=[],
        tools=tools,
        max_steps=5,
        agent_name="file_agent",
        agent_description="A file operation agent that can read and write files in the workspace.",
        context_manager_config=cm_config,
    )
    agent_run_info.context_manager = shared_cm

    result = await run_agent_with_tracking(agent_run_info, debug=False)
    print(f"\nFinal Answer:\n{result.final_answer}")
    print(f"Message counts: {result.message_type_count}")

    stats = shared_cm.get_all_compression_stats()
    print(f"[ContextManager Stats] {stats}")

    # Verify that ana.txt was actually created
    ana_path = ws / "ana.txt"
    if ana_path.exists():
        print(f"\n[OK] ana.txt created, content:\n{ana_path.read_text('utf-8')}")
    else:
        print(f"\n[FAIL] ana.txt was NOT created.")

async def test_read_write_workflow():
    """Test agent composing a multi-step read → transform → write workflow."""
    ws = WORKSPACE_DIR / "test_read_write_workflow"
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True, exist_ok=True)

    # Create test data
    (ws / "numbers.txt").write_text("10\n20\n30\n40\n50", encoding="utf-8")

    print(f"\nWorkspace: {ws}")
    print("Pre-created file: numbers.txt (contains 5 numbers)")

    tools = [make_read_tool_config(str(ws)), make_write_tool_config(str(ws))]

    agent_run_info = build_agent_run_info(
        query=(
            "请用 read_file 读取 numbers.txt 的内容，计算这些数字的总和与平均值，"
            "然后用 write_file 把结果（总和、平均值）写入 result.txt，格式为 JSON: "
            '{"sum": ..., "average": ...}'
        ),
        history=[],
        tools=tools,
        max_steps=6,
        agent_name="file_agent",
        agent_description="A file operation agent that can read and write files in the workspace.",
    )

    result = await run_agent_with_tracking(agent_run_info, debug=False)
    print(f"\nFinal Answer:\n{result.final_answer}")
    print(f"Message counts: {result.message_type_count}")

    result_path = ws / "result.txt"
    if result_path.exists():
        print(f"\n[OK] result.txt created, content:\n{result_path.read_text('utf-8')}")
    else:
        print(f"\n[FAIL] result.txt was NOT created.")


async def test_read_with_history():
    """Test agent with conversation history and tools."""
    base_history = parse_conversation_to_history("./small_history.md")
    print_history_stats(base_history)

    ws = WORKSPACE_DIR / "test_read_with_history"
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True, exist_ok=True)

    (ws / "notes.txt").write_text("Meeting notes:\n- Discuss Q2 roadmap\n- Review budget", encoding="utf-8")

    print(f"\nWorkspace: {ws}")
    print("Pre-created file: notes.txt")

    tools = [make_read_tool_config(str(ws))]

    agent_run_info = build_agent_run_info(
        query="请用 read_file 读取 notes.txt，并总结其中的内容。",
        history=base_history,
        tools=tools,
        max_steps=4,
        agent_name="file_agent",
        agent_description="A file operation agent that can read and write files in the workspace.",
    )

    result = await run_agent_with_tracking(agent_run_info, debug=False)
    print(f"\nFinal Answer:\n{result.final_answer}")
    print(f"Message counts: {result.message_type_count}")


async def test_chain_read_analyze_write():
    """Chain pattern: read → LLM analyze → write, all in one tool call.

    Token comparison with Agent pattern (test_read_ana_file):
      Agent:  analysis appears TWICE  (code block + write_file arg)  → ~2x tokens
      Chain:  analysis appears ONCE   (only as tool return)           → ~1x tokens
    """
    ws = WORKSPACE_DIR / "test_chain"
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True, exist_ok=True)

    (ws / "sample.txt").write_text(
        "Hello from the custom read_file tool!\nLine 2.", encoding="utf-8")

    print(f"\nWorkspace: {ws}")
    print("Pre-created file: sample.txt")

    model_callable = make_llm_callable()
    tools = [make_read_analyze_write_tool_config(str(ws), model_callable)]

    agent_run_info = build_agent_run_info(
        query=(
            "请用 read_analyze_write 工具读取 sample.txt，分析其内容并总结，"
            "将结果写入 ana.txt。分析指令：总结文件中的关键信息和主题。"
        ),
        history=[],
        tools=tools,
        max_steps=3,
        agent_name="chain_agent",
        agent_description="A chain agent that uses read_analyze_write for file analysis.",
    )

    result = await run_agent_with_tracking(agent_run_info, debug=True)
    print(f"\nFinal Answer:\n{result.final_answer}")
    print(f"Message counts: {result.message_type_count}")

    ana_path = ws / "ana.txt"
    if ana_path.exists():
        print(f"\n[OK] ana.txt created, content:\n{ana_path.read_text('utf-8')}")
    else:
        print(f"\n[FAIL] ana.txt was NOT created.")


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Running: test_read_ana_file  (Agent pattern — analysis duplicated)")
    print("=" * 60)
    asyncio.run(test_read_ana_file())

    print("\n" + "=" * 60)
    print("Running: test_chain_read_analyze_write  (Chain pattern — no duplication)")
    print("=" * 60)
    # asyncio.run(test_chain_read_analyze_write())