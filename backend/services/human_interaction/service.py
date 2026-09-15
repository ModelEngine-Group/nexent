"""Owner-scoped request lifecycle; no imports from Agent, NL2Agent or automation services."""

import json
from datetime import timedelta
from uuid import uuid4

from database.human_interaction_db import (
    ACTIVE_STATUSES,
    HumanInteractionRepository,
    utcnow,
)
from database.human_interaction_models import HumanRequest, HumanRun
from nexent.core.human_interaction.clarification import (
    ClarificationAnswer,
    format_clarification_answers,
)

from .crypto import PayloadCipher
from .models import DecisionCommand, InteractionError, SteeringCommand, digest, redact
from .persistence import validate_record

TERMINAL_STATUSES = {"COMPLETED", "FAILED", "STOPPED", "EXPIRED", "RECOVERY_REQUIRED"}


def validate_interaction_answer(payload: dict, text: str | None) -> None:
    if not text or not text.strip():
        raise InteractionError("An answer is required", 422)
    options = payload.get("options") or []
    if options and text not in options and payload.get("allow_other") is not True:
        raise InteractionError("Choose one of the registered options", 422)


def clarification_signature(payload: dict) -> str:
    """Build a stable identity for one clarification within a run."""
    if "questions" in payload:
        return digest({"questions": payload["questions"]})
    return digest({
        "question": str(payload.get("question") or "").strip(),
        "options": payload.get("options") or [],
        "allow_other": payload.get("allow_other") is not False,
    })


