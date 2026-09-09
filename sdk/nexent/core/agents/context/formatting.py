"""Deterministic formatting for structured context item groups.

These pure functions are owned by the SDK because final model-message
rendering is an SDK responsibility. Callers provide authorized data only.
"""

from typing import Any, Dict, List


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

    # Group memories by the supported hierarchy: tenant, user, agent.
    level_order = ["tenant", "user", "agent"]
    memory_by_level: Dict[str, List[Any]] = {}
    for mem in memory_list:
        if isinstance(mem, dict):
            level = mem.get("memory_level", "user")
            if level not in level_order:
                continue
            memory_by_level.setdefault(level, []).append(mem)

    if not memory_by_level:
        return ""

    lines = []

    if language == "zh":
        lines.append("### 上下文记忆")
        lines.append("基于之前的交互记录，以下是按作用域和重要程度排序的最相关记忆：")
        lines.append("")

        for level in level_order:
            if level in memory_by_level:
                level_title = {
                    "tenant": "Tenant",
                    "user": "User",
                    "agent": "Agent",
                }.get(level, level.title())
                lines.append(f"**{level_title} 层级记忆：**")
                for item in memory_by_level[level]:
                    content = item.get("memory", "") or item.get("content", "")
                    if item.get("version_id") is not None or item.get("memory_type") == "long_term":
                        lines.append(content)
                    else:
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
                    if item.get("version_id") is not None or item.get("memory_type") == "long_term":
                        lines.append(content)
                    else:
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
        lines.append("4. **执行技能脚本**：技能中引用的脚本（参考文档、脚本声明）可通过以下任一形式表达，**功能上完全等同**，模型必须把它们都识别为路径声明：")
        lines.append("   - XML 标签形式：`<use_script path=\"script_path\" />`、`<reference path=\"file_path\" />`")
        lines.append("   - 单个反引号包裹：`` `scripts/analyze.py` ``、`` `reference/api_doc` ``")
        lines.append("   - 三重反引号代码块：`` ```scripts/analyze.py``` ``（当代码块内仅有单行路径时）")
        lines.append("   调用 `run_skill_script` 时，默认的 `source=\"skill\"` 会相对技能根目录解析 `script_path`，常见形式如下：")
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
        lines.append("   如果技能要求先在当前运行工作区生成 `.py`、`.js` 或 `.mjs` 脚本，再执行该脚本，请显式使用 `source=\"workspace\"`：")
        lines.append("   <code>")
        lines.append("   result = run_skill_script(\"skill_name\", \"outputs/generated.js\", source=\"workspace\")")
        lines.append("   </code>")
        lines.append("   注意：")
        lines.append("   - 每个执行轮次最多输出一个 `<code>...</code>`；需要多个工具调用时，将它们放在同一个代码块中，并等待执行结果后再继续下一轮。")
        lines.append("   - 如果提示缺少 Python 包且沙箱已启用公网，可使用 `%pip install --user 包名`，也可沿用 `subprocess.run([sys.executable, \"-m\", \"pip\", \"install\", \"包名\"], check=True)`；`subprocess` 仅允许这种不经过 Shell 的 pip install argv 调用，禁止 `shell=True` 和其他系统命令。安装成功后下一轮重试。Node 依赖可通过技能自带的 npm/pnpm 脚本安装。不要安装与任务无关的包。")
        lines.append("   - `source=\"skill\"` 的路径相对于技能根目录；`source=\"workspace\"` 的路径相对于当前运行工作区。两种模式都拒绝绝对路径和路径穿越。")
        lines.append("   - 脚本的执行目录（CWD）始终是当前运行的 `outputs` 目录；生成产物时使用裸文件名，例如 `report.pptx`，不要写成 `outputs/report.pptx`。")
        lines.append("   - 使用 `skill-creator` 创建待校验、待打包的新技能时，必须用代码执行器的文件 API 在当前 `outputs/<new-skill>` 中创建文件，再把相对目录传给校验/打包脚本。`write_skill_file` 用于修改租户已安装技能，不会把文件写入本次运行的 outputs。")
        lines.append("   - 如果 `run_skill_script` 报告执行失败，必须先修复脚本并重新调用成功，禁止继续验证、上传或声称产物已经生成。禁止改用 `subprocess`、`os.system` 或直接 Shell 绕过。")
        lines.append("   - 当脚本不存在时，返回的错误信息中会列出该技能根目录下的可用脚本，请据此修正路径。")
        lines.append("")
        lines.append("5. **整合输出**：根据技能指南要求的输出格式，结合脚本执行结果生成最终回答。")
        lines.append("")
        lines.append("6. **引用场景处理**：技能中的引用既可以通过 XML 标签表达，也可以通过下列 Markdown 语法表达，**功能上完全等同**，必须都能识别：")
        lines.append("   - **引用模板识别**：")
        lines.append("     - XML 形式：`<reference path=\"file_path\" />`")
        lines.append("     - 单个反引号形式：`` `examples.md` ``、`` `reference/api_doc` ``")
        lines.append("     - 三重反引号代码块形式：`` ```examples.md``` ``（当代码块内仅有单行路径时）")
        lines.append("     - 自然语言式的引用声明（如\"详见 examples.md\"、\"请参考 reference/api_doc\"）")
        lines.append("   - **自动补全**：发现引用后，按需调用 `read_skill_md(\"skill_name\", [\"<路径>\"])` 读取被引用的文件，**不要一次性全部读取**，应基于当前任务判断哪些文件确实必要。")
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
        lines.append("4. **Execute Skill Script**: Skill-internal references (for both documentation and scripts) may be declared with **any of the following equivalent forms** - treat them all the same way: ")
        lines.append("   - XML tags: `<use_script path=\"script_path\" />`, `<reference path=\"file_path\" />`")
        lines.append("   - Single inline backticks: `` `scripts/analyze.py` ``, `` `reference/api_doc` ``")
        lines.append("   - Triple-backtick fenced code blocks: `` ```scripts/analyze.py``` `` (only when the block body is a single path line)")
        lines.append("   When calling `run_skill_script`, the `script_path` is **always resolved relative to the skill's root directory** (this is the platform behaviour, not the agent's CWD). Common forms:")
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
        lines.append("   If the skill requires generating a `.py`, `.js`, or `.mjs` script in the current run workspace before executing it, explicitly use `source=\"workspace\"`:")
        lines.append("   <code>")
        lines.append("   result = run_skill_script(\"skill_name\", \"outputs/generated.js\", source=\"workspace\")")
        lines.append("   </code>")
        lines.append("   Notes: Output at most one executable `<code>...</code>` block per step. Put multiple tool calls inside that one block when needed, then wait for its result before continuing. If a Python package is missing and sandbox network access is enabled, use either `%pip install --user <package>` or `subprocess.run([sys.executable, \"-m\", \"pip\", \"install\", \"<package>\"], check=True)`, then retry on the next step. `subprocess` is allowed only for this shell-free pip-install argv form; never set `shell=True` or run unrelated system commands. Install Node dependencies through the skill's bundled npm/pnpm script. Do not install unrelated packages. `source=\"skill\"` paths are relative to the skill root; `source=\"workspace\"` paths are relative to the current run workspace. Both reject absolute paths and traversal. Scripts always execute with the current run's `outputs` directory as CWD, so create artifacts with a bare filename such as `report.pptx`, not `outputs/report.pptx`. When using `skill-creator`, create the new skill under `outputs/<new-skill>` with the code executor's file APIs and pass that relative directory to its validation and packaging scripts; `write_skill_file` edits an installed tenant skill and does not create output files. If `run_skill_script` reports failure, repair and rerun it successfully before validation or upload; do not bypass a failed skill script with unrelated commands. When a bundled skill script cannot be found, use the returned list of available scripts to correct the path.")
        lines.append("")
        lines.append("5. **Integrate Output**: Generate the final answer based on the skill guide's output format and script execution results.")
        lines.append("")
        lines.append("6. **Handle References**: Skill-internal references can be expressed using XML tags, markdown forms, or natural-language hints. All three are **functionally equivalent** and must be recognised: ")
        lines.append("   - **Reference patterns to recognise**:")
        lines.append("     - XML tag form: `<reference path=\"file_path\" />`")
        lines.append("     - Single inline backtick form: `` `examples.md` ``, `` `reference/api_doc` ``")
        lines.append("     - Triple-backtick fenced block form: `` ```examples.md``` `` (only when the block body is a single path line)")
        lines.append("     - Natural-language references (\"see examples.md\", \"refer to reference/api_doc\")")
        lines.append("   - **Auto-complete**: After discovering a reference, call `read_skill_md(\"skill_name\", [\"<path>\"])` only for the files you actually need. Do **not** load every referenced file blindly - decide based on the current task which references matter.")
        lines.append("   - **Example**:")
        lines.append("   <code>")
        lines.append("   # Skill content says \"see examples.md for detailed examples\"")
        lines.append("   additional_info = read_skill_md(\"skill_name\", [\"examples.md\"])")
        lines.append("   print(additional_info)")
        lines.append("   </code>")

    return "\n".join(lines)


