# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Relevance gates reject partial lexical matches without curated word lists."""

import pytest

from runtime.agentos.agent_creator_config import build_nl2agent_system_prompt
from services import nl2agent_resource_flow as flow
from management.services.agent import nl2agent as service
from management.services.agent.nl2agent_tools import ResourceRequirement


def resource(name, description, **extra):
    return {"candidate_ref": "tool:1", "resource_type": "tool", "source": "LOCAL_TOOL",
            "name": name, "description": description, "names": [name],
            "descriptions": [description], "labels": [], "interfaces": [],
            "installed": True, "quality": 1.0, **extra}


@pytest.mark.parametrize("query,name,description", [
    ("generate image", "analyze_image", "Analyze an existing image and return its description."),
    ("query train route stops", "send_email", "Send an email to recipients with a subject and body."),
    ("search public webpages", "knowledge_base_search", "Search documents in an internal knowledge base."),
    ("recover deleted files", "delete_file", "Delete files from the workspace."),
    ("write inventory", "read_inventory", "Read inventory records."),
    ("write configuration", "read_configuration", "Read configuration records."),
    ("set inventory", "get_inventory", "Get inventory records."),
])
def test_partial_names_and_wrong_actions_do_not_reach_verification(query, name, description):
    assert flow._rank("r1", query, [resource(name, description)]) == []


@pytest.mark.parametrize("query,name,description", [
    ("send email", "mailer", "Send email to recipients with attachments."),
    ("public web search", "deepseek_search", "Search public webpages for current information."),
    ("generate image", "image_generator", "Generate an image from a text prompt."),
    ("daily report", "daily_report", "Create a daily report."),
    ("daily_reprot", "daily_report", "opaque"),
    ("发送邮件", "mailer", "发送邮件到指定收件人。"),
    ("图片生成", "image_generator", "按提示词进行图片生成。"),
    ("删除工作区指定单个文件", "delete_file", "删除单个工作区文件。此操作不可恢复，也不会删除目录。"),
    ("查询指定区间车次经停站到发时间", "train_routes",
     "查询特定列车车次在指定区间内的途径车站、到站时间、出发时间及停留时间等详细经停信息。"),
])
def test_complete_capability_and_name_matches_are_recalled(query, name, description):
    assert [item["candidate_ref"] for item in flow._rank("r1", query, [resource(name, description)])] == ["tool:1"]


def test_interfaces_and_labels_alone_cannot_admit_a_resource():
    row = resource("opaque", "opaque", interfaces=["generate image"], labels=["generate image"])
    assert flow._rank("r1", "generate image", [row]) == []


def test_ranking_bonuses_cannot_cross_relevance_threshold(mocker):
    mocker.patch.object(service, "_resource_similarity", return_value=.6)
    row = resource("opaque", "send email")
    requirement = ResourceRequirement(requirement_id="r", query="send email")
    plain = service._score_resource_requirement(requirement, {**row, "installed": False, "quality": 0})
    boosted = service._score_resource_requirement(requirement, row)
    assert plain < .5
    assert boosted == plain


def test_qualified_matches_keep_ranking_bonuses():
    row = resource("mailer", "send email")
    requirement = ResourceRequirement(requirement_id="r", query="send email")
    plain = service._score_resource_requirement(requirement, {**row, "installed": False, "quality": 0})
    boosted = service._score_resource_requirement(requirement, row)
    assert plain >= .5
    assert boosted == pytest.approx(plain + .05)


@pytest.mark.parametrize("left,right", [("", "search"), ("search", ""), (None, "search")])
def test_empty_similarity_is_zero(left, right):
    assert service._resource_similarity(left, right) == 0


@pytest.mark.parametrize("language", ["zh", "en"])
def test_prompt_prepares_positive_queries_without_changing_constraints(language):
    prompt = build_nl2agent_system_prompt(language)
    assert "positive action" in prompt if language == "en" else "正向动作" in prompt


@pytest.mark.parametrize("language", ["zh", "en"])
def test_prompt_separates_resource_capability_from_runtime_search_content(language):
    prompt = build_nl2agent_system_prompt(language)
    expected = "runtime search content" if language == "en" else "运行时检索内容"
    assert expected in prompt
    assert '"en":"knowledge base search"' in prompt


def test_knowledge_capability_queries_recall_native_tool_for_material_requests():
    from nexent.core.tools.knowledge_base_search_tool import KnowledgeBaseSearchTool
    from nexent.core.tools.haotian_search_tool import HaotianSearchTool

    catalog = [resource(tool.name, tool.description,
                        candidate_ref=f"tool:{index}",
                        descriptions=[tool.description, tool.description_zh])
               for index, tool in enumerate((KnowledgeBaseSearchTool, HaotianSearchTool), 1)]
    query = "使用知识库检索工具查询已关联的活动方案、品牌介绍和往期素材"
    result = flow._rank("r1", query, catalog, search_queries={"zh": "知识库检索", "en": "knowledge base search"})
    assert result[0]["name"] == "knowledge_base_search"
    assert result[0]["retrieval_score"] == 1.0


@pytest.mark.parametrize("pair,short,expected", [
    ({"zh": "知识库检索", "en": "knowledge base search"}, "event materials",
     {"知识库检索", "knowledge base search"}),
    (None, "knowledge base search", {"knowledge base search"}),
    (None, None, {"查询活动方案品牌介绍和往期素材"}),
])
def test_prepared_capabilities_replace_runtime_topics_in_recall(mocker, pair, short, expected):
    score = mocker.patch.object(service, "_score_resource_requirement", return_value=.1)
    flow._rank("r1", "查询活动方案品牌介绍和往期素材", [resource("opaque", "opaque")],
               search_queries=pair, search_query=short)
    assert {call.args[0].query for call in score.call_args_list} == expected
