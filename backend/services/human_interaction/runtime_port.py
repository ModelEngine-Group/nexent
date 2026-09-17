"""Fenced tool dispatch adapter. Approval and STARTED are consumed under one run lock."""

import threading
import time
from contextlib import contextmanager
from datetime import timezone

from database.human_interaction_db import utcnow
from database.human_interaction_models import HumanExecution
from nexent.core.human_interaction.contracts import (
    AttemptSuspended,
    RecoveryRequired,
    RunTerminated,
)

from .models import digest, redact


class RuntimeInteractionPort:
    def __init__(self, service, identity, owner_id, authorize, allowed_tools=(), *, live_resume=False, stop_event=None):
        self.service = service
        self.repository = service.repository
        self.cipher = service.cipher
        self.run_id = identity["run_id"]
        self.tenant_id = identity["tenant_id"]
        self.user_id = identity["user_id"]
        self.fence = identity["fence"]
        self.owner_id = owner_id
        self.authorize = authorize
        self.allowed_tools = frozenset(allowed_tools)
        self.live_resume = live_resume
        self.stop_event = stop_event
        # Thread-safe shared buffer for already-processed observer chunks
        # (model_output_thinking / parse ...). The async consumer loop in
        # application.py calls ``add_chunk`` after every processed chunk; the
        # worker thread calls ``flush_chunks_until_idle`` right before emitting
        # any HITL event so chunks always land in DB before the corresponding
        # human_interaction / human_execution row.
        self._chunk_buffer: list[str] = []
        self._chunk_buffer_lock = threading.Lock()
        # Set by the async consumer (application.py's _flush_if_due) right
        # before it hands buffered chunks to run_blocking(emit_chunks). The
        # worker's flush_chunks_until_idle uses this to distinguish "buffer
        # empty because async just handed chunks to the DB thread" from
        # "buffer empty because async is truly idle".
        self._emit_in_flight = threading.Event()
        with self.transaction() as tx:
            self.checkpoint = self.cipher.open(tx.run.checkpoint)
            self.request_payload = self.cipher.open(tx.run.request_payload)

    # --- Shared chunk buffer (async-producer ↔ worker-consumer) --------

    def add_chunk(self, chunk: str) -> None:
        """Append a processed chunk from the async consumer to the shared buffer."""
        with self._chunk_buffer_lock:
            self._chunk_buffer.append(chunk)

    def take_chunks(self) -> list[str]:
        """Atomically drain the shared buffer for immediate persistence."""
        with self._chunk_buffer_lock:
            chunks = self._chunk_buffer
            self._chunk_buffer = []
        return chunks

    def peek_chunks(self) -> int:
        """Return the number of buffered chunks without draining them.

        Used by the async consumer loop to decide whether to hand chunks
        to the DB thread — the buffer stays intact so a concurrent drain
        never sees a transiently-empty buffer.
        """
        with self._chunk_buffer_lock:
            return len(self._chunk_buffer)

    def begin_emit(self) -> None:
        """Signal that the async consumer is handing chunks to run_blocking(emit_chunks)."""
        self._emit_in_flight.set()

    def end_emit(self) -> None:
        """Signal that the async consumer's run_blocking(emit_chunks) has returned."""
        self._emit_in_flight.clear()

    def flush_chunks_until_idle(self, *, max_wait_ms: int = 500, settle_ms: int = 20) -> None:
        """Wait for the async consumer to drain the observer queue, then persist.

        **Worker-thread only.** The worker is the sole producer of observer
        messages. Once ``model()`` returns and the worker enters ask_user, no
        more tokens are pushed — every remaining chunk in the observer queue
        will eventually reach the shared buffer via ``port.add_chunk`` (async
        loop). This method polls the shared buffer: if it stays empty for
        ``settle_ms`` AND there is no in-flight emit (pending DB transaction
        from the async consumer) the async loop has fully consumed the
        observer. We run a final flush before returning.

        ``max_wait_ms`` is a **hard upper bound** measured from function entry
        — it is NOT reset when new chunks appear, so the worker cannot be
        blocked indefinitely.
        """
        hard_deadline = time.monotonic() + max_wait_ms / 1000.0
        idle_since: float | None = None

        while True:
            now = time.monotonic()
            if now >= hard_deadline:
                break

            chunks = self.take_chunks()
            if chunks:
                try:
                    self.emit_chunks(chunks)
                except Exception:
                    # Never lose drained chunks: put them back so a later
                    # flush (or the caller's recovery path) can retry.
                    for chunk in chunks:
                        self.add_chunk(chunk)
                    raise
                idle_since = None
            elif self._emit_in_flight.is_set():
                # Buffer is empty but async is still handing chunks to the
                # DB thread (emit_chunks in run_blocking). Treat as non-idle
                # so settle_ms doesn't fire on a transient empty window.
                idle_since = None
            elif idle_since is None:
                idle_since = now
            elif now - idle_since >= settle_ms / 1000.0:
                # Buffer has been empty long enough and nothing is in-flight
                # — observer must be drained.
                break

            time.sleep(min(settle_ms / 1000.0, hard_deadline - now))

    # -------------------------------------------------------------------

    @contextmanager
    def transaction(self, *, receipt=False):
        with self.repository.transaction(self.run_id, self.tenant_id, self.user_id) as tx:
            if (tx is None or tx.run.fence != self.fence or tx.run.lock_owner != self.owner_id
                    or tx.run.lock_until is None or tx.run.lock_until <= utcnow()):
                raise RunTerminated("Execution lease is no longer valid")
            if not receipt and tx.run.status not in {"RUNNING", "READY"}:
                raise RunTerminated("Run no longer permits execution")
            yield tx

    def bind_catalog(self, catalog):
        value = digest(catalog)
        with self.transaction() as tx:
            if tx.run.catalog_digest is not None and tx.run.catalog_digest != value:
                raise RecoveryRequired("Agent definition, model, tool configuration or credentials changed")
            tx.run.catalog_digest = value

    def context_snapshot(self, items):
        with self.transaction() as tx:
            saved = self.cipher.open(tx.run.request_payload)
            if "context_items" not in saved:
                saved["context_items"] = items
                tx.run.request_payload = self.cipher.seal(saved)
            return saved["context_items"]

    def bind_executor(self, identity):
        value = digest(identity)
        with self.transaction() as tx:
            if tx.run.executor_digest is not None and tx.run.executor_digest != value:
                raise RecoveryRequired("Executor or registered tool implementation changed")
            tx.run.executor_digest = value

    def save_checkpoint(self, checkpoint):
        sealed = self.cipher.seal(checkpoint)
        with self.transaction() as tx:
            tx.run.checkpoint = sealed
        self.checkpoint = checkpoint

    def boundary(self, checkpoint):
        self.authorize()
        suspended = False
        feedback = None
        # Wait for async to drain observer queue, then flush so model_output_thinking /
        # parse rows precede the human_run status transition below.
        self.flush_chunks_until_idle()
        with self.transaction() as tx:
            tx.run.checkpoint = self.cipher.seal(checkpoint)
            if tx.run.pause_requested:
                self.service._request_steering(tx)
                suspended = True
            else:
                pending = sorted((
                    request for request in tx.requests()
                    if request.kind == "USER_STEERING" and request.status == "DECIDED"
                    and request.request_id not in checkpoint.get("steering_ids", [])
                ), key=lambda request: (request.create_time, request.request_id))
                if pending:
                    completed = []
                    for execution in tx.executions():
                        if execution.status == "SUCCEEDED":
                            completed.append({"tool": execution.tool, "result": self.cipher.open(execution.result)})
                        elif execution.status == "PREPARED":
                            execution.status = "REJECTED"
                            execution.result = self.cipher.seal({"status": "not_executed", "reason": "user_steering"})
                    texts = [self.cipher.open(request.decision)["text"] for request in pending]
                    # Consume all accepted input at this boundary before making another model/tool call.
                    content = texts[0] if len(texts) == 1 else (
                        "Successive user guidance in submission order; later corrections take precedence:\n"
                        + "\n\n".join(f"{index}. {value}" for index, value in enumerate(texts, 1))
                    )
                    feedback = {"text": content, "request_id": pending[0].request_id,
                                "request_ids": [request.request_id for request in pending],
                                "completed_actions": str(redact(completed))}
        if suspended:
            if not self.live_resume:
                raise AttemptSuspended()
            self._wait_until_ready()
            return self.boundary(checkpoint)
        return feedback

    def close_steering(self, checkpoint):
        """Serialize finalization against newly submitted guidance under the run lock."""
        with self.transaction() as tx:
            if tx.run.pause_requested or any(
                item.kind == "USER_STEERING" and item.status == "DECIDED"
                and item.request_id not in checkpoint.get("steering_ids", []) for item in tx.requests()
            ):
                return False
            payload = self.cipher.open(tx.run.request_payload)
            payload["steering_closed"] = True
            tx.run.request_payload = self.cipher.seal(payload)
            return True

    def _wait_until_ready(self):
        """Park this worker while retaining the current Python continuation."""
        next_authorization_check = 0.0
        while True:
            if self.stop_event is not None and self.stop_event.is_set():
                raise RunTerminated("The managed execution was cancelled")
            now = time.monotonic()
            if now >= next_authorization_check:
                self.authorize()
                next_authorization_check = now + 5.0
            with self.repository.transaction(self.run_id, self.tenant_id, self.user_id) as tx:
                if (tx is None or tx.run.fence != self.fence or tx.run.lock_owner != self.owner_id
                        or tx.run.lock_until is None or tx.run.lock_until <= utcnow()):
                    raise RunTerminated("Execution lease is no longer valid")
                self.service._expire(tx)
                if tx.run.status == "READY":
                    # Wait for async to drain observer queue, then flush so
                    # any lingering batched chunks precede the human_run row.
                    self.flush_chunks_until_idle()
                    tx.run.status = "RUNNING"
                    tx.emit({"type": "human_run", "content": {
                        "run_id": self.run_id, "status": "RUNNING",
                    }})
                    return
                if tx.run.status != "WAITING_HUMAN":
                    raise RunTerminated("Run no longer permits live continuation")
            if self.stop_event is not None:
                self.stop_event.wait(0.2)
            else:
                time.sleep(0.2)

    def dispatch(self, slot, tool, arguments, *, interaction=None):
        self.authorize()
        suspended = False
        steering_requested = False
        outcome = None
        # Wait for async to drain observer queue, then flush BEFORE opening the
        # HITL transaction so that model_output_thinking / parse rows land in DB
        # with lower seq numbers than any subsequent human_interaction row.
        self.flush_chunks_until_idle()
        with self.transaction() as tx:
            if tx.run.pause_requested:
                self.service._request_steering(tx)
                suspended = True
                steering_requested = True
            else:
                action_digest = self.cipher.digest([self.run_id, self.tenant_id, self.user_id, slot, tool,
                                        arguments, tx.run.catalog_digest, "conservative-v1"])
                execution = tx.execution(slot)
                if execution is not None:
                    if execution.digest != action_digest:
                        raise RecoveryRequired("Arguments or tool identity changed at a persisted call slot")
                    if execution.status in {"SUCCEEDED", "REJECTED"}:
                        return {"status": "replay", "result": self.cipher.open(execution.result)}
                    if execution.status in {"STARTED", "UNKNOWN"}:
                        raise RecoveryRequired("An uncertain external effect must be reconciled")
                else:
                    execution = HumanExecution(run_record_id=tx.run.run_record_id, slot=slot, tool=tool, digest=action_digest,
                                               arguments=self.cipher.seal(arguments), status="PREPARED")
                    tx.add(execution)
                request = next((item for item in tx.requests()
                                if item.slot == slot and item.digest == action_digest), None)
                if request is not None:
                    if request.status == "CANCELLED" and any(
                            item.kind == "USER_STEERING" and item.status == "DECIDED"
                            for item in tx.requests()):
                        return {"status": "steered"}
                    if request.expires_at <= utcnow() or request.status != "DECIDED":
                        raise RunTerminated("No valid unexpired human decision is available")
                    decision = self.cipher.open(request.decision)
                    if decision["decision"] in {"answer", "reject"}:
                        if decision["decision"] == "answer":
                            result = self.service.clarification_result(request, decision)
                        else:
                            result = {
                                "status": "not_executed", "reason": "human_rejected", "feedback": decision.get("text"),
                            }
                        execution.status = "SUCCEEDED" if decision["decision"] == "answer" else "REJECTED"
                        execution.result = self.cipher.seal(result)
                        outcome = {"status": "replay", "result": result}
                elif interaction is not None:
                    answer = self.service.reusable_clarification_answer(tx, interaction)
                    if answer is None:
                        answer = self.service.clarification_budget_result(tx)
                    if answer is not None:
                        execution.status = "SUCCEEDED"
                        execution.result = self.cipher.seal(answer)
                        outcome = {"status": "replay", "result": answer}
                        tx.emit({"type": "human_execution", "content": {
                            "run_id": self.run_id, "slot": slot, "tool": tool, "status": "SUCCEEDED",
                        }})
                    else:
                        self.service.request(tx, kind="CLARIFICATION", slot=slot,
                                             action_digest=action_digest, payload=interaction)
                        suspended = True
                elif tool not in self.allowed_tools:
                    payload = {"tool": tool, "arguments": redact(arguments),
                               "question": "请审核即将执行的工具和参数。批准仅对此次动作有效。"}
                    self.service.request(tx, kind="ACTION_APPROVAL", slot=slot,
                                         action_digest=action_digest, payload=payload)
                    suspended = True
                if not suspended and outcome is None:
                    # Exact saved bytes, never the caller's mutable dictionary.
                    execution.status = "STARTED"
                    outcome = {"status": "execute", "arguments": self.cipher.open(execution.arguments)}
                    tx.emit({"type": "human_execution", "content": {
                        "run_id": self.run_id, "slot": slot, "tool": tool, "status": "STARTED",
                    }})
        if suspended:
            if not self.live_resume:
                raise AttemptSuspended()
            self._wait_until_ready()
            if steering_requested:
                return {"status": "steered"}
            return self.dispatch(slot, tool, arguments, interaction=interaction)
        return outcome

    def receipt(self, slot, result, *, uncertain=False):
        # Wait for async to drain observer queue, then flush before recording
        # execution outcome so the DB event order is chunks → human_execution.
        self.flush_chunks_until_idle()
        with self.transaction(receipt=True) as tx:
            execution = tx.execution(slot)
            if execution is None or execution.status != "STARTED":
                raise RecoveryRequired("Execution receipt does not match a started action")
            execution.status = "UNKNOWN" if uncertain else "SUCCEEDED"
            execution.result = None if uncertain else self.cipher.seal(result)
            tx.emit({"type": "human_execution", "content": {
                "run_id": self.run_id, "slot": slot, "tool": execution.tool, "status": execution.status,
            }})

    def save_plan(self, plan):
        with self.transaction() as tx:
            if self.cipher.open(tx.run.plan) != plan:
                tx.run.plan = self.cipher.seal(plan)
                tx.run.plan_version += 1

    def load_plan(self):
        with self.transaction() as tx:
            return self.cipher.open(tx.run.plan)

    def emit_chunk(self, chunk):
        self.emit_chunks([chunk])

    def emit_chunks(self, chunks):
        with self.transaction(receipt=True) as tx:
            for chunk in chunks:
                tx.emit({"chunk_cipher": self.cipher.seal(chunk)})

    def visible_guidance(self):
        """Return accepted composer input for the normal stream/history presentation path."""
        with self.transaction(receipt=True) as tx:
            requests = sorted(tx.requests(), key=lambda item: (item.create_time, item.request_id))
            return [
                {"request_id": item.request_id, "text": self.cipher.open(item.decision)["text"],
                 "created_at": item.create_time.replace(tzinfo=timezone.utc).isoformat()}
                for item in requests if item.kind == "USER_STEERING" and item.status == "DECIDED"
                and self.cipher.open(item.payload).get("source") == "composer"
            ]

    def finish(self, outcome):
        # Wait for async to drain observer queue, then flush remaining batched
        # chunks before the final human_run status row. Chunk-flush failures
        # must NOT prevent the terminal row from being written — wrap in
        # try/except so we always attempt the status transaction.
        try:
            self.flush_chunks_until_idle()
        except Exception:
            pass
        with self.transaction(receipt=True) as tx:
            if tx.run.status in {"STOPPED", "EXPIRED"}:
                return
            if tx.run.status == "READY" and outcome == "waiting_human":
                return
            tx.run.status = outcome.upper()
            if tx.run.status != "WAITING_HUMAN":
                for request in tx.requests():
                    if request.status == "PENDING":
                        request.status = "CANCELLED"
            tx.emit({"type": "human_run", "content": {"run_id": self.run_id, "status": tx.run.status}})
