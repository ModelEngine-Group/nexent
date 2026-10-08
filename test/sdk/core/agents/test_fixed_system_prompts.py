"""D1 contracts for SDK-owned fixed system prompts."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import tomllib

EXPECTED_CLARIFICATION = {
    "zh": (
        "你具备人在回路的能力，允许用户在智能体自主运行的关键节点进行关键信息的确认与澄清。\n"
        "该能力并非每次会话都必须使用，当用户请求清晰且无关键事实缺失时可直接回答。\n"
        "不要询问可选的偏好信息、用户已提供的信息或工具能够取得或已经取得的事实。只有缺少的信息会阻止智能体正确或安全地继续运行，或者上下文无法消除会显著改变结果的歧义时，才使用人在回路能力。\n"
        "每轮会话中需要用户澄清时，仅调用一次 ask_user(questions=[...]) ，其中仅包括需要确认的关键核心问题；只有存在相互独立的阻塞项时才可询问更多问题。\n"
        "问题标题使用用户语言，每个问题只询问一个事实，并尽可能提供有用选项。每个问题包含 id、type、title 和 required；type 为 text、single_choice 或 multiple_choice。选择题还要在问题对象上直接提供 options [{id,label}] 和 allow_other，不要嵌套 choices 对象。示例：\n"
        "<code>\n"
        "ask_user(questions=[{\"id\": \"topic\", \"type\": \"text\", \"title\": \"通知的主题是什么？\", \"required\": True}])\n"
        "</code>\n"
        "不要重复这些问题。等待返回答案后继续同一任务。用户回复后直接使用答案，不重复或改写问题。仍有未知信息时，明确说明无法确认的部分再尝试继续。"
    ),
    "en": (
        "You have a human-in-the-loop capability that allows the user to confirm and clarify key information at critical points while the agent runs autonomously.\n"
        "This capability is not required in every conversation. Answer directly when the request is clear and no key fact is missing.\n"
        "Do not ask about optional preferences, information already supplied, or facts tools can obtain or have already obtained. Only use the human-in-the-loop capability to request clarification when a missing key fact prevents correct or safe progress, or when context cannot reasonably resolve an ambiguity that would materially change the result.\n"
        "When clarification is necessary, call ask_user(questions=[...]) once with one concise structured card. Ask only a small number of essential core questions; ask more only when there are independent and indispensable blockers.\n"
        "Use short titles in the user's language, one fact per question, and useful choices where possible. Each question has id, type, title and required; type is text, single_choice or multiple_choice. For choice questions, put options [{id,label}] and allow_other directly on the question object, never inside a nested choices object. Example:\n"
        "<code>\n"
        "ask_user(questions=[{\"id\": \"topic\", \"type\": \"text\", \"title\": \"What is the notice about?\", \"required\": True}])\n"
        "</code>\n"
        "Do not repeat the questions. Wait for the returned answers, then continue the same task. After the user replies, use the answers directly without repeating or rephrasing the questions. For remaining unknowns, explain what cannot be confirmed and then try to continue."
    ),
}


def test_ut_sdk_dpr_012_fixed_prompt_resource_is_packaged():
    """UT-SDK-DPR-012: the fixed YAML is declared as SDK package data."""
    repository_root = Path(__file__).parents[4]
    pyproject = tomllib.loads(
        (repository_root / "sdk" / "pyproject.toml").read_text(encoding="utf-8")
    )

    package_data = pyproject["tool"]["setuptools"]["package-data"]
    assert "en/*/*.yaml" in package_data["nexent.core.prompts"]
    prompt_root = repository_root / "sdk/nexent/core/prompts"
    assert (prompt_root / "zh/agent/human_interaction.yaml").is_file()
    assert (prompt_root / "en/agent/context_summary.yaml").is_file()
    assert (prompt_root / "en/agent/answer_verifier.yaml").is_file()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_ut_sdk_dpr_012_fixed_hitl_prompt_matches_approved_policy(language):
    """UT-SDK-DPR-012: SDK HITL text matches the approved bilingual policy."""
    from nexent.core.agents.clarification import clarification_policy
    from nexent.core.prompts import load_prompt

    expected = ("### 向用户澄清\n" if language == "zh" else "### Clarifying with the User\n") + EXPECTED_CLARIFICATION[language]
    assert load_prompt(language, "agent/human_interaction")["clarification_policy"] == expected
    assert clarification_policy("nexent_ask_user", language=language) == expected.replace(
        "ask_user", "nexent_ask_user",
    )


def test_ut_sdk_dpr_012_summary_defaults_and_explicit_overrides():
    """UT-SDK-DPR-012: SDK resources supply defaults without blocking overrides."""
    from nexent.core.agents.context.config import ContextManagerConfig
    from nexent.core.prompts import load_prompt

    config = ContextManagerConfig()
    assert config.summary_system_prompt == load_prompt("en", "agent/context_summary")["system_prompt"]
    assert config.incremental_summary_system_prompt == load_prompt(
        "en", "agent/context_summary",
    )["incremental_system_prompt"]

    overridden = ContextManagerConfig(
        summary_system_prompt="custom summary",
        incremental_summary_system_prompt="custom incremental summary",
    )
    assert overridden.summary_system_prompt == "custom summary"
    assert overridden.incremental_summary_system_prompt == "custom incremental summary"


def test_ut_sdk_dpr_012_verifier_uses_sdk_fixed_prompt():
    """UT-SDK-DPR-012: final verification reads its system prompt from SDK resources."""
    from nexent.core.agents.verification import VerificationController
    from nexent.core.prompts import load_prompt

    controller = VerificationController.__new__(VerificationController)
    controller.config = SimpleNamespace(pass_score=0.75, strictness="balanced")
    messages = controller._build_verifier_messages(
        "task",
        "candidate",
        "evidence",
        policy={
            "task_profile": "evidence",
            "evidence_required": True,
            "tool_error_check_required": True,
        },
    )
    assert messages[0].content[0]["text"] == load_prompt("en", "agent/answer_verifier")["system_prompt"]


@pytest.mark.parametrize(
    "args",
    [
        ("fr", "agent/human_interaction", ValueError),
        ("en", "agent/missing", FileNotFoundError),
        ("en", "../agent/context_summary", ValueError),
    ],
)
def test_ut_sdk_dpr_012_fixed_prompt_lookup_rejects_unknown_paths(args):
    """UT-SDK-DPR-012: invalid fixed-prompt paths fail without fallback text."""
    from nexent.core.prompts import load_prompt

    language, path, error = args
    with pytest.raises(error):
        load_prompt(language, path)
