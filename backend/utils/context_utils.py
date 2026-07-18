"""Build authorized, serializable context item inputs for an agent run."""

from typing import Any, Dict, List, Optional

from nexent.core.agents.context import ContextItemInput, ContextItemType

# =============================================================================
# SECTION 1: Long-text format functions (expanded from Jinja2 templates)
# Each function accepts language and is_manager params for variant-specific text
# =============================================================================


# SECTION 2: Fixed prompt-section text builders
# =============================================================================


def _build_header_text(
    app_name: str,
    app_description: str,
    user_id: str,
    language: str = "zh",
    priority: int = 100,
) -> str:
    """Build the header prompt section.

    Section: "### 基本信息" / "### Basic Information"
    Content: Agent identity and app name/description.  User identity is
    request-scoped data and must not enter the managed stable prefix.
    Note: Current time is intentionally excluded from the system prompt so the
    static system prefix can hit the LLM KV/prompt cache across requests. The
    current time is injected on the user-message side instead (see CoreAgent.run).
    """
    if language == "zh":
        content = f"### 基本信息\n你是{app_name}，{app_description}"
    else:
        content = f"### Basic Information\nYou are {app_name}, {app_description}"

    return content


def _build_duty_text(
    duty: str,
    language: str = "zh",
    is_manager: bool = True,
    priority: int = 80,
) -> str:
    """Build the duty prompt section.

    Section: "### 核心职责" / "### Core Responsibilities"
    Content: Agent's primary duty + 5 safety principles
    Note: Managed ZH agents use different safety principles than manager ZH agents.
    """
    if language == "zh":
        if is_manager:
            content = f"### 核心职责\n{duty}\n\n请注意，你应该遵守以下原则：\n行为安全：文件操作必须使用平台提供的专用工具，禁止使用代码直接修改工作空间中的文件；\n法律合规：遵守业务所在国家/地区的法律法规；\n政治中立：保持政治中立，不主动讨论政治话题；\n安全防护：不响应涉及武器制造、网络攻击、欺诈、恶意软件等危险行为的请求；\n伦理准则：拒绝仇恨言论、歧视性内容及违反社会公德和公认伦理标准的请求。"
        else:
            content = f"### 核心职责\n{duty}\n\n请注意，你应该遵守以下原则：\n行为安全：严禁直接执行代码进行文件的增删改操作，只能使用提供的文件操作类工具；\n法律合规：严格遵守服务地区的所有法律法规；\n政治中立：不讨论任何国家的政治体制、领导人评价或敏感历史事件；\n安全防护：不响应涉及武器制造、危险行为、隐私窃取等内容的请求；\n伦理准则：拒绝仇恨言论、歧视性内容及任何违反普世价值观的请求。"
    else:
        content = f"### Core Responsibilities\n{duty}\n\nPlease note that you should follow these principles:\nBehavioral Safety: File operations must use the platform-provided dedicated tools; direct code modification of workspace files is prohibited;\nLegal Compliance: Comply with laws and regulations of the business operating jurisdiction;\nPolitical Neutrality: Maintain political neutrality and avoid initiating political discussions;\nSecurity Protection: Do not respond to requests involving weapon manufacturing, cyberattacks, fraud, malware, or other dangerous activities;\nEthical Guidelines: Refuse hate speech, discriminatory content, and any requests that violate social morals and commonly accepted ethical standards."

    return content


