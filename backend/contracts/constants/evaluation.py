# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Evaluation system limits and quotas.

PDF report labels — zh/en key-value dicts.

Follows the same dict-based i18n pattern as the former
``evaluation_messages.py``, scoped exclusively to PDF report strings.

Evaluation status constants.
"""

# Concurrent tasks
MAX_CONCURRENT_RUNS = 5
MAX_TOTAL_RUNS = 500

# Per-run
MAX_EVALUATORS_PER_RUN = 5

# Scoring
DEFAULT_PASS_THRESHOLD = 0.5
SCORE_RANGE_MIN_DEFAULT = 0.0
SCORE_RANGE_MAX_DEFAULT = 1.0
SCORE_ABSOLUTE_MAX = 100.0

# Evaluator
EVALUATOR_NAME_MIN_LEN = 1
EVALUATOR_NAME_MAX_LEN = 50
EVALUATOR_DESC_MAX_LEN = 200
EVALUATOR_PROMPT_MAX_LEN = 5_000
EVALUATOR_CODE_MAX_LEN = 20_000

# Retention
RUN_RETENTION_DAYS = 30

# Evaluation sets
MAX_EVALUATION_SETS = 50
MAX_CASES_PER_SET = 2_000
MAX_TURNS_PER_SESSION = 10
SET_NAME_MIN_LEN = 2
SET_NAME_MAX_LEN = 64

# Case content
CASE_QUERY_MAX_LEN = 2_000
CASE_ANSWER_MAX_LEN = 5_000

# Annotation
MAX_ANNOTATIONS_PER_CASE = 5
MAX_ANNOTATION_SCHEMAS = 500
ANNOTATION_CLASSIFICATION_MAX_OPTIONS = 20
ANNOTATION_OPTION_MAX_LEN = 50
ANNOTATION_NUMBER_MIN = -999999
ANNOTATION_NUMBER_MAX = 999999
ANNOTATION_TEXT_MAX_LEN = 200


_REPORT_LABELS = {
    "zh": {
        "TITLE": "Agent 评测报告",
        "SUBTITLE": "智能体: {agent} | 报告 #{id} | 生成时间 {time}",
        "SECTION_OVERVIEW": "一、概述",
        "SECTION_CONFIG": "二、评测配置",
        "SECTION_ANALYSIS": "三、评估结果分析",
        "SECTION_DETAILS": "四、用例详情",
        "STATUS_COMPLETED": "已完成",
        "STATUS_RUNNING": "运行中",
        "STATUS_PENDING": "等待中",
        "STATUS_FAILED": "失败",
        "SCORE_EXCELLENT": "表现优秀",
        "SCORE_GOOD": "表现良好",
        "SCORE_NEEDS_IMPROVEMENT": "需要改进",
        "SCORE_NA": "未指定",
        "METRIC_SCORE": "综合得分 (0-1)",
        "METRIC_PASS_RATE": "通过率",
        "METRIC_TOTAL": "用例总数",
        "META_TARGET": "评测对象",
        "META_SET": "评测集",
        "META_NO_SET": " [无评测集]",
        "META_MODEL": "Judge 模型",
        "META_VERSION": "版本",
        "META_CREATED": "创建时间",
        "META_COMPLETED": "完成时间",
        "META_EVALUATORS": "评估器数量",
        "META_PROGRESS": "进度",
        "CHART_SCORES": "各评估器得分",
        "CHART_DISTRIBUTION": "得分分布",
        "ANALYSIS_TEMPLATE": "在 {n} 个评估维度中，<b>「{best}」</b>得分最高（{best_score:.2f}），<b>「{worst}」</b>得分最低（{worst_score:.2f}）。",
        "SUMMARY_TEMPLATE": "本次评测对智能体 {agent} 进行了 {total} 个测试用例的评估，状态为{status}，综合得分 {overall}（{level}）。共使用了 {evaluator_count} 个评估器（{evaluator_names}），其中 {pass_count} 个用例通过（通过率 {pass_rate}），{fail_count} 个用例未通过。",
        "SUMMARY_EXTRA": " 该智能体在 {top}/{total} 个用例中得分 ≥0.8，整体质量{quality}。",
        "QUALITY_HIGH": "较高",
        "QUALITY_MEDIUM": "中等",
        "QUALITY_LOW": "偏低",
        "COL_HEADER_INDEX": "#",
        "COL_HEADER_QUERY": "评测问题",
        "COL_HEADER_SCORE": "评估得分",
        "COL_HEADER_RESULT": "结果",
        "PASS_LABEL": "通过",
        "FAIL_LABEL": "失败",
        "FOOTER": "Nexent Agent 评测报告 | 生成时间 {time}",
        "SECTION_ANNOTATIONS": "标注统计",
        "ANNOTATION_COVERAGE": "已标注 {coverage}",
        "ANNOTATION_NO_DATA": "暂无标注数据",
    },
    "en": {
        "TITLE": "Agent Evaluation Report",
        "SUBTITLE": "Agent: {agent} | Report #{id} | Generated {time}",
        "SECTION_OVERVIEW": "1. Overview",
        "SECTION_CONFIG": "2. Configuration",
        "SECTION_ANALYSIS": "3. Results Analysis",
        "SECTION_DETAILS": "4. Case Details",
        "STATUS_COMPLETED": "Completed",
        "STATUS_RUNNING": "Running",
        "STATUS_PENDING": "Pending",
        "STATUS_FAILED": "Failed",
        "SCORE_EXCELLENT": "Excellent",
        "SCORE_GOOD": "Good",
        "SCORE_NEEDS_IMPROVEMENT": "Needs Improvement",
        "SCORE_NA": "N/A",
        "METRIC_SCORE": "Overall Score (0-1)",
        "METRIC_PASS_RATE": "Pass Rate",
        "METRIC_TOTAL": "Total Cases",
        "META_TARGET": "Target",
        "META_SET": "Evaluation Set",
        "META_NO_SET": " [No Set]",
        "META_MODEL": "Judge Model",
        "META_VERSION": "Version",
        "META_CREATED": "Created",
        "META_COMPLETED": "Completed",
        "META_EVALUATORS": "Evaluators",
        "META_PROGRESS": "Progress",
        "CHART_SCORES": "Per-Evaluator Scores",
        "CHART_DISTRIBUTION": "Score Distribution",
        "ANALYSIS_TEMPLATE": 'Among {n} evaluators, <b>"{best}"</b> scored highest ({best_score:.2f}), <b>"{worst}"</b> scored lowest ({worst_score:.2f}).',
        "SUMMARY_TEMPLATE": "Evaluated Agent {agent} across {total} test cases, status: {status}, overall score {overall} ({level}). Used {evaluator_count} evaluators ({evaluator_names}), {pass_count} passed (pass rate {pass_rate}), {fail_count} failed.",
        "SUMMARY_EXTRA": " {top}/{total} cases scored 0.8, overall quality {quality}.",
        "QUALITY_HIGH": "high",
        "QUALITY_MEDIUM": "medium",
        "QUALITY_LOW": "low",
        "COL_HEADER_INDEX": "#",
        "COL_HEADER_QUERY": "Question",
        "COL_HEADER_SCORE": "Score",
        "COL_HEADER_RESULT": "Result",
        "PASS_LABEL": "Pass",
        "FAIL_LABEL": "Fail",
        "FOOTER": "Nexent Agent Evaluation Report | Generated {time}",
        "SECTION_ANNOTATIONS": "Annotations",
        "ANNOTATION_COVERAGE": "Annotated {coverage}",
        "ANNOTATION_NO_DATA": "No annotation data",
    },
}


def get_report_labels(language: str = "zh") -> dict:
    """Return the label dict for the given language. Falls back to 'zh'."""
    return _REPORT_LABELS.get(language, _REPORT_LABELS["zh"])


class EvalRunStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EvalCaseStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EvalPassStatus:
    PASS = "pass"
    FAIL = "fail"


# Used in generate_analysis_report_impl
MAX_FAILURE_EXAMPLES = 200


_AUTH_REQUIRED_MSG = "Authentication required"


_UNKNOWN_ID = "<unknown>"

_UNAUTHORIZED_MESSAGE = "Authentication required"
