"""Context component building utilities for system prompt assembly.

Provides build_context_components() to convert agent configuration data
into ContextComponent instances for use with ContextManager.

This module implements the piecewise component architecture where each
semantic section of the system prompt is emitted by a dedicated function,
allowing ContextManager to assemble them in the correct order.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from nexent.core.agents.agent_model import (
        ContextComponent,
        ToolsComponent,
        SkillsComponent,
        MemoryComponent,
        KnowledgeBaseComponent,
        ManagedAgentsComponent,
        ExternalAgentsComponent,
        SystemPromptComponent,
        ToolConfig,
        AgentConfig,
        ExternalA2AAgentConfig,
    )


# =============================================================================
# SECTION 1: Long-text format functions (expanded from Jinja2 templates)
# Each function accepts language and is_manager params for variant-specific text
# =============================================================================


def _format_memory_context(
    memory_list: List[Any],
    language: str = "zh",
) -> str:
    """Format memory search results with full usage guidelines.

    Jinja2 templates have ~30 lines of "记忆使用准则" text that must be
    included here for semantic equivalence.
    """
    if not memory_list:
        return ""

    # Group memories by level in correct order: tenant, user_agent, user, agent
    level_order = ["tenant", "user_agent", "user", "agent"]
    memory_by_level: Dict[str, List[Any]] = {}
    for mem in memory_list:
        if isinstance(mem, dict):
            level = mem.get("memory_level", "user")
            if level not in memory_by_level:
                memory_by_level[level] = []
            memory_by_level[level].append(mem)

    lines = []

    if language == "zh":
        lines.append("### 上下文记忆")
        lines.append("基于之前的交互记录，以下是按作用域和重要程度排序的最相关记忆：")
        lines.append("")

        for level in level_order:
            if level in memory_by_level:
                level_title = {
                    "tenant": "Tenant",
                    "user_agent": "User_agent",
                    "user": "User",
                    "agent": "Agent",
                }.get(level, level.title())
                lines.append(f"**{level_title} 层级记忆：**")
                for item in memory_by_level[level]:
                    content = item.get("memory", "") or item.get("content", "")
                    score = item.get("score", 0.0)
                    lines.append(f"- {content} `({score:.2f})`")
                lines.append("")

        lines.append("**记忆使用准则：**")
        lines.append("1. **冲突处理优先级**：当记忆信息存在矛盾时，严格按以下顺序处理：")
        lines.append("- **最优先**：在上述列表中位置靠前的记忆具有优先权")
        lines.append("- **次优先**：当前对话内容与记忆直接冲突时，以当前对话为准")
        lines.append("- **次优先**：相关度分数越高，表示记忆越可信")
        lines.append("")
        lines.append("2. **记忆整合最佳实践**：")
        lines.append("  - 自然地将相关记忆融入回答中，避免显式使用\"根据记忆\"、\"根据上下文\"或\"根据交互记忆\"等语言")
        lines.append("  - 利用记忆信息调整回答的语调、方式和技术深度以适应用户")
        lines.append("  - 让记忆指导您对用户偏好和上下文的理解")
        lines.append("")
        lines.append("3. **级别特定说明**：")
        lines.append("  - **tenant（租户级）**：组织层面的约束和政策（不可违背）")
        lines.append("  - **user_agent（用户-代理级）**：特定用户在代理中的交互模式和既定工作流程")
        lines.append("  - **user（用户级）**：用户的个人偏好、技能水平和历史上下文")
        lines.append("  - **agent（代理级）**：您的既定行为模式和能力特征，通常对所有用户共享（重要性最低）")
    else:
        lines.append("### Contextual Memory")
        lines.append("Based on previous interactions, here are the most relevant memories organized by scope and importance:")
        lines.append("")

        for level in level_order:
            if level in memory_by_level:
                lines.append(f"**{level.title()} Level Memory:**")
                for item in memory_by_level[level]:
                    content = item.get("memory", "") or item.get("content", "")
                    score = item.get("score", 0.0)
                    lines.append(f"- {content} `({score:.2f})`")
                lines.append("")

        lines.append("**Memory Usage Guidelines:**")
        lines.append("1. **Conflict Resolution Priority**: When memories contradict each other, follow this strict order:")
        lines.append("   - **Primary**: Information appearing EARLIER in the above numbered list takes precedence")
        lines.append("   - **Secondary**: Current conversation context overrides historical memory when directly contradicted")
        lines.append("   - **Tertiary**: Higher relevance scores indicate more trustworthy information")
        lines.append("")
        lines.append("2. **Memory Integration Best Practices**:")
        lines.append("   - Seamlessly weave relevant memories into your responses without explicitly saying \"I remember\", \"based on memory\" or \"based on context\"")
        lines.append("   - Use memories to inform your tone, approach, and technical level appropriate for this user")
        lines.append("   - Let memories guide your assumptions about user preferences and context")
        lines.append("")
        lines.append("3. **Level-Specific Considerations**:")
        lines.append("   - **tenant**: Organizational constraints and policies (non-negotiable)")
        lines.append("   - **user_agent**: Specific interaction dynamics and established workflow patterns")
        lines.append("   - **user**: Individual preferences, skills, and historical context")
        lines.append("   - **agent**: Your established behavioral patterns and capabilities, usually shared by all users (least important)")

    return "\n".join(lines)


def _format_skills_description(
    skills: List[Dict[str, str]],
    language: str = "zh",
) -> str:
    """Format skill descriptions with full 6-step usage process.

    Jinja2 templates have ~50 lines of "技能使用流程" text that must be
    included here for semantic equivalence.
    """
    if not skills:
        return ""

    lines = []

    # Build the <available_skills> block
    skills_block_lines = ["<available_skills>"]
    for skill in skills:
        name = skill.get("name", "")
        desc = skill.get("description", "")
        skills_block_lines.append("  <skill>")
        skills_block_lines.append(f"    <name>{name}</name>")
        skills_block_lines.append(f"    <description>{desc}</description>")
        skills_block_lines.append("  </skill>")
    skills_block_lines.append("</available_skills>")
    skills_block = "\n".join(skills_block_lines)

    if language == "zh":
        lines.append("### 可用技能")
        lines.append("")
        lines.append("你拥有以下技能（Skills）。技能是预定义的专业能力模块，包含详细执行指南和可选的附加脚本。")
        lines.append("")
        lines.append(skills_block)
        lines.append("")
        lines.append("**技能使用流程**：")
        lines.append("1. 收到用户请求后，首先审视 `<available_skills>` 中每个技能的 description，判断是否有匹配的技能。")
        lines.append("2. **加载技能**：根据不同场景选择读取方式：")
        lines.append("   - **首次加载**：调用 `read_skill_md(\"skill_name\")` 读取技能的完整执行指南（默认读取 SKILL.md）")
        lines.append("   - **精确读取**：如只需特定文件（如示例、参考文档），可指定 additional_files：")
        lines.append("   <code>")
        lines.append("   skill_content = read_skill_md(\"skill_name\", [\"examples.md\", \"reference/api_doc\"])")
        lines.append("   print(skill_content)")
        lines.append("   </code>")
        lines.append("   注意：当 additional_files 非空时，默认不再自动读取 SKILL.md，如需同时读取请显式指定。")
        lines.append("")
        lines.append("   - **加载技能配置**：如果技能需要读取配置变量，可先调用 `read_skill_config(\"skill_name\")` 读取配置字符串，通过 `json.loads` 方法转化为配置字典，再从中获取所需值：")
        lines.append("   <code>")
        lines.append("   import json")
        lines.append("   config = json.loads(read_skill_config(\"skill_name\"))")
        lines.append("   # 返回示例: {\"key_a\": {\"key2\": \"value2\"}, \"others\": {...}}")
        lines.append("   value = config[\"key1\"][\"key2\"]")
        lines.append("   print(value)")
        lines.append("   </code>")
        lines.append("")
        lines.append("3. **遵循技能指南**：技能内容注入后，严格按其中的步骤执行。不要跳过技能指南中的步骤，也不要用自行编写的代码替代技能定义的流程。")
        lines.append("")
        lines.append("4. **执行技能脚本**：如果技能指南中引用了附加脚本（形如 `<use_script path=\"script_path\" />`），使用以下格式调用：")
        lines.append("   代码：")
        lines.append("   <code>")
        lines.append("   result = run_skill_script(\"skill_name\", \"script_path\")")
        lines.append("   print(result)")
        lines.append("   </code>")
        lines.append("   对于需要附加参数的脚本，需要参照脚本调用说明，将参数直接以字符串形式传递。")
        lines.append("   例如对于希望附加的参数：--param1 value1 --flag，则使用以下格式调用run_skill_script：")
        lines.append("   <code>")
        lines.append("   result = run_skill_script(\"skill_name\", \"script_path\", \"--param1 value1 --flag\")")
        lines.append("   print(result)")
        lines.append("   </code>")
        lines.append("   注意：只执行技能指南中明确声明的脚本路径，绝不自行构造脚本路径。")
        lines.append("")
        lines.append("5. **整合输出**：根据技能指南要求的输出格式，结合脚本执行结果生成最终回答。")
        lines.append("")
        lines.append("6. **引用场景处理**：当技能内容中出现引用标记或需要引用其他文件时，需要识别并再次调用 read_skill_md：")
        lines.append("   - **引用模板识别**：注意技能内容中形如 `<reference path=\"script_path\" />` 或自然语言式的引用声明（如\"详见 examples.md\"、\"请参考 reference/api_doc\"）")
        lines.append("   - **自动补全**：发现引用后，尝试读取被引用的文件获取更多信息")
        lines.append("   - **示例**：")
        lines.append("   <code>")
        lines.append("   # 技能内容提示\"请参考 examples.md 获取详细示例\"")
        lines.append("   additional_info = read_skill_md(\"skill_name\", [\"examples.md\"])")
        lines.append("   print(additional_info)")
        lines.append("   </code>")
    else:
        lines.append("### Available Skills")
        lines.append("")
        lines.append("You have the following Skills. Skills are predefined professional capability modules with detailed execution guides and optional additional scripts.")
        lines.append("")
        lines.append(skills_block)
        lines.append("")
        lines.append("**Skill Usage Process**:")
        lines.append("1. After receiving a user request, first examine the description of each skill in `<available_skills>` to determine if there is a matching skill.")
        lines.append("2. **Load Skill**: Choose the appropriate reading method based on the scenario:")
        lines.append("   - **First-time load**: Call `read_skill_md(\"skill_name\")` to read the complete execution guide (defaults to reading SKILL.md)")
        lines.append("   - **Precise read**: If you only need specific files (like examples, reference docs), specify additional_files:")
        lines.append("   <code>")
        lines.append("   skill_content = read_skill_md(\"skill_name\", [\"examples.md\", \"reference/api_doc\"])")
        lines.append("   print(skill_content)")
        lines.append("   </code>")
        lines.append("   Note: When additional_files is non-empty, SKILL.md is no longer auto-read. If you need both, explicitly specify it.")
        lines.append("")
        lines.append("   - **Load skill config**: If the skill needs configuration variables, call `read_skill_config(\"skill_name\")` to read the config string, convert to dict via `json.loads`, then access values:")
        lines.append("   <code>")
        lines.append("   import json")
        lines.append("   config = json.loads(read_skill_config(\"skill_name\"))")
        lines.append("   # Example: {\"key_a\": {\"key2\": \"value2\"}, \"others\": {...}}")
        lines.append("   value = config[\"key1\"][\"key2\"]")
        lines.append("   print(value)")
        lines.append("   </code>")
        lines.append("")
        lines.append("3. **Follow Skill Guide**: After skill content is injected, strictly follow its steps. Do not skip steps or replace with your own code.")
        lines.append("")
        lines.append("4. **Execute Skill Script**: If the skill guide references additional scripts (like `<use_script path=\"script_path\" />`), call:")
        lines.append("   <code>")
        lines.append("   result = run_skill_script(\"skill_name\", \"script_path\")")
        lines.append("   print(result)")
        lines.append("   </code>")
        lines.append("   For scripts needing extra params, pass them as a command-line string per the script's calling instructions.")
        lines.append("   Example for --param1 value1 --flag:")
        lines.append("   <code>")
        lines.append("   result = run_skill_script(\"skill_name\", \"script_path\", \"--param1 value1 --flag\")")
        lines.append("   print(result)")
        lines.append("   </code>")
        lines.append("   Note: Only execute script paths explicitly declared in the skill guide. Never construct paths yourself.")
        lines.append("")
        lines.append("5. **Integrate Output**: Generate the final answer based on the skill guide's output format and script execution results.")
        lines.append("")
        lines.append("6. **Handle References**: When the skill content has reference markers or needs to reference other files, identify and call read_skill_md again:")
        lines.append("   - **Reference template recognition**: Look for patterns like `<reference path=\"file_path\" />` or natural-language references (\"see examples.md\", \"refer to reference/api_doc\")")
        lines.append("   - **Auto-complete**: After discovering a reference, try reading the referenced file for more info")
        lines.append("   - **Example**:")
        lines.append("   <code>")
        lines.append("   # Skill content says \"see examples.md for detailed examples\"")
        lines.append("   additional_info = read_skill_md(\"skill_name\", [\"examples.md\"])")
        lines.append("   print(additional_info)")
        lines.append("   </code>")

    return "\n".join(lines)


def _format_tools_description(
    tools: Dict[str, Any],
    knowledge_base_summary: Optional[str] = None,
    language: str = "zh",
    is_manager: bool = True,
) -> str:
    """Format tool descriptions with file URL usage guide.

    Jinja2 templates have ~10 lines of "文件链接使用指南" text that must be
    included here for semantic equivalence.

    Note: Managed agents use different presigned_url guidance than manager agents.
    """
    if not tools:
        no_tools_msg = "- 当前没有可用的工具" if language == "zh" else "- No tools are currently available"
        return no_tools_msg

    lines = []

    if language == "zh":
        lines.append("- 你只能使用以下工具，不得使用任何其他工具：")
    else:
        lines.append("- You can only use the following tools and may not use any other tools:")

    for name, tool in tools.items():
        if hasattr(tool, 'description'):
            desc = tool.description
            inputs = tool.inputs
            output_type = tool.output_type
            source = getattr(tool, 'source', 'local')
        else:
            desc = tool.get('description', '')
            inputs = tool.get('inputs', '')
            output_type = tool.get('output_type', '')
            source = tool.get('source', 'local')

        # MCP tools have [MCP] prefix
        if source == 'mcp':
            if language == "zh":
                lines.append(f"- [MCP] {name}: {desc}")
                lines.append(f"   接受输入: {inputs}")
                lines.append(f"   返回输出类型: {output_type}")
            else:
                lines.append(f"- [MCP] {name}: {desc}")
                lines.append(f"   Accepts input: {inputs}")
                lines.append(f"   Returns output type: {output_type}")
        else:
            if language == "zh":
                lines.append(f"- {name}: {desc}")
                lines.append(f"   接受输入: {inputs}")
                lines.append(f"   返回输出类型: {output_type}")
            else:
                lines.append(f"- {name}: {desc}")
                lines.append(f"   Accepts input: {inputs}")
                lines.append(f"   Returns output type: {output_type}")

    # Knowledge base summary
    if knowledge_base_summary:
        if language == "zh":
            lines.append("- knowledge_base_search工具只能使用以下知识库索引，请根据用户问题选择最相关的一个或多个知识库索引：")
            lines.append(f" {knowledge_base_summary}")
        else:
            lines.append("- knowledge_base_search tool can only use the following knowledge base indexes, please select the most relevant one or more knowledge base indexes based on the user's question:")
            lines.append(f" {knowledge_base_summary}")

    # File URL usage guide
    lines.append("")
    if language == "zh":
        lines.append("### 文件链接使用指南")
        lines.append("当处理用户上传的文件时，请根据工具类型选择正确的 URL：")
        lines.append("1. **调用标记为 [MCP] 的工具**（外部工具，运行在 Nexent 之外）：")
        if is_manager:
            lines.append("   → 使用 **Download URL**（格式：`https://minio.example.com/...?token=xxx`）")
            lines.append("   原因：MCP 工具运行在外部服务，无法访问内部 S3 存储")
        else:
            lines.append("   → 使用 **presigned_url**（已包含代理前缀，格式：`http://.../api/nb/v1/file/fetch?presigned_url=...`）")
            lines.append("   直接使用用户上传文件信息中提供的 **presigned_url** 字段，无需拼接。")
        lines.append("2. **调用其他所有工具**（内部工具，如 analyze_text_file、analyze_image 等）：")
        lines.append("   → 使用 **S3 URL**（格式：`s3:/nexent/attachments/xxx.pdf`）")
        lines.append("   原因：内部工具运行在 Nexent 内部，可以直接访问 MinIO 存储")
    else:
        lines.append("### File URL Usage Guide")
        lines.append("When processing user-uploaded files, choose the correct URL based on tool type:")
        lines.append("1. **Calling tools marked with [MCP]** (external tools that run outside Nexent):")
        if is_manager:
            lines.append("   → Use **Download URL** (format: `https://minio.example.com/...?token=xxx`)")
            lines.append("   Reason: MCP tools run on external services and cannot access internal S3 storage")
        else:
            lines.append("   → Use **presigned_url** (already includes proxy prefix, format: `http://.../api/nb/v1/file/fetch?presigned_url=...`)")
            lines.append("   Directly use the **presigned_url** field provided in the user's uploaded file info. No need to construct or append anything.")
        lines.append("2. **Calling all other tools** (internal tools like analyze_text_file, analyze_image):")
        lines.append("   → Use **S3 URL** (format: `s3:/nexent/attachments/xxx.pdf`)")
        lines.append("   Reason: Internal tools run inside Nexent and can directly access MinIO storage")

    return "\n".join(lines)


def _format_managed_agents_description(
    managed_agents: Dict[str, Any],
    language: str = "zh",
) -> str:
    """Format managed sub-agent descriptions with calling specifications.

    Jinja2 templates have ~15 lines of "内部助手调用规范" text that must be
    included here for semantic equivalence.
    """
    if not managed_agents:
        return ""

    lines = []

    if language == "zh":
        lines.append("你可以使用以下内部助手（通过函数调用方式协作）：")
        for name, agent in managed_agents.items():
            desc = agent.description if hasattr(agent, 'description') else agent.get('description', '')
            lines.append(f" - {name}: {desc}")
        lines.append("")
        lines.append("内部助手调用规范：")
        lines.append("  1. 调用方式：")
        lines.append("     - 接受输入：{\"task\": {\"type\": \"string\", \"description\": \"任务描述\"}}")
        lines.append("     - 返回输出类型：{\"type\": \"string\", \"description\": \"执行结果\"}")
        lines.append("  2. 使用策略：")
        lines.append("     - 任务分解：单次调用中不要让助手一次做过多的事情，任务拆分是你的工作，你需要将复杂任务分解为可管理的子任务")
        lines.append("     - 专业匹配：根据助手的专长分配任务")
        lines.append("     - 信息整合：整合不同助手的输出生成连贯解决方案")
        lines.append("     - 效率优化：避免重复工作")
        lines.append("  3. 协作要求：")
        lines.append("     - 评估助手返回的结果")
        lines.append("     - 必要时提供额外指导或重新分配任务")
        lines.append("     - 在助手结果基础上进行工作，避免重复工作")
        lines.append("     - 注意保留子助手回答中的特殊符号，如索引溯源信息等")
    else:
        lines.append("You can use the following internal agents (via function calls):")
        for name, agent in managed_agents.items():
            desc = agent.description if hasattr(agent, 'description') else agent.get('description', '')
            lines.append(f" - {name}: {desc}")
        lines.append("")
        lines.append("Internal agent calling specifications:")
        lines.append("   1. Calling method:")
        lines.append("      - Accepts input: {\"task\": {\"type\": \"string\", \"description\": \"task description\"}}")
        lines.append("      - Returns output type: {\"type\": \"string\", \"description\": \"execution result\"}")
        lines.append("   2. Usage strategy:")
        lines.append("      - Task decomposition: Don't let agents do too many things in a single call, task breakdown is your job, you need to decompose complex tasks into manageable subtasks")
        lines.append("      - Professional matching: Assign tasks based on agent expertise")
        lines.append("      - Information integration: Integrate outputs from different agents to generate coherent solutions")
        lines.append("      - Efficiency optimization: Avoid duplicate work")
        lines.append("   3. Collaboration requirements:")
        lines.append("      - Evaluate agent returned results")
        lines.append("      - Provide additional guidance or reassign tasks when necessary")
        lines.append("      - Work based on agent results, avoid duplicate work")
        lines.append("      - Pay attention to preserving special symbols in sub-agent answers, such as index traceability information")

    return "\n".join(lines)


def _format_external_agents_description(
    external_a2a_agents: Dict[str, Any],
    language: str = "zh",
) -> str:
    """Format external A2A agent descriptions with calling specifications.

    Jinja2 templates have ~5 lines of "外部助手调用规范" text that must be
    included here for semantic equivalence.
    """
    if not external_a2a_agents:
        return ""

    lines = []

    if language == "zh":
        lines.append("你还可以使用以下外部助手（通过 A2A 协议远程调用）：")
        for agent_id, agent in external_a2a_agents.items():
            name = agent.name if hasattr(agent, 'name') else agent.get('name', '')
            desc = agent.description if hasattr(agent, 'description') else agent.get('description', '')
            lines.append(f" - {name}: {desc}")
        lines.append("")
        lines.append("外部助手调用规范：")
        lines.append("  1. 调用格式：`agent_name(task=\"自然语言任务描述\")`，注意：只需要 task 参数，不需要其他参数")
        lines.append("  2. 例如：`tool_assistant(task=\"北京天气怎么样\")`")
        lines.append("  3. 任务描述使用自然语言，让外部助手自动识别和处理")
    else:
        lines.append("You can also use the following external agents (called via A2A protocol remotely):")
        for agent_id, agent in external_a2a_agents.items():
            name = agent.name if hasattr(agent, 'name') else agent.get('name', '')
            desc = agent.description if hasattr(agent, 'description') else agent.get('description', '')
            lines.append(f" - {name}: {desc}")
        lines.append("")
        lines.append("External agent calling specifications:")
        lines.append("   1. Call format: `agent_name(task=\"natural language task description\")`, NOTE: only task parameter is needed, no other parameters")
        lines.append("   2. Example: `tool_assistant(task=\"What's the weather in Beijing?\")`")
        lines.append("   3. Use natural language for task description, let the external agent handle the rest")

    return "\n".join(lines)


def _format_skills_usage_requirements(
    skills: List[Dict[str, str]],
    language: str = "zh",
) -> str:
    """Format skills usage requirements section.

    This is the "技能使用要求" section that appears after the skills reference
    in the Available Resources section.
    """
    if not skills:
        no_skills_msg = "- 当前没有可用的技能" if language == "zh" else "- No skills are currently available"
        return no_skills_msg

    lines = []

    if language == "zh":
        lines.append("- 你拥有上述 `<available_skills>` 中列出的技能。技能中引用的脚本通过 `run_skill_script()` 函数调用，该函数由平台提供，不需要导入。")
        lines.append("")
        lines.append("### 技能使用要求")
        lines.append("1. **技能优先**：如果用户请求匹配了某个技能的 description，必须先调用 `read_skill_md()` 加载技能指南，再按指南执行。不得跳过技能自行编写代码解决。")
        lines.append("2. **忠实执行**：读取技能内容后，严格按技能指南中的步骤操作。不要自行修改流程、跳过步骤或用通用代码替代技能定义的流程。")
        lines.append("3. **脚本调用规范**：只使用 `run_skill_script` 工具执行技能指南中明确要求的脚本。传入的 `skill_name` 和 `script_path` 必须与技能指南中的声明完全一致，不要自行拼接或猜测路径。如果需要附加参数，将参数以命令行字符串形式传递给`run_skill_script`。")
        lines.append("4. **失败回退**：如果 `read_skill_md` 返回错误或 `run_skill_script` 执行失败，向用户说明情况，并尝试用通用推理模式提供替代方案。")
        lines.append("5. **技能组合**：如果一个任务需要多个技能配合，按逻辑依赖顺序依次加载和执行，前一个技能的输出可作为后一个技能的输入。")
    else:
        lines.append("- You have the skills listed in `<available_skills>` above. Scripts referenced in skills are called via the `run_skill_script()` function, which is provided by the platform and does not need to be imported.")
        lines.append("")
        lines.append("### Skill Usage Requirements")
        lines.append("1. **Skill Priority**: If a user request matches a skill's description, you must first call `read_skill_md()` to load the skill guide, then execute per the guide. Do not skip skills and write your own code.")
        lines.append("2. **Faithful Execution**: After reading skill content, strictly follow the skill guide's steps. Do not modify the flow, skip steps, or replace with generic code.")
        lines.append("3. **Script Calling Specification**: Only use `run_skill_script` to execute scripts explicitly required in the skill guide. The `skill_name` and `script_path` must match the skill guide's declaration exactly. Do not construct or guess paths. For extra params, pass them as a command-line string to `run_skill_script`.")
        lines.append("4. **Failure Fallback**: If `read_skill_md` returns an error or `run_skill_script` fails, explain to the user and try to provide an alternative via general reasoning mode.")
        lines.append("5. **Skill Combination**: If a task needs multiple skills, load and execute in logical dependency order. The output of one skill can be input to the next.")

    return "\n".join(lines)


def _format_agent_fallback(
    managed_agents: Dict[str, Any],
    external_a2a_agents: Dict[str, Any],
    language: str = "zh",
) -> str:
    """Format fallback message when no agents are available."""
    if managed_agents or external_a2a_agents:
        return ""

    return "- 当前没有可用的助手" if language == "zh" else "- No agents are currently available"


def _format_app_context(app_name: str, app_description: str, user_id: str, time_str: str) -> str:
    """Format application context for system prompt injection."""
    lines = [
        f"Application: {app_name}",
        f"Description: {app_description}",
        f"Current user: {user_id}",
        f"Current time: {time_str}",
    ]
    return "\n".join(lines)


# =============================================================================
# SECTION 2: Skeleton component builders
# These build SystemPromptComponent instances for fixed text sections
# =============================================================================


def build_skeleton_header_component(
    app_name: str,
    app_description: str,
    time_str: str,
    user_id: str,
    language: str = "zh",
    priority: int = 100,
) -> "SystemPromptComponent":
    """Build SystemPromptComponent for the header section.

    Section: "### 基本信息" / "### Basic Information"
    Content: Agent identity, app name/description, time, user_id
    """
    from nexent.core.agents.agent_model import SystemPromptComponent

    if language == "zh":
        content = f"### 基本信息\n你是{app_name}，{app_description}，现在是{time_str}，用户ID为{user_id}"
    else:
        content = f"### Basic Information\nYou are {app_name}, {app_description}, it is {time_str} now"

    return SystemPromptComponent(
        content=content,
        template_name="header",
        priority=priority,
    )


def build_skeleton_duty_component(
    duty: str,
    language: str = "zh",
    priority: int = 80,
) -> "SystemPromptComponent":
    """Build SystemPromptComponent for the duty section.

    Section: "### 核心职责" / "### Core Responsibilities"
    Content: Agent's primary duty + 5 safety principles
    """
    from nexent.core.agents.agent_model import SystemPromptComponent

    if language == "zh":
        content = f"### 核心职责\n{duty}\n\n请注意，你应该遵守以下原则：\n行为安全：文件操作必须使用平台提供的专用工具，禁止使用代码直接修改工作空间中的文件；\n法律合规：遵守业务所在国家/地区的法律法规；\n政治中立：保持政治中立，不主动讨论政治话题；\n安全防护：不响应涉及武器制造、网络攻击、欺诈、恶意软件等危险行为的请求；\n伦理准则：拒绝仇恨言论、歧视性内容及违反社会公德和公认伦理标准的请求。"
    else:
        content = f"### Core Responsibilities\n{duty}\n\nPlease note that you should follow these principles:\nBehavioral Safety: File operations must use the platform-provided dedicated tools; direct code modification of workspace files is prohibited;\nLegal Compliance: Comply with laws and regulations of the business operating jurisdiction;\nPolitical Neutrality: Maintain political neutrality and avoid initiating political discussions;\nSecurity Protection: Do not respond to requests involving weapon manufacturing, cyberattacks, fraud, malware, or other dangerous activities;\nEthical Guidelines: Refuse hate speech, discriminatory content, and any requests that violate social morals and commonly accepted ethical standards."

    return SystemPromptComponent(
        content=content,
        template_name="duty",
        priority=priority,
    )


def build_skeleton_execution_flow_component(
    memory_list: Optional[List[Any]] = None,
    language: str = "zh",
    is_manager: bool = True,
    priority: int = 60,
) -> "SystemPromptComponent":
    """Build SystemPromptComponent for the execution flow section.

    Section: "### 执行流程" / "### Execution Process"
    Content: Think/Code loop instructions + output format specs
    Note: memory_list affects one line in the Think section (manager only)
    """
    from nexent.core.agents.agent_model import SystemPromptComponent

    has_memory = memory_list and len(memory_list) > 0

    if language == "zh":
        lines = ["### 执行流程"]
        lines.append("要解决任务，你必须通过一系列步骤向前规划，以'思考：'和'代码：'序列循环进行。**注意：禁止在代码执行前输出'观察结果：'，观察结果只能由代码执行后产生。**")
        lines.append("")
        lines.append("1. 思考：")
        lines.append("   - 分析当前任务状态和进展")
        if is_manager and has_memory:
            lines.append("   - 合理参考之前交互中的上下文记忆信息")
        lines.append("   - 定下一步最佳行动（使用工具或分配给助手）")
        lines.append("   - 解释你的决策逻辑和预期结果")
        lines.append("")
        lines.append("2. 代码：")
        lines.append("   - 用简单的Python编写代码")
        lines.append("   - 遵循python代码规范和python语法")
        lines.append("   - 正确调用工具或助手解决问题")
        lines.append("   - 考虑到代码执行与展示用户代码的区别，使用'<code>代码</code>'表达运行代码，使用'<DISPLAY:语言类型>代码</DISPLAY>'表达展示代码")
        lines.append("   - 注意运行的代码不会被用户看到，所以如果用户需要看到代码，你需要使用'<DISPLAY:语言类型>代码</DISPLAY>'表达展示代码。")
        lines.append("   - **重要**：代码执行后，系统会返回 \"Observation:\" 标记的内容（这是真实的执行结果）。请基于这些真实结果继续下一步思考，**不要在代码执行前自行编造观察结果**。")
        lines.append("")
        lines.append("在思考结束后，当你认为可以回答用户问题，那么可以不生成代码，直接生成最终回答给到用户并停止循环。")
        lines.append("")
        lines.append("生成最终回答时，你需要遵循以下规范：")
        lines.append("1. Markdown格式要求：")
        lines.append("  - 使用标准Markdown语法格式化输出，支持标题、列表、表格、代码块、链接等")
        lines.append("  - 展示图片和视频使用链接方式，不需要外套代码块，格式：[链接文本](URL)，图片格式：![alt文本](图片URL)，视频格式：<video src=\"视频URL\" controls></video>")
        lines.append("  - 段落之间使用单个空行分隔，避免多个连续空行")
        lines.append("  - 数学公式使用标准Markdown格式：行内公式用 $公式$，块级公式用 $$公式$$")
        lines.append("")
        lines.append("2. 引用标记规范（仅在使用了检索工具时）：")
        lines.append("  - 引用标记格式必须严格为：`[[字母+数字]]`，例如：`[[a1]]`、`[[b2]]`、`[[c3]]`")
        lines.append("  - 字母部分必须是单个小写字母（a-e），数字部分必须是整数")
        lines.append("  - 引用标记的字母和数字必须与检索工具的检索结果一一对应")
        lines.append("  - 引用标记应紧跟在相关信息或句子之后，通常放在句末或段落末尾")
        lines.append("  - 多个引用标记可以连续使用，例如：`[[a1]][[b2]]`")
        lines.append("  - **重要**：仅添加引用标记，不要添加链接、参考文献列表等多余内容")
        lines.append("  - 如果检索结果中没有匹配的引用，则不显示该引用标记")
        lines.append("")
        lines.append("3. 格式细节要求：")
        lines.append("  - 避免在Markdown中使用HTML标签，优先使用Markdown原生语法")
        lines.append("  - 代码块中的代码应保持原始格式，不要添加额外的转义字符")
        lines.append("  - 若未使用检索工具，则不添加任何引用标记")
    else:
        lines = ["### Execution Process"]
        lines.append("To solve tasks, you must plan forward through a series of steps in a loop of 'Think:' and 'Code:' sequences. **IMPORTANT: You must NOT output 'Observe Results:' before code execution. Observation results can ONLY be generated after code execution.**")
        lines.append("")
        lines.append("1. Think:")
        lines.append("   - Analyze current task status and progress")
        if is_manager and has_memory:
            lines.append("   - Reference relevant contextual memories from previous interactions when applicable")
        lines.append("   - Determine the best next action (use tools or delegate to agents)")
        lines.append("   - Explain your decision logic and expected results")
        lines.append("")
        lines.append("2. Code:")
        lines.append("   - Write code in simple Python")
        lines.append("   - Follow Python coding standards and Python syntax")
        lines.append("   - Correctly call tools or agents to solve problems")
        lines.append("   - To distinguish between code execution and displaying user code, use '<code>code</code>' for executing code and '<DISPLAY:language_type>code</DISPLAY>' for displaying code")
        lines.append("   - Note that executed code is not visible to users. If users need to see the code, use '<DISPLAY:language_type>code</DISPLAY>' for displaying code.")
        lines.append("   - **IMPORTANT**: After code execution, the system will return content with \"Observation:\" marker (this is the real execution result). Please continue your next thinking based on these real results. **Do NOT fabricate observation results before code execution.**")
        lines.append("")
        lines.append("After thinking, when you believe you can answer the user's question, you can generate a final answer directly to the user without generating code and stop the loop.")
        lines.append("")
        lines.append("When generating the final answer, you need to follow these specifications:")
        lines.append("1. **Markdown Format Requirements**:")
        lines.append("   - Use standard Markdown syntax to format your output, supporting headings, lists, tables, code blocks, and links.")
        lines.append("   - Display images and videos using links instead of wrapping them in code blocks. Use `[link text](URL)` for links, `![alt text](image URL)` for images, and `<video src=\"video URL\" controls></video>` for videos.")
        lines.append("   - Use a single blank line between paragraphs, avoid multiple consecutive blank lines")
        lines.append("   - Mathematical formulas use standard Markdown format: inline formulas use $formula$, block formulas use $$formula$$")
        lines.append("")
        lines.append("2. **Reference Mark Specifications** (only when retrieval tools are used):")
        lines.append("   - Reference mark format must strictly be: `[[letter+number]]`, for example: `[[a1]]`, `[[b2]]`, `[[c3]]`")
        lines.append("   - The letter part must be a single lowercase letter (a-e), the number part must be an integer")
        lines.append("   - The letters and numbers of reference marks must correspond one-to-one with the retrieval results of retrieval tools")
        lines.append("   - Reference marks should be placed immediately after relevant information or sentences, usually at the end of sentences or paragraphs")
        lines.append("   - Multiple reference marks can be used consecutively, for example: `[[a1]][[b2]]`")
        lines.append("   - **Important**: Only add reference marks, do not add links, reference lists, or other extraneous content")
        lines.append("   - If there is no matching reference in the retrieval results, do not display that reference mark")
        lines.append("")
        lines.append("3. **Format Detail Requirements**:")
        lines.append("   - Avoid using HTML tags in Markdown, prioritize native Markdown syntax")
        lines.append("   - Code in code blocks should maintain original format, do not add extra escape characters")
        lines.append("   - If no retrieval tools are used, do not add any reference marks")

    content = "\n".join(lines)

    return SystemPromptComponent(
        content=content,
        template_name="execution_flow",
        priority=priority,
    )


def build_skeleton_constraint_component(
    constraint: str,
    language: str = "zh",
    priority: int = 30,
) -> "SystemPromptComponent":
    """Build SystemPromptComponent for the constraint section.

    Section: "### 资源使用要求" / "### Resource Usage Requirements"
    Content: User-defined constraint text
    """
    from nexent.core.agents.agent_model import SystemPromptComponent

    if language == "zh":
        content = f"### 资源使用要求\n{constraint}"
    else:
        content = f"### Resource Usage Requirements\n{constraint}"

    return SystemPromptComponent(
        content=content,
        template_name="constraint",
        priority=priority,
    )


def build_skeleton_code_norms_component(
    language: str = "zh",
    is_manager: bool = True,
    priority: int = 20,
) -> "SystemPromptComponent":
    """Build SystemPromptComponent for the Python code norms section.

    Section: "### python代码规范" / "### Python Code Specifications"
    Content: 12 fixed code rules (11 for managed agents)
    """
    from nexent.core.agents.agent_model import SystemPromptComponent

    if language == "zh":
        lines = ["### python代码规范"]
        lines.append("1. 如果认为是需要执行的代码，使用'<code>代码</code>'格式；如果是不需要执行仅用于展示的代码，使用'<DISPLAY:语言类型>代码</DISPLAY>'格式，其中语言类型例如python、java、javascript等；")
        lines.append("2. 只使用已定义的变量，变量将在多次调用之间持续保持；")
        lines.append("3. 使用\"print()\"函数让下一次的模型调用看到对应变量信息；")
        lines.append("4. 正确使用工具/助手的入参，使用关键字参数，不要用字典形式；")
        lines.append("5. 避免在一轮对话中进行过多的工具/助手调用，这会导致输出格式难以预测；")
        lines.append("6. 只在需要时调用工具/助手，不重复相同参数的调用；")
        lines.append("7. 使用变量名保存函数调用结果，在每个中间步骤中，您可以使用\"print()\"来保存您需要的任何重要信息。被保存的信息在代码执行之间保持。print()输出的内容应被视为字符串，不要对其进行字典相关操作如.get()、[]等，避免类型错误；")
        lines.append("9. 示例中的代码避免出现**if**、**for**等逻辑，仅调用工具/助手，示例中的每一次的行动都是确定事件。如果有不同的条件，你应该给出不同条件下的示例；")
        lines.append("10. 工具调用使用关键字参数，如：tool_name(param1=\"value1\", param2=\"value2\")；")
        if is_manager:
            lines.append("11. 助手调用必须使用task参数，如：assistant_name(task=\"任务描述\")；")
        lines.append("12. 不要放弃！你负责解决任务，而不是提供解决方向。")
    else:
        lines = ["### Python Code Specifications"]
        lines.append("1. If it is considered to be code that needs to be executed, use '<code>code</code>'. If the code does not need to be executed for display only, use '<DISPLAY:language_type>code</DISPLAY>', where language_type can be python, java, javascript, etc;")
        lines.append("2. Only use defined variables, variables will persist between multiple calls;")
        lines.append("3. Use \"print()\" function to let the next model call see corresponding variable information;")
        lines.append("4. Use tool/agent input parameters correctly, use keyword arguments, not dictionary format;")
        lines.append("5. Avoid making too many tool/agent calls in one round of conversation, as this will make the output format unpredictable;")
        lines.append("6. Only call tools/agents when needed, do not repeat calls with the same parameters;")
        lines.append("7. Use variable names to save function call results. In each intermediate step, you can use \"print()\" to save any important information you need. The saved information persists between code executions. The content printed by print() should be treated as a string, do not perform dictionary-related operations such as .get(), [] etc., to avoid type errors;")
        lines.append("8. Avoid **if**, **for** and other logic in example code, only call tools/agents. Each action in the example is a deterministic event. If there are different conditions, you should provide examples under different conditions;")
        lines.append("9. Tool calls use keyword arguments, such as: tool_name(param1=\"value1\", param2=\"value2\");")
        if is_manager:
            lines.append("10. Agent calls must use task parameter, such as: agent_name(task=\"task description\");")
        lines.append("11. Don't give up! You are responsible for solving the task, not providing solution directions.")

    content = "\n".join(lines)

    return SystemPromptComponent(
        content=content,
        template_name="code_norms",
        priority=priority,
    )


def build_skeleton_footer_component(
    few_shots: str,
    language: str = "zh",
    priority: int = 10,
) -> "SystemPromptComponent":
    """Build SystemPromptComponent for the footer section.

    Section: "### 示例模板" + ending
    Content: few_shots + "$1M reward" ending
    """
    from nexent.core.agents.agent_model import SystemPromptComponent

    if language == "zh":
        content = f"### 示例模板\n{few_shots}\n\n现在开始！如果你正确解决任务，你将获得100万美元的奖励。"
    else:
        content = f"### Example Templates\n{few_shots}\n\nNow start! If you solve the task correctly, you will receive a reward of 1 million dollars."

    return SystemPromptComponent(
        content=content,
        template_name="footer",
        priority=priority,
    )


# =============================================================================
# SECTION 3: Piecewise component builders (existing, enhanced)
# =============================================================================


def build_tools_component(
    tools: Dict[str, Any],
    knowledge_base_summary: Optional[str] = None,
    language: str = "zh",
    is_manager: bool = True,
    priority: int = 50,
) -> "ToolsComponent":
    """Build ToolsComponent from tool configurations.

    Args:
        tools: Dict of tool name -> ToolConfig or tool dict
        knowledge_base_summary: Summary text from knowledge bases
        language: Language code ('zh' or 'en')
        is_manager: Whether this is a manager agent
        priority: Component priority for selection

    Returns:
        ToolsComponent instance
    """
    from nexent.core.agents.agent_model import ToolsComponent

    tool_list = []
    for name, tool in tools.items():
        if hasattr(tool, 'description'):
            tool_dict = {
                "name": name,
                "description": tool.description,
                "inputs": getattr(tool, 'inputs', ''),
                "output_type": getattr(tool, 'output_type', ''),
                "source": getattr(tool, 'source', 'local'),
            }
        else:
            tool_dict = {
                "name": name,
                "description": tool.get('description', ''),
                "inputs": tool.get('inputs', ''),
                "output_type": tool.get('output_type', ''),
                "source": tool.get('source', 'local'),
            }
        tool_list.append(tool_dict)

    formatted_desc = _format_tools_description(
        tools,
        knowledge_base_summary=knowledge_base_summary,
        language=language,
        is_manager=is_manager,
    )
    return ToolsComponent(
        tools=tool_list,
        formatted_description=formatted_desc,
        priority=priority,
    )


def build_skills_component(
    skills: List[Dict[str, str]],
    language: str = "zh",
    priority: int = 70,
) -> "SkillsComponent":
    """Build SkillsComponent from skill configurations.

    Args:
        skills: List of skill dicts with name and description
        language: Language code ('zh' or 'en')
        priority: Component priority for selection

    Returns:
        SkillsComponent instance
    """
    from nexent.core.agents.agent_model import SkillsComponent

    formatted_desc = _format_skills_description(skills, language=language)
    return SkillsComponent(
        skills=skills,
        formatted_description=formatted_desc,
        priority=priority,
    )


def build_memory_component(
    memory_list: List[Any],
    search_query: Optional[str] = None,
    language: str = "zh",
    priority: int = 90,
) -> "MemoryComponent":
    """Build MemoryComponent from memory search results.

    Args:
        memory_list: List of memory search results
        search_query: Query used to search memory
        language: Language code ('zh' or 'en')
        priority: Component priority for selection

    Returns:
        MemoryComponent instance
    """
    from nexent.core.agents.agent_model import MemoryComponent

    memories = []
    for mem in memory_list:
        if isinstance(mem, dict):
            memories.append({
                "content": mem.get('memory', '') or mem.get('content', ''),
                "memory_type": mem.get('memory_type', 'user'),
                "metadata": mem.get('metadata', {}),
            })
        elif isinstance(mem, str):
            memories.append({
                "content": mem,
                "memory_type": "user",
                "metadata": {},
            })

    formatted_content = _format_memory_context(memory_list, language=language)
    return MemoryComponent(
        memories=memories,
        formatted_content=formatted_content,
        search_query=search_query,
        priority=priority,
    )


def build_knowledge_base_component(
    knowledge_base_summary: str,
    kb_ids: Optional[List[str]] = None,
    priority: int = 10,
) -> "KnowledgeBaseComponent":
    """Build KnowledgeBaseComponent from knowledge base summary.

    Args:
        knowledge_base_summary: Summary text from knowledge bases
        kb_ids: List of knowledge base IDs used
        priority: Component priority for selection

    Returns:
        KnowledgeBaseComponent instance
    """
    from nexent.core.agents.agent_model import KnowledgeBaseComponent

    return KnowledgeBaseComponent(
        summary=knowledge_base_summary,
        kb_ids=kb_ids or [],
        priority=priority,
    )


def build_managed_agents_component(
    managed_agents: Dict[str, Any],
    language: str = "zh",
    priority: int = 45,
) -> "ManagedAgentsComponent":
    """Build ManagedAgentsComponent from managed sub-agent configurations.

    Args:
        managed_agents: Dict of agent name -> AgentConfig
        language: Language code ('zh' or 'en')
        priority: Component priority for selection

    Returns:
        ManagedAgentsComponent instance
    """
    from nexent.core.agents.agent_model import ManagedAgentsComponent

    agent_list = []
    for name, agent in managed_agents.items():
        if hasattr(agent, 'description'):
            agent_dict = {
                "name": name,
                "description": agent.description,
                "tools": [],
            }
            if hasattr(agent, 'tools'):
                agent_dict["tools"] = [t.name for t in agent.tools if hasattr(t, 'name')]
        else:
            agent_dict = {
                "name": name,
                "description": agent.get('description', ''),
                "tools": [],
            }
        agent_list.append(agent_dict)

    formatted_desc = _format_managed_agents_description(managed_agents, language=language)
    return ManagedAgentsComponent(
        agents=agent_list,
        formatted_description=formatted_desc,
        priority=priority,
    )


def build_external_agents_component(
    external_a2a_agents: Dict[str, Any],
    language: str = "zh",
    priority: int = 44,
) -> "ExternalAgentsComponent":
    """Build ExternalAgentsComponent from external A2A agent configurations.

    Args:
        external_a2a_agents: Dict of agent_id -> ExternalA2AAgentConfig
        language: Language code ('zh' or 'en')
        priority: Component priority for selection

    Returns:
        ExternalAgentsComponent instance
    """
    from nexent.core.agents.agent_model import ExternalAgentsComponent

    agent_list = []
    for agent_id, agent in external_a2a_agents.items():
        if hasattr(agent, 'agent_id'):
            agent_dict = {
                "agent_id": str(agent.agent_id),
                "name": agent.name,
                "description": agent.description,
                "url": getattr(agent, 'url', ''),
            }
        else:
            agent_dict = {
                "agent_id": str(agent_id),
                "name": agent.get('name', ''),
                "description": agent.get('description', ''),
                "url": agent.get('url', ''),
            }
        agent_list.append(agent_dict)

    formatted_desc = _format_external_agents_description(external_a2a_agents, language=language)
    return ExternalAgentsComponent(
        agents=agent_list,
        formatted_description=formatted_desc,
        priority=priority,
    )


def build_system_prompt_component(
    content: str,
    template_name: Optional[str] = None,
    priority: int = 100,
) -> "SystemPromptComponent":
    """Build SystemPromptComponent with rendered content.

    Args:
        content: Rendered system prompt content
        template_name: Source template name for reference
        priority: Component priority (highest by default)

    Returns:
        SystemPromptComponent instance
    """
    from nexent.core.agents.agent_model import SystemPromptComponent

    return SystemPromptComponent(
        content=content,
        template_name=template_name,
        priority=priority,
    )


def build_skills_usage_component(
    skills: List[Dict[str, str]],
    language: str = "zh",
    priority: int = 40,
) -> "SystemPromptComponent":
    """Build SystemPromptComponent for skills usage requirements.

    This is a skeleton-like component but its content depends on
    whether skills exist, so it's built dynamically.

    Args:
        skills: List of skill dicts
        language: Language code ('zh' or 'en')
        priority: Component priority

    Returns:
        SystemPromptComponent instance
    """
    from nexent.core.agents.agent_model import SystemPromptComponent

    content = _format_skills_usage_requirements(skills, language=language)
    return SystemPromptComponent(
        content=content,
        template_name="skills_usage",
        priority=priority,
    )


def build_agent_fallback_component(
    managed_agents: Dict[str, Any],
    external_a2a_agents: Dict[str, Any],
    language: str = "zh",
    priority: int = 5,
) -> "SystemPromptComponent":
    """Build SystemPromptComponent for agent fallback message.

    Only emits content when no agents are available.

    Args:
        managed_agents: Dict of managed agents
        external_a2a_agents: Dict of external agents
        language: Language code
        priority: Component priority

    Returns:
        SystemPromptComponent instance (may have empty content)
    """
    from nexent.core.agents.agent_model import SystemPromptComponent

    content = _format_agent_fallback(managed_agents, external_a2a_agents, language=language)
    return SystemPromptComponent(
        content=content,
        template_name="agent_fallback",
        priority=priority,
    )


# =============================================================================
# SECTION 4: Main assembly function - build_context_components
# =============================================================================


def build_context_components(
    # Raw params for piecewise assembly (NEW in Goal 3)
    duty: Optional[str] = None,
    constraint: Optional[str] = None,
    few_shots: Optional[str] = None,
    app_name: Optional[str] = None,
    app_description: Optional[str] = None,
    time_str: Optional[str] = None,
    user_id: Optional[str] = None,
    language: str = "zh",
    is_manager: bool = True,
    # Piecewise data sources
    tools: Optional[Dict[str, Any]] = None,
    skills: Optional[List[Dict[str, str]]] = None,
    managed_agents: Optional[Dict[str, Any]] = None,
    external_a2a_agents: Optional[Dict[str, Any]] = None,
    memory_list: Optional[List[Any]] = None,
    memory_search_query: Optional[str] = None,
    knowledge_base_summary: Optional[str] = None,
    kb_ids: Optional[List[str]] = None,
    # Legacy param for fallback (removed short-circuit in Goal 3)
    system_prompt: Optional[str] = None,
    # Inclusion flags (kept for backward compatibility)
    include_tools: bool = True,
    include_skills: bool = True,
    include_memory: bool = True,
    include_knowledge_base: bool = True,
    include_managed_agents: bool = True,
    include_external_agents: bool = True,
    include_app_context: bool = True,
) -> List["ContextComponent"]:
    """Build list of ContextComponents from agent configuration data.

    Piecewise assembly: Each semantic section is emitted as a dedicated
    ContextComponent, assembled in the exact order matching Jinja2 templates.

    Assembly order (12 sections):
      1. Header (基本信息)
      2. Memory (上下文记忆) - if memory_list exists
      3. Duty (核心职责 + 安全准则)
      4. Skills (可用技能 + 6步流程) - if skills exist
      5. Execution Flow (执行流程 + 输出规范)
      6. Tools (可用资源/1. 工具 + 文件链接指南)
      7. Managed Agents (可用资源/2. 助手) - if managed_agents exist
      8. External Agents (外部助手) - if external_a2a_agents exist
      9. Agent Fallback (当前没有可用的助手) - if no agents
     10. Skills Usage (可用资源/3. 技能 + 使用要求)
     11. Constraint (资源使用要求)
     12. Code Norms (python代码规范)
     13. Footer (示例模板 + 结尾)

    Note: The a330d815 short-circuit (if system_prompt: return [single])
    has been REMOVED. All callers must provide raw params for piecewise assembly.
    The system_prompt param is kept for future fallback use but not currently
    used in the piecewise path.

    Args:
        duty: Agent's primary duty text
        constraint: Resource usage constraint text
        few_shots: Example templates text
        app_name: Application name
        app_description: Application description
        time_str: Current time string
        user_id: Current user ID
        language: Language code ('zh' or 'en')
        is_manager: Whether this is a manager agent
        tools: Dict of tool name -> ToolConfig
        skills: List of skill dicts with name and description
        managed_agents: Dict of agent name -> AgentConfig
        external_a2a_agents: Dict of agent_id -> ExternalA2AAgentConfig
        memory_list: List of memory search results
        memory_search_query: Query used to search memory
        knowledge_base_summary: Summary text from knowledge bases
        kb_ids: List of knowledge base IDs
        system_prompt: (Legacy) Pre-rendered system prompt - NOT USED in piecewise path
        include_*: Flags for backward compatibility

    Returns:
        List of ContextComponent instances ready for ContextManager
    """
    components: List = []

    # 1. Header
    if app_name and app_description and time_str and user_id:
        components.append(
            build_skeleton_header_component(
                app_name=app_name,
                app_description=app_description,
                time_str=time_str,
                user_id=user_id,
                language=language,
            )
        )

    # 2. Memory (if exists)
    if include_memory and memory_list:
        components.append(
            build_memory_component(
                memory_list=memory_list,
                search_query=memory_search_query,
                language=language,
            )
        )

    # 3. Duty + Safety Principles
    if duty:
        components.append(
            build_skeleton_duty_component(
                duty=duty,
                language=language,
            )
        )

    # 4. Skills (if exists) - includes 6-step process
    if include_skills and skills:
        components.append(
            build_skills_component(
                skills=skills,
                language=language,
            )
        )

    # 5. Execution Flow
    components.append(
        build_skeleton_execution_flow_component(
            memory_list=memory_list,
            language=language,
            is_manager=is_manager,
        )
    )

    # 6. Tools + File URL Guide
    if include_tools and tools:
        components.append(
            build_tools_component(
                tools=tools,
                knowledge_base_summary=knowledge_base_summary,
                language=language,
                is_manager=is_manager,
            )
        )

    # 7. Managed Agents (if exists) - manager only
    if is_manager and include_managed_agents and managed_agents:
        components.append(
            build_managed_agents_component(
                managed_agents=managed_agents,
                language=language,
            )
        )

    # 8. External Agents (if exists) - manager only
    if is_manager and include_external_agents and external_a2a_agents:
        components.append(
            build_external_agents_component(
                external_a2a_agents=external_a2a_agents,
                language=language,
            )
        )

    # 9. Agent Fallback (if no agents available) - manager only
    if is_manager and not managed_agents and not external_a2a_agents:
        fallback_comp = build_agent_fallback_component(
            managed_agents=managed_agents or {},
            external_a2a_agents=external_a2a_agents or {},
            language=language,
        )
        if fallback_comp.content:  # Only add if has content
            components.append(fallback_comp)

    # 10. Skills Usage Requirements
    if include_skills:
        components.append(
            build_skills_usage_component(
                skills=skills or [],
                language=language,
            )
        )

    # 11. Constraint
    if constraint:
        components.append(
            build_skeleton_constraint_component(
                constraint=constraint,
                language=language,
            )
        )

    # 12. Code Norms
    components.append(
        build_skeleton_code_norms_component(
            language=language,
            is_manager=is_manager,
        )
    )

    # 13. Footer
    if few_shots:
        components.append(
            build_skeleton_footer_component(
                few_shots=few_shots,
                language=language,
            )
        )

    return components


def build_app_context_string(
    app_name: str,
    app_description: str,
    user_id: str,
) -> str:
    """Build app context string for template injection.

    Args:
        app_name: Application name
        app_description: Application description
        user_id: Current user ID

    Returns:
        Formatted app context string
    """
    time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return _format_app_context(app_name, app_description, user_id, time_str)