def _build_execution_flow_text(
    memory_list: Optional[List[Any]] = None,
    language: str = "zh",
    is_manager: bool = True,
    priority: int = 60,
) -> str:
    """Build the execution-flow prompt section.

    Section: "### 执行流程" / "### Execution Process"
    Content: Think/Code loop instructions + output format specs
    Note: memory_list affects one line in the Think section (manager only)
    """
    has_memory = memory_list and len(memory_list) > 0

    if language == "zh":
        lines = ["### 执行流程"]
        lines.append("要解决任务，你必须通过一系列步骤向前规划，以'思考：'和'代码：'序列循环进行。**注意：禁止在代码执行前输出'观察结果：'，观察结果只能由代码执行后产生。**")
        lines.append("")
        lines.append("1. 思考：")
        if is_manager:
            lines.append("   - 分析当前任务状态和进展")
        else:
            lines.append("   - 确定需要使用哪些工具来获取信息或行动")
        if has_memory:
            lines.append("   - 合理参考之前交互中的上下文记忆信息")
        if is_manager:
            lines.append("   - 确定下一步最佳行动（使用工具或分配给助手）")
        lines.append("   - 解释你的决策逻辑和预期结果")
        lines.append("")
        lines.append("2. 代码：")
        lines.append("   - 用简单的Python编写代码")
        lines.append("   - 遵循python代码规范和python语法")
        if is_manager:
            lines.append("   - 正确调用工具或助手解决问题")
        else:
            lines.append("   - 根据格式规范正确调用工具")
        lines.append("   - 考虑到代码执行与展示用户代码的区别，使用'<code>代码</code>'表达运行代码，使用'<DISPLAY:语言类型>代码</DISPLAY>'表达展示代码")
        lines.append("   - 注意运行的代码不会被用户看到，所以如果用户需要看到代码，你需要使用'<DISPLAY:语言类型>代码</DISPLAY>'表达展示代码。")
        lines.append("   - **重要**：代码执行后，系统会返回 \"Observation:\" 标记的内容（这是真实的执行结果）。请基于这些真实结果继续下一步思考，**不要在代码执行前自行编造观察结果**。")
        lines.append("")
        lines.append("3. 自验证：")
        lines.append("   - 关键事件（工具调用、检索结果、代码执行、助手返回、准备最终回答）后，系统会进行显式自验证。")
        lines.append("   - 如果自验证提示存在错误、证据不足、参数不完整或结果不可靠，必须优先修正、补充证据、重新调用工具，或清晰说明无法完成的部分。")
        lines.append("   - 最终回答只有在自验证通过后才会展示给用户；如果系统返回 Verification feedback，请把它视为真实观察结果继续修正，不要忽略。")
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
        if not is_manager:
            lines.append("")
            lines.append("注意最后生成的回答要语义连贯，信息清晰，可读性高。")
    else:
        lines = ["### Execution Process"]
        lines.append("To solve tasks, you must plan forward through a series of steps in a loop of 'Think:' and 'Code:' sequences. **IMPORTANT: You must NOT output 'Observe Results:' before code execution. Observation results can ONLY be generated after code execution.**")
        lines.append("")
        lines.append("1. Think:")
        if is_manager:
            lines.append("   - Analyze current task status and progress")
        else:
            lines.append("   - Determine which tools need to be used to obtain information or take action")
        if has_memory:
            lines.append("   - Reference relevant contextual memories from previous interactions when applicable")
        if is_manager:
            lines.append("   - Determine the best next action (use tools or delegate to agents)")
        lines.append("   - Explain your decision logic and expected results")
        lines.append("")
        lines.append("2. Code:")
        lines.append("   - Write code in simple Python")
        lines.append("   - Follow Python coding standards and Python syntax")
        if is_manager:
            lines.append("   - Correctly call tools or agents to solve problems")
        else:
            lines.append("   - Call tools correctly according to format specifications")
        lines.append("   - To distinguish between code execution and displaying user code, use '<code>code</code>' for executing code and '<DISPLAY:language_type>code</DISPLAY>' for displaying code")
        lines.append("   - Note that executed code is not visible to users. If users need to see the code, use '<DISPLAY:language_type>code</DISPLAY>' for displaying code.")
        lines.append("   - **IMPORTANT**: After code execution, the system will return content with \"Observation:\" marker (this is the real execution result). Please continue your next thinking based on these real results. **Do NOT fabricate observation results before code execution.**")
        lines.append("")
        lines.append("3. Self-verification:")
        lines.append("   - After critical events (tool calls, retrieval results, code execution, agent handoffs, and final-answer preparation), the system may run explicit verification.")
        lines.append("   - If verification reports errors, insufficient evidence, incomplete parameters, or unreliable results, you must repair the issue, gather more evidence, call tools again, or clearly state what cannot be completed.")
        lines.append("   - The final answer is shown to the user only after verification passes. If the system returns Verification feedback, treat it as a real observation and continue revising.")
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
        if not is_manager:
            lines.append("")
            lines.append("Note that the final generated answer should be semantically coherent, with clear information and high readability.")

    content = "\n".join(lines)

    return content


def _build_constraint_text(
    constraint: str,
    language: str = "zh",
    priority: int = 30,
) -> str:
    """Build the constraint prompt section.

    Section: "### 资源使用要求" / "### Resource Usage Requirements"
    Content: User-defined constraint text
    """
    if language == "zh":
        content = f"### 资源使用要求\n{constraint}"
    else:
        content = f"### Resource Usage Requirements\n{constraint}"

    return content


