# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Record first-party Skill requests inside the confirmed chat-message transaction."""

from contextlib import nullcontext

from sqlalchemy import select, text

from infrastructure.rdb.account_access import get_user_role_by_tenant, query_group_ids_by_user_in_tenant
from infrastructure.rdb.skill_execution_records import SkillInfo, SkillInstance, bound_skill_predicates
from infrastructure.workbench_skill_execution import can_view_skill
from management.utils.suggestion_intent import BEHAVIOR, BUSINESS, CHANGE, FUTURE, NUMBER, SKILL, choose_target, future_request, intent


def _visible_skills(session, scope, binding):
    owner, tenant = scope["owner"], scope["tenant"]

    def same_session():
        return nullcontext(session)

    roles = get_user_role_by_tenant(owner, tenant, session_factory=same_session)
    if not roles:
        return []
    groups = set(query_group_ids_by_user_in_tenant(owner, tenant, session_factory=same_session))
    query = select(SkillInfo.skill_id, SkillInfo.skill_name.label("name"), SkillInfo.created_by,
                   SkillInfo.source, SkillInfo.group_ids, SkillInfo.ingroup_permission).join(
        SkillInstance, SkillInstance.skill_id == SkillInfo.skill_id).where(
        *bound_skill_predicates(scope["agent"], scope["version"], tenant),
        SkillInstance.skill_instance_id.in_(binding["instances"]))
    return [dict(skill) for skill in session.execute(query).mappings()
            if can_view_skill(skill=skill, user_id=owner, user_role=roles, user_group_ids=groups)]


def _status_reply(session, scope, query, reply):
    number = NUMBER.search(query)
    match = "s.suggestion_id=:sid" if number else "s.conversation_id=:cid"
    rows = session.execute(text(f"""
        SELECT s.suggestion_id, s.status, s.experiment_id,
            (SELECT count(*) FROM nexent.evolution_trial_t t WHERE t.experiment_id=s.experiment_id
                AND t.status IN ('running','pending')) AS active,
            (SELECT cancelled FROM nexent.evolution_experiment_t e WHERE e.experiment_id=s.experiment_id
                AND e.tenant_id=s.tenant_id) AS stopped
        FROM nexent.evolution_suggestion_t s
        JOIN nexent.conversation_record_t c ON c.conversation_id=s.conversation_id AND c.created_by=s.submitter_id
        WHERE s.tenant_id=:tenant AND s.submitter_id=:owner AND {match} AND c.delete_flag='N' AND s.status='submitted'
        ORDER BY s.suggestion_id DESC LIMIT 2
    """), {**scope, "sid": int(number[1]) if number else None}).mappings().all()
    if not rows:
        return reply("未找到你提交的这条建议。", "I couldn't find a suggestion you submitted matching this request.")
    if len(rows) > 1:
        ids = "、".join(f"S-{r['suggestion_id']}" for r in rows)
        return reply(f"你提交了多条建议，请指定编号，例如 {ids}。", f"Please specify a suggestion ID, for example {ids}.")
    sid = rows[0]["suggestion_id"]
    if rows[0]["experiment_id"] is not None:
        if rows[0]["stopped"]:
            return reply(f"建议 S-{sid} 的对比评测已取消。", f"The evaluation for S-{sid} was cancelled.")
        if rows[0]["active"]:
            return reply(f"建议 S-{sid} 正在进行对比评测。", f"The evaluation for S-{sid} is in progress.")
        return reply(f"建议 S-{sid} 的对比评测已结束，等待评审结果。", f"The evaluation for S-{sid} has finished and awaits review.")
    return reply(f"建议 S-{sid} 已登记，等待维护人评审。", f"Suggestion S-{sid} is waiting for maintainer review.")


