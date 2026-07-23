"""Safely soft-delete explicitly selected legacy NL2AGENT cutover data."""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import func, select, text, update


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "sdk"))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from agents.nl2agent_workflow import WORKFLOW_SCHEMA_VERSION  # noqa: E402
from backend.scripts.check_nl2agent_cutover import (  # noqa: E402
    evaluate_session_rows,
)
from database.client import db_client  # noqa: E402
from database.db_models import (  # noqa: E402
    AgentInfo,
    ConversationMessage,
    ConversationMessageUnit,
    ConversationRecord,
    ConversationSourceImage,
    ConversationSourceSearch,
    Nl2AgentInstallationOperation,
    Nl2AgentSession,
)


APPLY_CONFIRMATION = "SOFT_DELETE_LEGACY_NL2AGENT"
DEFAULT_ACTOR = "nl2agent_cutover"
MAX_TARGETS = 100


class CutoverCleanupError(RuntimeError):
    """Raised when cleanup targets fail a safety precondition."""


@dataclass(frozen=True)
class CleanupTarget:
    session_id: int
    conversation_id: int
    draft_agent_id: int
    status: str
    workflow_schema_version: int
    reasons: tuple[str, ...]


CONVERSATION_MODELS = (
    ("installation_operations", Nl2AgentInstallationOperation),
    ("conversation_sources_search", ConversationSourceSearch),
    ("conversation_sources_image", ConversationSourceImage),
    ("conversation_message_units", ConversationMessageUnit),
    ("conversation_messages", ConversationMessage),
    ("conversations", ConversationRecord),
)


def _positive_id(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("IDs must be integers") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("IDs must be positive integers")
    return parsed


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or soft-delete explicitly selected legacy NL2AGENT Sessions "
            "and their internal Builder Conversations."
        )
    )
    parser.add_argument(
        "--session-ids",
        nargs="+",
        required=True,
        type=_positive_id,
        metavar="ID",
        help="Exact legacy Session IDs reported by the cutover check.",
    )
    parser.add_argument(
        "--conversation-ids",
        nargs="+",
        required=True,
        type=_positive_id,
        metavar="ID",
        help="Exact Builder Conversation IDs reported by the cutover check.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the soft-delete transaction. The default is a read-only preview.",
    )
    parser.add_argument(
        "--confirm",
        help=f"Required with --apply; must equal {APPLY_CONFIRMATION!r}.",
    )
    parser.add_argument(
        "--actor",
        default=DEFAULT_ACTOR,
        help="Audit value written to updated_by (default: nl2agent_cutover).",
    )
    return parser.parse_args(argv)


def _normalize_expected_ids(
    values: Iterable[int], *, field_name: str
) -> tuple[int, ...]:
    normalized = tuple(int(value) for value in values)
    if not normalized:
        raise CutoverCleanupError(f"{field_name} cannot be empty.")
    if len(normalized) > MAX_TARGETS:
        raise CutoverCleanupError(
            f"{field_name} exceeds the maximum cleanup batch size of {MAX_TARGETS}."
        )
    if len(set(normalized)) != len(normalized):
        raise CutoverCleanupError(f"{field_name} contains duplicate IDs.")
    return tuple(sorted(normalized))


