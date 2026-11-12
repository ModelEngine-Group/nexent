# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Core-neutral behavior policies and business context selection."""

from nexent.core.agents.context.models import ContextItemInput, ContextItemType
from nexent.core.prompts import load_prompt


CURRENT_TASK_GUIDANCE = (
    "Process only the latest user request in this run. Earlier conversation messages, attachments and "
    "results are historical reference, not pending tasks. Do not repeat earlier requests or tool calls "
    "unless the latest user request explicitly asks you to. Reuse prior results when answering follow-up "
    "questions; the presence of an earlier attachment does not require analyzing it again."
    " Never copy internal history or attachment envelopes into your response. "
    "Keep the final answer limited to user-facing content; internal records are reference only."
)

RESOURCE_GUIDANCE = (
    "Honor an explicit latest-request delegation through an authorized collaborator before direct execution. "
    "The file-creation instructions below apply only when direct execution is appropriate, "
    "not as a substitute for requested delegation. "
    "For a new file request no download is needed. Follow the authorized skill instructions, then "
    "create the requested file with controlled Python in the current outputs directory. "
    "Use Python libraries and shell-free pip argv only when the configured sandbox permits it. "
    "Upload the actual generated file with upload_to_s3 and use the returned file link. "
    "Never claim a file exists or was uploaded without successful tool observations."
)

SKILL_GUIDANCE = (
    "Skills are authorized local resources, not S3 objects. Read a listed skill with read_skill_md "
    "and its configuration with read_skill_config. Run only a script actually listed in that skill "
    "using run_skill_script; never invent skill names, script paths or S3 paths. "
    "download_from_s3 is only for actual authorized uploaded/generated file references, never for "
    "skills or missing inputs. Do not retry a denied or missing file using guessed path variants. "
)

COMMON_BEHAVIOR_GUIDANCE = CURRENT_TASK_GUIDANCE + "\n\n" + RESOURCE_GUIDANCE
CORE_PROTOCOL_SYSTEM_IDS = frozenset({
    "system:execution_flow", "system:code_norms", "system:restricted_python_execution",
    "system:final_answer_guidance", "system:clarification_protocol",
})


def common_behavior_guidance(language="en", *, skills_available=False):
    """Render the same behavior and user-facing result rules for every Core."""
    language = language if isinstance(language, str) and language in {"zh", "en"} else "en"
    return (COMMON_BEHAVIOR_GUIDANCE + ("\n\n" + SKILL_GUIDANCE if skills_available else "")
            + "\n\n" + load_prompt(language, "agent/response_style")["policy"])


def with_common_behavior(items, language="en"):
    """Insert one authoritative shared behavior item without mutating saved inputs."""
    items = tuple(items)
    skills_available = any(item.type == ContextItemType.SKILL for item in items)
    return [
        *(item for item in items if item.id != "system:common_behavior"),
        ContextItemInput(
            id="system:common_behavior", type=ContextItemType.SYSTEM,
            content={"text": common_behavior_guidance(language, skills_available=skills_available)},
            source=("platform:common_behavior",), priority=99,
            metadata={"authority": "platform", "layout_order": 36},
        ),
    ]


def business_system_instructions(instructions, items, language="en"):
    """Project shared authorized business/system sections without executable Core syntax."""
    return [instructions or "", *(
        item.content.get("text", "") for item in with_common_behavior(items, language)
        if item.type == ContextItemType.SYSTEM and item.id not in CORE_PROTOCOL_SYSTEM_IDS
    )]
