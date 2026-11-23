# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Recognize first-party Skill requests without invoking the business model."""

import re

SKILL = re.compile(r"技能|\bskills?\b|skill", re.I)
FUTURE = re.compile(r"以后|今后|往后|下次起|每次|始终|from now on|in future|always", re.I)
CHANGE = re.compile(r"优化|改进|改为|改成|修改|调整|改一下|改一改|更新|improve|change|update|revise", re.I)
DIRECTIVE = re.compile(r"要|请|应当|应该|必须|默认|保留|补充|列出|标注|标为|写为|写成|记录|增加|添加|取消|删除|避免|使用|排除|不能|不要|keep|include|preserve|use|list|mark|exclude|omit|must|should", re.I)
BEHAVIOR = re.compile(
    r"保留|补上|补充|列出|标注|标为|写为|写成|记录|增加|添加|删除|展示|隐藏|避免|使用|排除|"
    r"检查|校验|核对|调用|排序|输出|重试|改成|改为|跳过|\b(?:keep|include|preserve|use|list|mark|exclude|omit|format|sort|validate)\b",
    re.I,
)
BUSINESS = re.compile(r"(?:这次|本次|这一次|这回)(?:先|请|帮我|把|也|就|用|的|改|只)|现在(?:先|请|帮我)|(?:this time|for now)[, ]", re.I)
PROGRESS = re.compile(r"(?:建议|提议).{0,18}(?:进展|进度|怎么样|采用|处理了吗)|(?:status|progress).{0,25}suggestion", re.I)
NUMBER = re.compile(r"(?:建议(?:编号)?\s*[#＃]?\s*|(?<![A-Za-z0-9_-])S-)([1-9][0-9]{0,15})(?![0-9])", re.I)
CONFIRM = re.compile(r"^(?:以后(?:都)?(?:这样(?:做)?|这么做)?|提交(?:建议)?|确认提交|from now on|submit it)[。.!！\s]*$", re.I)
CANCEL = re.compile(r"^(?:算了|不用(?:提交)?了?|取消(?:建议)?|只改这次|仅(?:改)?本次|just this time|cancel)[。.!！\s]*$", re.I)
# Questions, quotations, and reported speech do not grant permission to submit a change.
QUOTED = re.compile(r"“[^”]*”|「[^」]*」|『[^』]*』|\x22[^\x22]*\x22|`[^`]*`")
REPORTED = re.compile(r"他说|她说|同事说|原文|举例|比如|转述|翻译下面|翻译这|\b(?:example|suppose|said|asked|translate)\b", re.I)
INDIRECT = re.compile(r"[“”「」『』`\x22]|不要提交|不用提交|别提交|我不想|假如|如果我说|能否|是否|是不是|如何|怎么提交|[？?]|(?:吗|么)[。！!\s]*$|\b(?:how to|do not submit)\b", re.I)


def intent(message):
    query = message.strip()
    if not query or len(query) > 4000 or REPORTED.search(query):
        return None
    query = QUOTED.sub(" ", query).strip()
    number = NUMBER.search(query)
    if PROGRESS.search(query) or (number and (number.group(0) == query or re.search("进度|进展|status", query, re.I))):
        return "status"
    if INDIRECT.search(query) or re.search("我喜欢|我个人|我偏好|my personal preference", query, re.I):
        return None
    if CONFIRM.fullmatch(query):
        return "confirm"
    if CANCEL.fullmatch(query):
        return "cancel"
    if not SKILL.search(query):
        if FUTURE.match(query) and DIRECTIVE.search(query):
            return "detail"
        if re.fullmatch(r"[a-z][a-z0-9]*(?:[-_][a-z0-9]+)+", query, re.I):
            return "target"
        return None
    if (FUTURE.search(query) and DIRECTIVE.search(query)) or CHANGE.search(query):
        return "propose"
    # A bare Skill name may answer an immediately preceding target clarification.
    target_reply = r"(?:选(?:择)?|使用|就是|use|choose)?\s*(?:(?:skill|技能)\s+[\w-]+|[\w-]+\s+(?:skill|技能))[。.!！]?"
    return "target" if len(query) <= 120 and re.fullmatch(target_reply, query, re.I) else None


def choose_target(query, skills):
    lower = query.casefold()
    named = [s for s in skills if re.search(r"(?<![\w-])" + re.escape(s["name"].casefold())
                                            + r"(?![\w-])", lower, flags=re.ASCII)]
    if len(named) == 1:
        return named[0]
    implicit = re.search(r"这个\s*(?:skill|技能)|该技能|这项技能|this skill", lower)
    if len(skills) == 1 and implicit and not named:
        return skills[0]
    return None


def future_request(query):
    """Keep the long-term request when one message also asks for an immediate delivery."""
    future = FUTURE.search(query)
    if future and BUSINESS.search(query):
        next_task = BUSINESS.search(query, future.end())
        return query[future.start():next_task.start() if next_task else None].strip(" ，,；;。")
    return query