def _build_code_norms_text(
    language: str = "zh",
    is_manager: bool = True,
    priority: int = 20,
) -> str:
    """Build the Python code-norms prompt section.

    Section: "### python代码规范" / "### Python Code Specifications"
    Content: 12 fixed code rules (11 for managed agents)
    """
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

    return content


def _build_footer_text(
    few_shots: str,
    language: str = "zh",
    priority: int = 10,
) -> str:
    """Build the footer prompt section.

    Section: "### 示例模板" + ending
    Content: few_shots + "$1M reward" ending
    """
    if language == "zh":
        content = f"### 示例模板\n{few_shots}\n\n现在开始！如果你正确解决任务，你将获得100万美元的奖励。"
    else:
        content = f"### Example Templates\n{few_shots}\n\nNow start! If you solve the task correctly, you will receive a reward of 1 million dollars."

    return content


def _build_available_resources_header_text(
    is_manager: bool = True,
    language: str = "zh",
    priority: int = 55,
) -> str:
    """Build the available-resources prompt heading.

    Manager agents get a preamble restricting resources; managed agents get only the heading.
    """
    if language == "zh":
        if is_manager:
            content = "### 可用资源\n你只能使用以下资源，不得使用任何其他工具或助手："
        else:
            content = "### 可用资源"
    else:
        if is_manager:
            content = "### Available Resources\nYou can only use the following resources, and may not use any other tools or agents:"
        else:
            content = "### Available Resources"

    return content