class HumanInteractionService:
    def __init__(self, repository: HumanInteractionRepository, cipher: PayloadCipher, wait_seconds=86400):
        self.repository = repository
        self.repository.validator = validate_record
        self.cipher = cipher
        self.wait_seconds = wait_seconds

    @staticmethod
    def require(tx):
        if tx is None:
            raise InteractionError("Human interaction run was not found", 404)
        return tx.run

    def create(self, tenant_id, user_id, conversation_id, payload, *, ready=True):
        run_id = str(uuid4())
        run = HumanRun(
            run_id=run_id, tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id,
            status="READY" if ready else "INITIALIZING", request_payload=self.cipher.seal(payload),
            plan_version=0, fence=0, pause_requested=0, event_seq=0,
        )
        with self.repository.creation(run) as tx:
            if not tx.conversation_exists():
                raise InteractionError("Conversation was not found for this owner", 404)
            if tx.active_run_exists():
                raise InteractionError("This conversation already has an active human interaction run")
            if tx.run_id_exists():
                raise InteractionError("This run identity already exists")
            tx.add(run)
        return run_id

    def initialized(self, run_id, tenant_id, user_id, *, succeeded):
        with self.repository.transaction(run_id, tenant_id, user_id) as tx:
            run = self.require(tx)
            if run.status != "INITIALIZING":
                raise InteractionError("Run initialization was interrupted")
            run.status = "READY" if succeeded else "FAILED"

    def _project_request(self, request, run_id):
        payload = self.cipher.open(request.payload)
        return {"request_id": request.request_id, "run_id": run_id, "kind": request.kind,
                "status": request.status, "version": request.version, "digest": request.digest,
                "expires_at": request.expires_at.isoformat(), "payload": redact(payload)}

    def _expire(self, tx):
        expired = False
        for request in tx.requests():
            if request.status == "PENDING" and request.expires_at <= utcnow():
                request.status = "EXPIRED"
                expired = True
        if expired:
            tx.run.status = "EXPIRED"
            tx.emit({"type": "human_run", "content": {"run_id": tx.run.run_id, "status": "EXPIRED"}})
        return expired

    def snapshot(self, run_id, tenant_id, user_id):
        with self.repository.transaction(run_id, tenant_id, user_id) as tx:
            run = self.require(tx)
            self._expire(tx)
            return {"run_id": run.run_id, "conversation_id": run.conversation_id, "status": run.status,
                    "event_seq": run.event_seq, "pause_requested": bool(run.pause_requested),
                    "attempt_active": bool(run.lock_until and run.lock_until > utcnow()),
                    "requests": [self._project_request(item, run.run_id) for item in tx.requests() if item.status == "PENDING"]}

    def request(self, tx, *, kind, slot, action_digest, payload):
        request = HumanRequest(
            request_id=str(uuid4()), run_record_id=tx.run.run_record_id, kind=kind, status="PENDING", version=1,
            slot=slot, digest=action_digest, payload=self.cipher.seal(payload),
            expires_at=utcnow() + timedelta(seconds=self.wait_seconds),
        )
        tx.add(request)
        tx.run.status = "WAITING_HUMAN"
        tx.emit({"type": "human_interaction", "content": self._project_request(request, tx.run.run_id)})
        return request

    def reusable_clarification_answer(self, tx, payload):
        """Return the latest answer for an identical clarification in this run."""
        signature = clarification_signature(payload)
        decided = sorted(
            (item for item in tx.requests() if item.kind == "CLARIFICATION" and item.status == "DECIDED"),
            key=lambda item: item.create_time,
            reverse=True,
        )
        for request in decided:
            if clarification_signature(self.cipher.open(request.payload)) != signature:
                continue
            decision = self.cipher.open(request.decision)
            if decision and decision.get("decision") == "answer":
                return self.clarification_result(request, decision)
        return None

    def clarification_budget_result(self, tx):
        """One card per run, including cancelled cards, regardless of rewording."""
        previous = [item for item in tx.requests() if item.kind == "CLARIFICATION"]
        if not previous:
            return None
        answers = []
        for item in previous:
            decision = self.cipher.open(item.decision) if item.decision else None
            if decision and decision.get("decision") == "answer":
                answers.append(self.clarification_result(item, decision))
        return json.dumps({
            "status": "clarification_limit_reached",
            "previous_answers": answers,
            "instruction": (
                "Do not ask more questions in this run, including reworded questions. "
                "Use the supplied answers and user guidance to finish the task. "
                "For nonessential gaps use explicit reasonable assumptions. If a critical fact remains "
                "unknown, explain the limitation without inventing it or opening another card."
            ),
        }, ensure_ascii=False)

    def clarification_result(self, request, decision):
        payload = self.cipher.open(request.payload)
        if "questions" in payload:
            answers = [ClarificationAnswer.model_validate(item) for item in decision["answers"]]
            return format_clarification_answers(payload, answers)
        return decision["text"]

    def decide(self, run_id, request_id, tenant_id, user_id, command: DecisionCommand):
        error = None
        with self.repository.transaction(run_id, tenant_id, user_id) as tx:
            run = self.require(tx)
            request = next((item for item in tx.requests() if item.request_id == request_id), None)
            if request is None:
                raise InteractionError("Human interaction request was not found", 404)
            command_data = command.model_dump()
            if command.answers is None:
                # Preserve idempotent retries of decisions saved before structured forms existed.
                command_data.pop("answers")
            command_digest = digest(command_data)
            if request.idempotency_key == command.idempotency_key:
                if request.decision_digest != command_digest:
                    raise InteractionError("Idempotency key was used with a different decision")
                return {"run_id": run_id, "request_id": request_id, "accepted": True}
            if self._expire(tx):
                error = InteractionError("Human interaction request has expired", 410)
            elif (request.status != "PENDING" or run.status != "WAITING_HUMAN"
                  or command.version != request.version or command.digest != request.digest):
                error = InteractionError("The request is no longer pending or its version has changed")
            else:
                allowed = {"CLARIFICATION": {"answer"}, "ACTION_APPROVAL": {"approve", "reject"},
                           "USER_STEERING": {"steer"}}[request.kind]
                if command.decision not in allowed:
                    raise InteractionError("Decision is not valid for this request kind", 422)
                if command.decision in {"answer", "steer"}:
                    payload = self.cipher.open(request.payload)
                    if request.kind == "CLARIFICATION" and "questions" in payload:
                        if command.text is not None or command.answers is None:
                            raise InteractionError("Submit structured answers for this clarification", 422)
                        try:
                            format_clarification_answers(payload, command.answers)
                        except ValueError as exc:
                            raise InteractionError(str(exc), 422) from exc
                    else:
                        if command.answers is not None:
                            raise InteractionError("This request requires a text response", 422)
                        validate_interaction_answer(payload, command.text)
                elif command.answers is not None:
                    raise InteractionError("Structured answers are only valid for clarification", 422)
                request.status = "DECIDED"
                request.idempotency_key = command.idempotency_key
                request.decision_digest = command_digest
                request.decision = self.cipher.seal(command.model_dump())
                run.status = "READY"
                tx.emit({"type": "human_decision", "content": {
                    "run_id": run_id, "request_id": request_id, "status": "DECIDED",
                }})
        if error:
            raise error
        return {"run_id": run_id, "request_id": request_id, "accepted": True}

    def steer(self, run_id, tenant_id, user_id, command: SteeringCommand):
        """Deliver each composer message once while allowing successive guidance in the same run."""
        with self.repository.transaction(run_id, tenant_id, user_id) as tx:
            run = self.require(tx)
            fingerprint = digest(command.model_dump())
            for item in tx.requests():
                if item.kind != "USER_STEERING" or self.cipher.open(item.payload).get("source") != "composer":
                    continue
                if item.idempotency_key == command.message_id:
                    if item.decision_digest != fingerprint:
                        raise InteractionError("Idempotency key was used with different guidance")
                    return {"accepted": True, "run_id": run_id, "request_id": item.request_id}
            saved = self.cipher.open(run.request_payload)
            if run.status not in {"READY", "RUNNING", "WAITING_HUMAN"} or saved.get("steering_closed"):
                raise InteractionError("This run has finished accepting guidance; keep the message queued")
            if any(item.status == "PENDING" and item.expires_at <= utcnow() for item in tx.requests()):
                raise InteractionError("The pending interaction has expired", 410)
            for item in tx.requests():
                if item.status == "PENDING":
                    item.status = "CANCELLED"
            tx.flush()
            request = HumanRequest(
                request_id=str(uuid4()), run_record_id=run.run_record_id, kind="USER_STEERING", status="DECIDED", version=1,
                slot=f"composer:{command.message_id}", digest=fingerprint,
                payload=self.cipher.seal({"source": "composer"}),
                decision=self.cipher.seal({"decision": "steer", "text": command.text}),
                idempotency_key=command.message_id, decision_digest=fingerprint,
                expires_at=utcnow() + timedelta(seconds=self.wait_seconds),
            )
            tx.add(request)
            run.pause_requested = 0
            if run.status == "WAITING_HUMAN":
                run.status = "READY"
            tx.emit({"type": "human_decision", "content": {
                "run_id": run_id, "request_id": request.request_id, "status": "DECIDED",
            }})
            return {"accepted": True, "run_id": run_id, "request_id": request.request_id}

    def _request_steering(self, tx):
        for request in tx.requests():
            if request.status == "PENDING":
                request.status = "CANCELLED"
        tx.flush()
        tx.run.pause_requested = 0
        self.request(tx, kind="USER_STEERING", slot=f"steering:{tx.run.event_seq}",
                     action_digest=digest([tx.run.run_id, tx.run.event_seq, "steering"]),
                     payload={"question": "请提供新的意见或约束，继续执行当前任务。", "options": []})

    def control(self, run_id, tenant_id, user_id, action):
        with self.repository.transaction(run_id, tenant_id, user_id) as tx:
            run = self.require(tx)
            if action == "terminate":
                if run.status not in {"COMPLETED", "FAILED", "STOPPED", "EXPIRED"}:
                    run.status = "STOPPED"
                    run.pause_requested = 0
                    for request in tx.requests():
                        if request.status == "PENDING":
                            request.status = "CANCELLED"
            elif action == "pause":
                if run.status not in ACTIVE_STATUSES or run.status == "RECOVERY_REQUIRED":
                    raise InteractionError("This run cannot be paused")
                pending = [item for item in tx.requests() if item.status == "PENDING"]
                if run.status == "WAITING_HUMAN":
                    if not any(item.kind == "USER_STEERING" for item in pending):
                        self._request_steering(tx)
                else:
                    run.pause_requested = 1
            else:
                raise InteractionError("Unsupported control action", 422)
            tx.emit({"type": "human_run", "content": {
                "run_id": run_id, "status": run.status, "pause_requested": bool(run.pause_requested),
            }})
        return self.snapshot(run_id, tenant_id, user_id)

    def expire_waiting(self):
        for run_id in self.repository.waiting_ids():
            with self.repository.transaction(run_id) as tx:
                if tx is not None:
                    self._expire(tx)