def _normalize_target_ids(
    session_ids: Iterable[int], conversation_ids: Iterable[int]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    normalized_session_ids = _normalize_expected_ids(
        session_ids, field_name="session_ids"
    )
    normalized_conversation_ids = _normalize_expected_ids(
        conversation_ids, field_name="conversation_ids"
    )
    if len(normalized_session_ids) != len(normalized_conversation_ids):
        raise CutoverCleanupError(
            "Session and Conversation target counts must be identical."
        )
    return normalized_session_ids, normalized_conversation_ids


def load_session_rows(
    db_session, session_ids: Sequence[int], *, lock: bool
) -> list[Mapping[str, Any]]:
    statement = select(
        Nl2AgentSession.session_id,
        Nl2AgentSession.conversation_id,
        Nl2AgentSession.draft_agent_id,
        Nl2AgentSession.status,
        Nl2AgentSession.workflow_schema_version,
        Nl2AgentSession.session_catalogs,
        Nl2AgentSession.workflow_state,
    ).where(
        Nl2AgentSession.session_id.in_(session_ids),
        Nl2AgentSession.delete_flag.is_distinct_from("Y"),
    )
    if lock:
        statement = statement.with_for_update(of=Nl2AgentSession)
    return db_session.execute(statement).mappings().all()


def load_conversation_rows(
    db_session, conversation_ids: Sequence[int], *, lock: bool
) -> list[dict[str, Any]]:
    statement = select(
        ConversationRecord.conversation_id,
        ConversationRecord.conversation_title,
        ConversationRecord.agent_id,
    ).where(
        ConversationRecord.conversation_id.in_(conversation_ids),
        ConversationRecord.delete_flag.is_distinct_from("Y"),
    )
    if lock:
        statement = statement.with_for_update(of=ConversationRecord)
    conversations = [
        dict(row) for row in db_session.execute(statement).mappings().all()
    ]
    agent_ids = sorted(
        {
            int(row["agent_id"])
            for row in conversations
            if row.get("agent_id") is not None
        }
    )
    agent_names: dict[int, str] = {}
    if agent_ids:
        agent_rows = (
            db_session.execute(
                select(AgentInfo.agent_id, AgentInfo.name).where(
                    AgentInfo.agent_id.in_(agent_ids),
                    AgentInfo.version_no == 0,
                    AgentInfo.delete_flag.is_distinct_from("Y"),
                )
            )
            .mappings()
            .all()
        )
        agent_names = {
            int(row["agent_id"]): str(row.get("name") or "") for row in agent_rows
        }
    for row in conversations:
        agent_id = row.get("agent_id")
        row["agent_name"] = agent_names.get(int(agent_id)) if agent_id else None
    return conversations


def _cleanup_reasons(row: Mapping[str, Any]) -> tuple[str, ...]:
    reasons = {
        issue.code
        for issue in evaluate_session_rows([row])
        if issue.subject == "session"
    }
    workflow_state = row.get("workflow_state")
    state_schema_version = (
        workflow_state.get("schema_version")
        if isinstance(workflow_state, Mapping)
        else None
    )
    if (
        row.get("workflow_schema_version") != WORKFLOW_SCHEMA_VERSION
        or state_schema_version != WORKFLOW_SCHEMA_VERSION
    ):
        reasons.add("legacy_schema")
    return tuple(sorted(reasons))


def validate_cleanup_targets(
    session_rows: Iterable[Mapping[str, Any]],
    conversation_rows: Iterable[Mapping[str, Any]],
    *,
    expected_session_ids: Iterable[int],
    expected_conversation_ids: Iterable[int],
) -> list[CleanupTarget]:
    sessions = [dict(row) for row in session_rows]
    conversations = [dict(row) for row in conversation_rows]
    session_ids, conversation_ids = _normalize_target_ids(
        expected_session_ids,
        expected_conversation_ids,
    )

    actual_session_ids = tuple(sorted(int(row["session_id"]) for row in sessions))
    actual_conversation_ids = tuple(
        sorted(int(row["conversation_id"]) for row in conversations)
    )
    if actual_session_ids != session_ids:
        raise CutoverCleanupError(
            f"Session targets changed: expected={session_ids}, actual={actual_session_ids}."
        )
    if actual_conversation_ids != conversation_ids:
        raise CutoverCleanupError(
            "Conversation targets changed: "
            f"expected={conversation_ids}, actual={actual_conversation_ids}."
        )

    bound_conversation_ids = tuple(
        sorted(int(row["conversation_id"]) for row in sessions)
    )
    if bound_conversation_ids != conversation_ids:
        raise CutoverCleanupError(
            "Selected Sessions are not bound to the exact selected Conversations."
        )

    for row in conversations:
        title = str(row.get("conversation_title") or "")
        agent_name = str(row.get("agent_name") or "")
        if not title.startswith("NL2AGENT - ") and agent_name != "nl2agent":
            raise CutoverCleanupError(
                f"Conversation {int(row['conversation_id'])} is not an internal "
                "NL2AGENT Builder Conversation."
            )

    targets: list[CleanupTarget] = []
    for row in sorted(sessions, key=lambda item: int(item["session_id"])):
        reasons = _cleanup_reasons(row)
        if not reasons:
            raise CutoverCleanupError(
                f"Session {int(row['session_id'])} is a healthy v3 Session and "
                "cannot be cleaned by this script."
            )
        targets.append(
            CleanupTarget(
                session_id=int(row["session_id"]),
                conversation_id=int(row["conversation_id"]),
                draft_agent_id=int(row["draft_agent_id"]),
                status=str(row.get("status") or ""),
                workflow_schema_version=int(row.get("workflow_schema_version") or 0),
                reasons=reasons,
            )
        )
    return targets


def count_cleanup_rows(db_session, targets: Sequence[CleanupTarget]) -> dict[str, int]:
    conversation_ids = [target.conversation_id for target in targets]
    counts: dict[str, int] = {}
    for name, model in CONVERSATION_MODELS:
        counts[name] = int(
            db_session.execute(
                select(func.count())
                .select_from(model)
                .where(
                    model.conversation_id.in_(conversation_ids),
                    model.delete_flag.is_distinct_from("Y"),
                )
            ).scalar_one()
        )
    counts["sessions"] = int(
        db_session.execute(
            select(func.count())
            .select_from(Nl2AgentSession)
            .where(
                Nl2AgentSession.session_id.in_(
                    [target.session_id for target in targets]
                ),
                Nl2AgentSession.delete_flag.is_distinct_from("Y"),
            )
        ).scalar_one()
    )
    return counts


def soft_delete_cleanup_targets(
    db_session,
    targets: Sequence[CleanupTarget],
    *,
    actor: str,
) -> dict[str, int]:
    conversation_ids = [target.conversation_id for target in targets]
    values = {
        "delete_flag": "Y",
        "updated_by": actor,
        "update_time": func.now(),
    }
    counts: dict[str, int] = {}
    for name, model in CONVERSATION_MODELS:
        result = db_session.execute(
            update(model)
            .where(
                model.conversation_id.in_(conversation_ids),
                model.delete_flag.is_distinct_from("Y"),
            )
            .values(**values)
        )
        counts[name] = int(result.rowcount or 0)

    result = db_session.execute(
        update(Nl2AgentSession)
        .where(
            Nl2AgentSession.session_id.in_([target.session_id for target in targets]),
            Nl2AgentSession.delete_flag.is_distinct_from("Y"),
        )
        .values(**values)
    )
    counts["sessions"] = int(result.rowcount or 0)
    expected_roots = len(targets)
    if (
        counts["conversations"] != expected_roots
        or counts["sessions"] != expected_roots
    ):
        raise CutoverCleanupError(
            "Cleanup root counts changed while applying the transaction."
        )
    return counts


def _print_preview(targets: Sequence[CleanupTarget], counts: Mapping[str, int]) -> None:
    print("NL2AGENT cutover cleanup preview; no rows were changed:")
    for target in targets:
        print(
            f"- session {target.session_id} -> conversation "
            f"{target.conversation_id}; draft={target.draft_agent_id}; "
            f"status={target.status}; schema={target.workflow_schema_version}; "
            f"reasons={','.join(target.reasons)}"
        )
    print("Rows that would be soft-deleted:")
    for name, count in counts.items():
        print(f"- {name}: {count}")
    print("Draft Agents and their resource bindings are preserved.")
    print(
        "To apply, stop NL2AGENT writes, back up PostgreSQL, and rerun with "
        f"--apply --confirm {APPLY_CONFIRMATION}."
    )


def _validate_actor(actor: str) -> str:
    normalized = str(actor or "").strip()
    if not normalized or len(normalized) > 100:
        raise CutoverCleanupError("actor must contain 1 to 100 characters.")
    return normalized


def _rollback_best_effort(db_session) -> None:
    if db_session is None:
        return
    try:
        db_session.rollback()
    except Exception:
        pass


def _close_best_effort(db_session) -> None:
    if db_session is None:
        return
    try:
        db_session.close()
    except Exception:
        pass


def run_cleanup(args: argparse.Namespace) -> int:
    if args.apply and args.confirm != APPLY_CONFIRMATION:
        print(
            f"NL2AGENT cutover cleanup blocked: --confirm must equal "
            f"{APPLY_CONFIRMATION!r} when --apply is used.",
            file=sys.stderr,
        )
        return 1

    try:
        actor = _validate_actor(args.actor)
    except CutoverCleanupError as exc:
        print(f"NL2AGENT cutover cleanup blocked: {exc}", file=sys.stderr)
        return 1

    db_session = None
    try:
        session_ids, conversation_ids = _normalize_target_ids(
            args.session_ids,
            args.conversation_ids,
        )
        db_session = db_client.session_maker()
        if args.apply:
            db_session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        else:
            db_session.execute(text("SET TRANSACTION READ ONLY"))
        session_rows = load_session_rows(db_session, session_ids, lock=args.apply)
        conversation_rows = load_conversation_rows(
            db_session, conversation_ids, lock=args.apply
        )
        targets = validate_cleanup_targets(
            session_rows,
            conversation_rows,
            expected_session_ids=session_ids,
            expected_conversation_ids=conversation_ids,
        )
        counts = count_cleanup_rows(db_session, targets)
        if not args.apply:
            _print_preview(targets, counts)
            db_session.rollback()
            return 0

        deleted_counts = soft_delete_cleanup_targets(
            db_session,
            targets,
            actor=actor,
        )
        db_session.commit()
        print("NL2AGENT cutover cleanup committed:")
        for name, count in deleted_counts.items():
            print(f"- {name}: {count}")
        print("Draft Agents and their resource bindings were preserved.")
        print("Run backend/scripts/check_nl2agent_cutover.py before deployment.")
        return 0
    except CutoverCleanupError as exc:
        _rollback_best_effort(db_session)
        print(f"NL2AGENT cutover cleanup blocked: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        _rollback_best_effort(db_session)
        print(
            "NL2AGENT cutover cleanup could not update PostgreSQL: "
            f"{type(exc).__name__}",
            file=sys.stderr,
        )
        return 2
    finally:
        _close_best_effort(db_session)


def main(argv: Sequence[str] | None = None) -> int:
    return run_cleanup(parse_arguments(argv))


if __name__ == "__main__":
    raise SystemExit(main())
