"""Fail closed when legacy NL2AGENT state would make the v3 cutover unsafe."""

import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from sqlalchemy import and_, or_, select, text


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "sdk"))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from agents.nl2agent_workflow import WORKFLOW_SCHEMA_VERSION  # noqa: E402
from database.client import db_client  # noqa: E402
from database.db_models import AgentInfo, ConversationRecord, Nl2AgentSession  # noqa: E402
from utils.nl2agent_catalog_snapshot import catalog_identity  # noqa: E402


LEGACY_WORKFLOW_KEYS = frozenset({"card_delivery", "online_installations"})


@dataclass(frozen=True)
class CutoverIssue:
    code: str
    subject: str
    identifier: int
    detail: str


@contextmanager
def _read_only_db_session():
    """Open a PostgreSQL-enforced read-only transaction without generic error logging."""
    session = db_client.session_maker()
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        yield session
    finally:
        try:
            session.rollback()
        finally:
            session.close()


def _legacy_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        found = {str(key) for key in value if str(key) in LEGACY_WORKFLOW_KEYS}
        for item in value.values():
            found.update(_legacy_keys(item))
        return found
    if isinstance(value, (list, tuple)):
        found: set[str] = set()
        for item in value:
            found.update(_legacy_keys(item))
        return found
    return set()


def evaluate_session_rows(rows: Iterable[Mapping[str, Any]]) -> list[CutoverIssue]:
    """Validate session rows without exposing their catalog or workflow content."""
    issues: list[CutoverIssue] = []
    for row in rows:
        session_id = int(row["session_id"])
        workflow_state = row.get("workflow_state")
        state_version = (
            workflow_state.get("schema_version")
            if isinstance(workflow_state, Mapping)
            else None
        )
        active_schema_valid = (
            row.get("workflow_schema_version") == WORKFLOW_SCHEMA_VERSION
            and state_version == WORKFLOW_SCHEMA_VERSION
        )
        if row.get("status") == "active" and not active_schema_valid:
            issues.append(
                CutoverIssue(
                    code="active_schema_mismatch",
                    subject="session",
                    identifier=session_id,
                    detail=f"active Session is not workflow schema v{WORKFLOW_SCHEMA_VERSION}",
                )
            )
        if row.get("status") == "active" and active_schema_valid:
            try:
                catalog_identity(row.get("session_catalogs"))
            except (KeyError, TypeError, ValueError):
                issues.append(
                    CutoverIssue(
                        code="active_catalog_snapshot_invalid",
                        subject="session",
                        identifier=session_id,
                        detail="active Session lacks a valid immutable catalog snapshot",
                    )
                )
        legacy_keys = sorted(_legacy_keys(workflow_state))
        if legacy_keys:
            issues.append(
                CutoverIssue(
                    code="legacy_workflow_state",
                    subject="session",
                    identifier=session_id,
                    detail="legacy workflow keys remain: " + ", ".join(legacy_keys),
                )
            )
    return issues


def evaluate_builder_conversation_rows(
    rows: Iterable[Mapping[str, Any]],
) -> list[CutoverIssue]:
    """Reject Builder conversations that are not owned by a v3 Session."""
    return [
        CutoverIssue(
            code="legacy_builder_conversation",
            subject="conversation",
            identifier=int(row["conversation_id"]),
            detail="Builder Conversation is not bound to a non-deleted v3 Session",
        )
        for row in rows
        if row.get("v3_session_id") is None
    ]


def inspect_nl2agent_cutover(db_session) -> list[CutoverIssue]:
    """Run read-only cutover queries against one database session."""
    session_rows = (
        db_session.execute(
            select(
                Nl2AgentSession.session_id,
                Nl2AgentSession.status,
                Nl2AgentSession.workflow_schema_version,
                Nl2AgentSession.session_catalogs,
                Nl2AgentSession.workflow_state,
            ).where(Nl2AgentSession.delete_flag != "Y")
        )
        .mappings()
        .all()
    )

    v3_session = Nl2AgentSession.__table__.alias("v3_session")
    builder_rows = (
        db_session.execute(
            select(
                ConversationRecord.conversation_id,
                v3_session.c.session_id.label("v3_session_id"),
            )
            .outerjoin(
                AgentInfo,
                and_(
                    AgentInfo.agent_id == ConversationRecord.agent_id,
                    AgentInfo.version_no == 0,
                    AgentInfo.delete_flag != "Y",
                ),
            )
            .outerjoin(
                v3_session,
                and_(
                    v3_session.c.conversation_id == ConversationRecord.conversation_id,
                    v3_session.c.workflow_schema_version == WORKFLOW_SCHEMA_VERSION,
                    v3_session.c.delete_flag != "Y",
                ),
            )
            .where(
                ConversationRecord.delete_flag != "Y",
                or_(
                    ConversationRecord.conversation_title.like("NL2AGENT - %"),
                    AgentInfo.name == "nl2agent",
                ),
            )
        )
        .mappings()
        .all()
    )
    return [
        *evaluate_session_rows(session_rows),
        *evaluate_builder_conversation_rows(builder_rows),
    ]


def main() -> int:
    try:
        with _read_only_db_session() as session:
            issues = inspect_nl2agent_cutover(session)
    except Exception as exc:
        print(
            f"NL2AGENT cutover check could not inspect PostgreSQL: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 2

    if issues:
        print(f"NL2AGENT cutover blocked by {len(issues)} issue(s):", file=sys.stderr)
        for issue in issues:
            print(
                f"- {issue.code}: {issue.subject} {issue.identifier}: {issue.detail}",
                file=sys.stderr,
            )
        return 1
    print(
        f"NL2AGENT cutover check passed for workflow schema v{WORKFLOW_SCHEMA_VERSION}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