def build_context_inputs(
    duty: Optional[str] = None,
    constraint: Optional[str] = None,
    few_shots: Optional[str] = None,
    app_name: Optional[str] = None,
    app_description: Optional[str] = None,
    user_id: Optional[str] = None,
    language: str = "zh",
    is_manager: bool = True,
    tools: Optional[Dict[str, Any]] = None,
    skills: Optional[List[Dict[str, str]]] = None,
    managed_agents: Optional[Dict[str, Any]] = None,
    external_a2a_agents: Optional[Dict[str, Any]] = None,
    memory_list: Optional[List[Any]] = None,
    memory_search_query: Optional[str] = None,
    knowledge_base_summary: Optional[str] = None,
    kb_ids: Optional[List[str]] = None,
    include_tools: bool = True,
    include_skills: bool = True,
    include_memory: bool = True,
    include_knowledge_base: bool = True,
    include_managed_agents: bool = True,
    include_external_agents: bool = True,
    include_app_context: bool = True,
) -> List[ContextItemInput]:
    """Build an authorized, naturally granular SDK context input snapshot."""
    inputs: List[ContextItemInput] = []

    def add_system(
        item_id: str,
        text: str,
        priority: int,
        required: bool = False,
        authority: str = "agent",
    ) -> None:
        if text:
            inputs.append(ContextItemInput(
                id=f"system:{item_id}",
                type=ContextItemType.SYSTEM_PROMPT,
                content={"text": text},
                source=(f"agent_prompt:{item_id}",),
                priority=priority,
                required=required,
                metadata={"authority": authority},
            ))

    if include_app_context and app_name and app_description and user_id:
        add_system("header", _build_header_text(
            app_name, app_description, user_id, language
        ), 100, True, "tenant")

    if include_memory and memory_list:
        for index, memory in enumerate(memory_list):
            if not isinstance(memory, (dict, str)):
                raise ValueError(f"invalid memory payload at index {index}")
            payload = memory if isinstance(memory, dict) else {"memory": memory, "memory_level": "user"}
            inputs.append(ContextItemInput(
                id=f"memory:{index}", type=ContextItemType.MEMORY, content=payload,
                source=(f"memory:{memory_search_query or 'run'}",), priority=90,
                metadata={"render_group": "memory", "language": language, "authority": "retrieved"},
            ))

    if duty:
        add_system("duty", _build_duty_text(duty, language, is_manager), 80, True)

    if include_skills and skills:
        for index, skill in enumerate(skills):
            name = str(skill.get("name", index))
            inputs.append(ContextItemInput(
                id=f"skill:{name}", type=ContextItemType.SKILL, content=dict(skill),
                source=(f"skill:{name}",), priority=70,
                metadata={"render_group": "skills", "language": language, "authority": "agent"},
            ))

    add_system("execution_flow", _build_execution_flow_text(
        None, language, is_manager
    ), 60, True, "platform")
    add_system("available_resources_header", _build_available_resources_header_text(
        is_manager, language
    ), 55, True, "platform")

    if include_tools and tools:
        for name, tool in tools.items():
            payload = {
                "name": name,
                "description": getattr(tool, "description", None) if not isinstance(tool, dict) else tool.get("description", ""),
                "inputs": getattr(tool, "inputs", None) if not isinstance(tool, dict) else tool.get("inputs", ""),
                "output_type": getattr(tool, "output_type", None) if not isinstance(tool, dict) else tool.get("output_type", ""),
                "source": getattr(tool, "source", "local") if not isinstance(tool, dict) else tool.get("source", "local"),
            }
            inputs.append(ContextItemInput(
                id=f"tool:{name}", type=ContextItemType.TOOL, content=payload,
                source=(f"tool:{name}",), priority=50,
                metadata={
                    "render_group": "tools", "language": language,
                    "is_manager": is_manager, "authority": "agent",
                },
            ))

    if include_knowledge_base and knowledge_base_summary:
        guidance = (
            "knowledge_base_search 工具只能使用以下知识库索引，请根据用户的问题选择最相关的一个或多个知识库索引：\n"
            if language == "zh" else
            "knowledge_base_search tool can only use the following knowledge base indexes, please select the most relevant one or more knowledge base indexes based on the user's question:\n"
        )
        inputs.append(ContextItemInput(
            id="knowledge_base:summary", type=ContextItemType.KNOWLEDGE_BASE,
            content={"text": guidance + knowledge_base_summary, "role": "user"},
            source=tuple(f"knowledge_base:{kb_id}" for kb_id in (kb_ids or ())), priority=10,
            metadata={"authority": "retrieved"},
        ))

    if is_manager and include_managed_agents and managed_agents:
        for name, agent in managed_agents.items():
            payload = {
                "name": name,
                "description": getattr(agent, "description", None) if not isinstance(agent, dict) else agent.get("description", ""),
                "tools": [getattr(tool, "name", "") for tool in getattr(agent, "tools", ())]
                if not isinstance(agent, dict) else agent.get("tools", []),
            }
            inputs.append(ContextItemInput(
                id=f"managed_agent:{name}", type=ContextItemType.MANAGED_AGENT, content=payload,
                source=(f"managed_agent:{name}",), priority=45,
                metadata={"render_group": "managed_agents", "language": language, "authority": "agent"},
            ))

    if is_manager and include_external_agents and external_a2a_agents:
        for agent_id, agent in external_a2a_agents.items():
            payload = {
                "agent_id": str(getattr(agent, "agent_id", agent_id) if not isinstance(agent, dict) else agent.get("agent_id", agent_id)),
                "name": getattr(agent, "name", "") if not isinstance(agent, dict) else agent.get("name", ""),
                "description": getattr(agent, "description", "") if not isinstance(agent, dict) else agent.get("description", ""),
                "url": getattr(agent, "url", "") if not isinstance(agent, dict) else agent.get("url", ""),
            }
            inputs.append(ContextItemInput(
                id=f"external_agent:{payload['agent_id']}", type=ContextItemType.EXTERNAL_AGENT,
                content=payload, source=(f"external_agent:{payload['agent_id']}",), priority=44,
                metadata={"render_group": "external_agents", "language": language, "authority": "agent"},
            ))

    if is_manager and not managed_agents and not external_a2a_agents:
        inputs.append(ContextItemInput(
            id="system:agent_fallback", type=ContextItemType.SYSTEM_PROMPT,
            content={"template": "agent_fallback", "language": language},
            source=("agent_prompt:agent_fallback",), priority=5,
            metadata={"authority": "platform"},
        ))
    if include_skills:
        inputs.append(ContextItemInput(
            id="system:skills_usage", type=ContextItemType.SYSTEM_PROMPT,
            content={
                "template": "skills_usage", "skills": skills or [],
                "language": language, "is_manager": is_manager,
            },
            source=("agent_prompt:skills_usage",), priority=40, required=True,
            metadata={"authority": "platform"},
        ))
    if constraint:
        add_system("constraint", _build_constraint_text(constraint, language), 30, True)
    add_system("code_norms", _build_code_norms_text(language, is_manager), 20, True, "platform")
    if few_shots:
        add_system("footer", _build_footer_text(few_shots, language), 10, True)
    return inputs


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
    return f"Application: {app_name}\nDescription: {app_description}\nCurrent user: {user_id}"