def record_intent(session, turn, source, user_turn):
    binding = user_turn["suggestion_scope"]
    query = user_turn["query"].strip()
    language = binding["language"]
    scope = dict(tenant=turn.tenant_id, owner=turn.user_id, cid=turn.reference.conversation_id,
                 source=source, agent=binding["agent"], version=binding["version"])

    def reply(zh, en, *, business=False):
        return {"message": en if language == "en" else zh, "business": business}

    # A retry on the same persisted user message reuses its actual receipt, including clarification.
    previous = session.execute(text("""
        SELECT evolution_reply FROM nexent.conversation_run_admission_t WHERE conversation_id=:cid
            AND created_by=:owner AND tenant_id=:tenant AND evolution_reply->>'source' = CAST(:source AS text)
            AND delete_flag='N' AND evolution_reply IS NOT NULL LIMIT 1
    """), scope).scalar()
    if previous is not None:
        return previous
    action = intent(query)
    if action == "status":
        return _status_reply(session, scope, query, reply)

    # Only the next original user message can answer the clarification in this branch.
    pending = session.execute(text("""
        SELECT s.* FROM nexent.evolution_suggestion_t s
        JOIN nexent.conversation_message_t prev ON prev.message_id=s.last_message_id AND prev.conversation_id=s.conversation_id
        JOIN nexent.conversation_message_t cur ON cur.message_id=:source AND cur.conversation_id=s.conversation_id
        WHERE s.tenant_id=:tenant AND s.submitter_id=:owner AND s.conversation_id=:cid AND s.agent_id=:agent AND s.version_no=:version
          AND s.status='clarifying' AND prev.message_index+2=cur.message_index
          AND prev.delete_flag='N' AND cur.delete_flag='N' ORDER BY s.suggestion_id DESC LIMIT 1 FOR UPDATE OF s
    """), scope).mappings().first()
    if pending and action == "cancel":
        session.execute(text("""UPDATE nexent.evolution_suggestion_t SET status='cancelled',last_message_id=:source,
            update_time=now() WHERE suggestion_id=:sid"""), {**scope, "sid": pending["suggestion_id"]})
        return reply("已取消这条改进建议。", "The suggestion was cancelled.",
                     business=query.rstrip("。.!！ ") in {"只改这次", "仅改本次", "just this time"})
    if action != "propose" and (not pending or action not in {"target", "confirm", "detail"}):
        return {"business": True, "message": ""}
    skills = _visible_skills(session, scope, binding)
    mixed = bool(BUSINESS.search(query))
    if mixed and not FUTURE.search(query) and not pending:
        return {"business": True, "message": ""}
    if not skills:
        return reply("当前智能体没有你可提出改进建议的已启用 Skill。",
                     "This agent has no enabled Skill available to you for suggestions.", business=mixed)
    continuing = pending and action in {"target", "confirm", "detail"}
    expected = pending["expected_behavior"] if continuing and action != "detail" else future_request(query)
    target = choose_target(query, skills)
    if continuing and not target:
        target = next((s for s in skills if s["skill_id"] == pending["skill_id"]), None)
    specific = bool(BEHAVIOR.search(expected))
    requested_edit = SKILL.search(expected) and CHANGE.search(expected) and specific and not mixed
    permanent = bool(FUTURE.search(expected) or action == "confirm" or "提交" in expected or requested_edit)
    status = "submitted" if target and permanent and specific else "clarifying"
    fields = {**scope, "skill": target["skill_id"] if target else None, "expected": expected, "status": status}
    if continuing:
        sid = pending["suggestion_id"]
        session.execute(text("""UPDATE nexent.evolution_suggestion_t SET skill_id=:skill,status=:status,expected_behavior=:expected,
            last_message_id=:source,update_time=now() WHERE suggestion_id=:sid"""), {**fields, "sid":sid})
    else:
        sid = session.scalar(text("""INSERT INTO nexent.evolution_suggestion_t
            (tenant_id,submitter_id,conversation_id,source_message_id,agent_id,version_no,skill_id,
             expected_behavior,status,last_message_id)
            VALUES (:tenant,:owner,:cid,:source,:agent,:version,:skill,:expected,:status,:source)
            RETURNING suggestion_id"""), fields)
    if not target:
        names = "、".join(s["name"] for s in skills[:12])
        return reply(f"请说明要改哪个 Skill，可回复“Skill 名称”。当前可选：{names}。",
                     f"Which Skill should change? Reply with 'Skill' and its name. Available: {names}.", business=mixed)
    if not permanent:
        return reply("只改这次结果，还是希望这个 Skill 以后都这样做？可回复“只改这次”或“确认提交”。",
                     "Is this just for this result, or a change to the Skill? Reply 'just this time' or 'submit it'.",
                     business=mixed)
    if not specific:
        return reply("希望这个 Skill 以后具体怎样处理？可以用“以后请……”说明期望。",
                     "What should the Skill do differently? Start with 'In future, please ...'.", business=mixed)
    return reply(f"已登记建议 S-{sid}（{target['name']}）。\n{expected}",
                 f"Filed S-{sid} for {target['name']}.\n{expected}", business=mixed)
