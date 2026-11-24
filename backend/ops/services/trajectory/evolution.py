# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Extract bounded, attributable signals without storing conversation or tool bodies."""

import logging
import re

from contracts.errors.trajectory import QueryError
from infrastructure.trace.trajectory_reader import JSONReader
from ops.db.trajectory import evolution as queue

from .nodes import build_nodes
from .runtime import get_service

logger = logging.getLogger(__name__)
CORRECTION = re.compile(r"(?:刚才|上次|你给的|这份结果|你的回答).{0,16}(?:不对|漏了|有误|错了)|你漏了|you (?:missed|omitted)", re.I)
FILE_REQUEST = re.compile(r"(?:请|帮我|需要)(?:生成|导出|提供|创建).{0,12}(?:文件|附件|表格|xlsx|pdf)|(?:export|generate) (?:a |an )?(?:pdf|xlsx|file)", re.I)
OPERATION = re.compile(r"[A-Za-z_][A-Za-z0-9_.:-]{0,95}")


def node_ref(node):
    source = node.get("source", {})
    trace, span = source.get("trace_id", ""), source.get("span_id", "")
    if re.fullmatch(r"[0-9a-fA-F]{32}", trace) and re.fullmatch(r"[0-9a-fA-F]{16}", span):
        return f"otel:{trace}:{span}"
    return None


def observation(message, nodes=(), coverage="missing", *, unavailable=None):
    signals = []
    request = message.get("request") or ""
    if CORRECTION.search(request):
        signals.append("user_correction")
    if message.get("opinion_flag") == "N":
        signals.append("negative_feedback")
    if FILE_REQUEST.search(request) and not message.get("file_receipt"):
        signals.append("file_receipt_missing")
    failures = [n for n in nodes if n["kind"] == "tool" and n["status"] in {"failed", "interrupted"}]
    if failures:
        signals.append("tool_error")
    refs = [ref for node in failures[:16] if (ref := node_ref(node))]
    facts = {"coverage": coverage, "signals": signals, "failed_tool_count": len(failures), "node_refs": refs}
    if unavailable:
        facts["unavailable"] = unavailable
    if coverage == "complete":
        calls = [n for n in nodes if n["kind"] == "tool"]
        evidence = []
        for node in calls[:32]:
            if ref := node_ref(node):
                item = {"node": ref}
                invocation = node.get("attributes", {}).get("nexent.invocation_id")
                if isinstance(invocation, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", invocation):
                    item["invocation_id"] = invocation
                evidence.append(item)
        facts["case_outline"] = {"tool_count": len(calls), "tools": evidence}
        summaries = []
        for node in [*failures, *(n for n in calls if n["status"] not in {"failed", "interrupted"})][:16]:
            ref = node_ref(node)
            if ref is None or node["status"] not in {"completed", "failed", "interrupted"}:
                continue
            name = node.get("name") or ""
            summaries.append({"ref": ref, "kind": "tool", "status": node["status"],
                              **({"operation": name} if OPERATION.fullmatch(name) else {})})
        if summaries:
            facts["diagnosis_nodes"] = summaries
        if not signals and calls and len(calls) == len(summaries) and message.get("opinion_flag") == "Y":
            operations = [node.get("operation") for node in summaries if node["status"] == "completed"]
            if len(operations) == len(calls) and all(operations):
                facts["successful_tool_steps"] = operations
    return facts


def _track_root_execution(requests, roots):
    """Read the trusted root correlation without exposing it in public trajectory nodes."""
    for request in requests:
        if len(roots) > 1:
            yield request
            continue
        for resource in request.get("resourceSpans", []):
            for scope in resource.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    if span.get("name") != "agent.run":
                        continue
                    attrs = {item["key"]: item["value"] for item in span.get("attributes", [])}
                    if len(roots) <= 1 and attrs.get("nexent.trajectory.root", {}).get("boolValue") is True:
                        execution = attrs.get("nexent.agent_run_id", {}).get("stringValue")
                        roots.add((span["traceId"], span["spanId"], execution))
        yield request


def inspect_archive(job, message):
    service = get_service()
    budget = service.budget()
    identity = {**job, "conversation_id": str(job["conversation_id"]), "agent_id": str(job["agent_id"])}
    with service.archive.opened(identity, job["trajectory_id"], budget) as (fd, _, run):
        if (run.get("root_agent_id"), run.get("root_agent_version_no")) != (identity["agent_id"], job["agent_version_no"]):
            return observation(message, unavailable="trajectory_mismatch")
        source = run.get("source_message_id")
        if source is not None and source != str(job["source_message_id"]):
            return observation(message, unavailable="trajectory_mismatch")
        reader = JSONReader(fd, run["confirmed_bytes"], check=budget.check)
        roots = set()
        requests = _track_root_execution(reader.requests(), roots)
        nodes, _, coverage = build_nodes(requests, conversation_id=identity["conversation_id"],
                                         complete=run["capture_state"] == "ready", check=budget.check)
        if len(roots) > 1 or (not roots and source is None):
            return observation(message, unavailable="trajectory_mismatch")
        if roots:
            execution = next(iter(roots))[2]
            if execution != job["run_id"] and (execution is not None or source is None):
                return observation(message, unavailable="trajectory_mismatch")
        complete = coverage["complete"] and not coverage["capture_gap"]
        return observation(message, nodes, "complete" if complete else "partial")


class EvolutionReviewWorker:
    def __init__(self):
        self.stopping = False

    def request_stop(self):
        self.stopping = True

    def run(self, cancel_event):
        while not self.stopping and not cancel_event.is_set():
            try:
                busy = self.tick()
            except Exception as error:
                logger.warning("evolution.review.deferred exception_type=%s", type(error).__name__)
                busy = False
            cancel_event.wait(0.1 if busy else 3)

    def tick(self):
        job = queue.claim()
        if job is None:
            return False
        message = queue.messages(job)
        if message is None or job["attempts"] > 3:
            queue.finish(job, observation(message or {}))
            return True
        try:
            facts = inspect_archive(job, message)
        except QueryError as error:
            unavailable = "trajectory_expired" if error.code == "content_expired" else None
            queue.finish(job, observation(message, unavailable=unavailable),
                         retry=error.status >= 500 or error.code == "trajectory_unarchived")
        except (OSError, ValueError, TypeError, RecursionError, KeyError):
            queue.finish(job, observation(message), retry=True)
        else:
            queue.finish(job, facts)
        return True