def _format_tools_description(
    tools: Dict[str, Any],
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
        prefix = "1. 工具\n" if language == "zh" else "1. Tools\n"
        return prefix + no_tools_msg

    lines = []

    if language == "zh":
        lines.append("1. 工具")
    else:
        lines.append("1. Tools")

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
        lines.append("2. 助手")
    else:
        lines.append("2. Agents")

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
        lines.append("     - 并行优化：如果你有多个互不依赖的子任务，可以在单步内发出多个助手调用，系统将并行执行以节省时间。判断标准：子任务不需要对方的输出作为输入即可并行。示例：同时检查代码风格、安全性和逻辑 → 一步内调用3个助手。反例：先搜索信息，再基于结果写报告 → 必须串行。")
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
        lines.append("      - Parallel optimization (important): If you have multiple independent subtasks, you can issue multiple agent calls in a single step -- the system will execute them in parallel to save time. Criterion: if subtasks do not need each other's output as input, they are parallelizable. Example: checking code style, security, and logic simultaneously → call 3 agents in one step. Counter-example: first search for information, then write a report based on results → must be serial.")
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
    is_manager: bool = True,
) -> str:
    """Format skills usage requirements section.

    This is the "技能使用要求" section that appears after the skills reference
    in the Available Resources section.
    """
    if not skills:
        no_skills_msg = "- 当前没有可用的技能" if language == "zh" else "- No skills are currently available"
        prefix = "3. 技能\n" if language == "zh" else "3. Skills\n"
        return prefix + no_skills_msg

    lines = []

    if language == "zh":
        lines.append("3. 技能")
    else:
        lines.append("3. Skills")

    if language == "zh":
        lines.append("- 你拥有上述 `<available_skills>` 中列出的技能。技能中引用的脚本通过 `run_skill_script()` 函数调用，该函数由平台提供，不需要导入。")
        lines.append("")
        lines.append("### 技能使用要求")
        lines.append("1. **技能优先**：如果用户请求匹配了某个技能的 description，必须先调用 `read_skill_md()` 加载技能指南，再按指南执行。不得跳过技能自行编写代码解决。")
        lines.append("2. **忠实执行**：读取技能内容后，严格按技能指南中的步骤操作。不要自行修改流程、跳过步骤或用通用代码替代技能定义的流程。")
        lines.append("3. **脚本调用规范**：")
        lines.append("   - 路径声明识别：技能指南中的脚本路径既可以以 XML 标签（`<use_script path=\"...\" />`）声明，也允许以等价的 Markdown 形式（`` `scripts/foo.py` `` 单反引号，或 `` ```scripts/foo.py``` `` 三重反引号代码块）声明。模型必须把这些形式都识别为脚本路径。")
        lines.append("   - 路径解析：默认 `source=\"skill\"` 时，`script_path` 相对于技能根目录；`source=\"workspace\"` 时，路径相对于当前运行工作区。两种模式都拒绝绝对路径和路径穿越。")
        lines.append("   - 参数传递：如果需要附加参数，将参数以命令行字符串形式传递给 `run_skill_script`。")
        lines.append("   - 工作区脚本：仅当技能要求执行本次运行生成的 `.py`/`.js`/`.mjs` 文件时，使用 `source=\"workspace\"`；技能自带脚本保持默认 `source=\"skill\"`。")
        lines.append("   - 错误处理：`run_skill_script` 失败后必须先修复并重新运行；成功前不得校验、上传产物，也不得改用 `subprocess`、`os.system` 或 Shell 绕过。")
        lines.append("4. **失败回退**：如果 `read_skill_md` 返回错误，向用户说明情况；如果 `run_skill_script` 执行失败，依据错误信息修复脚本并重新运行。")
        lines.append("5. **技能组合**：如果一个任务需要多个技能配合，按逻辑依赖顺序依次加载和执行，前一个技能的输出可作为后一个技能的输入。")
    else:
        lines.append("- You have the skills listed in `<available_skills>` above. Scripts referenced in skills are called via the `run_skill_script()` function, which is provided by the platform and does not need to be imported.")
        lines.append("")
        lines.append("### Skill Usage Requirements")
        lines.append("1. **Skill Priority**: If a user request matches a skill's description, you must first call `read_skill_md()` to load the skill guide, then execute per the guide. Do not skip skills and write your own code.")
        lines.append("2. **Faithful Execution**: After reading skill content, strictly follow the skill guide's steps. Do not modify the flow, skip steps, or replace with generic code.")
        lines.append("3. **Script Calling Specification**:")
        lines.append("   - **Path declaration recognition**: A script path inside the skill guide may be declared using XML tags (`<use_script path=\"...\" />`) OR via the equivalent markdown forms - single inline backticks like `` `scripts/foo.py` ``, or triple-backtick fenced blocks like `` ```scripts/foo.py``` ``. Treat all three as the same kind of declaration.")
        lines.append("   - **Path resolution**: With the default `source=\"skill\"`, `script_path` is relative to the skill root. With `source=\"workspace\"`, it is relative to the current run workspace. Both modes reject absolute paths and traversal.")
        lines.append("   - **Parameter passing**: For extra parameters, pass them as a command-line string to `run_skill_script`.")
        lines.append("   - **Workspace scripts**: Use `source=\"workspace\"` only when the skill requires executing a `.py`/`.js`/`.mjs` file generated during this run. Keep the default `source=\"skill\"` for bundled scripts.")
        lines.append("   - **Error handling**: If `run_skill_script` fails, repair and rerun it before validating or uploading artifacts. Never bypass it with `subprocess`, `os.system`, or a shell.")
        lines.append("4. **Failure Fallback**: If `read_skill_md` returns an error, explain the problem. If `run_skill_script` fails, use its error details to repair the script and rerun it.")
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
