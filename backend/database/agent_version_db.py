import logging
from typing import List, Optional, Tuple
from sqlalchemy import or_, select, insert, update, delete, func

from database.client import get_db_session, as_dict
from database.db_models import AgentInfo, ToolInstance, AgentRelation, AgentVersion, SkillInstance
from consts.const import ASSET_OWNER_TENANT_ID

logger = logging.getLogger("agent_version_db")

# Version source types
SOURCE_TYPE_NORMAL = "NORMAL"
SOURCE_TYPE_ROLLBACK = "ROLLBACK"

# Version statuses
STATUS_RELEASED = "RELEASED"
STATUS_DISABLED = "DISABLED"
STATUS_ARCHIVED = "ARCHIVED"


def search_version_by_version_no(
    agent_id: int,
    tenant_id: str,
    version_no: int,
) -> Optional[dict]:
    """
    Search version metadata by version_no
    """
    with get_db_session() as session:
        version = session.query(AgentVersion).filter(
            AgentVersion.agent_id == agent_id,
            AgentVersion.version_no == version_no,
            AgentVersion.delete_flag == 'N',
        ).first()
        return as_dict(version) if version else None


def search_version_by_id(
    version_id: int,
    tenant_id: str,
) -> Optional[dict]:
    """
    Search version metadata by id
    """
    with get_db_session() as session:
        version = session.query(AgentVersion).filter(
            AgentVersion.id == version_id,
            AgentVersion.tenant_id == tenant_id,
            AgentVersion.delete_flag == 'N',
        ).first()
        return as_dict(version) if version else None

def query_version_list(
    agent_id: int,
    tenant_id: str,
) -> List[dict]:
    """
    Query version list for an agent
    """
    with get_db_session() as session:
        versions = session.query(AgentVersion).filter(
            AgentVersion.agent_id == agent_id,
            AgentVersion.tenant_id == tenant_id,
            AgentVersion.delete_flag == 'N',
        ).order_by(AgentVersion.version_no.desc()).all()

        return [as_dict(v) for v in versions]


def query_current_version_no(
    agent_id: int,
    tenant_id: str,
) -> Optional[int]:
    """
    Query current published version_no from agent draft (version_no=0)
    """
    with get_db_session() as session:
        agent = session.query(AgentInfo).filter(
            AgentInfo.agent_id == agent_id,
            or_(
                AgentInfo.tenant_id == tenant_id,
                AgentInfo.tenant_id == ASSET_OWNER_TENANT_ID,
            ),
            AgentInfo.version_no == 0,
            AgentInfo.delete_flag == 'N',
        ).first()
        return agent.current_version_no if agent else None


def query_agent_snapshot(
    agent_id: int,
    tenant_id: str,
    version_no: int,
) -> Tuple[Optional[dict], List[dict], List[dict]]:
    """
    Query agent snapshot data (agent_info, tools, relations) for a specific version
    """
    with get_db_session() as session:
        # Query agent info snapshot
        agent = session.query(AgentInfo).filter(
            AgentInfo.agent_id == agent_id,
            or_(
                AgentInfo.tenant_id == tenant_id,
                AgentInfo.tenant_id == ASSET_OWNER_TENANT_ID,
            ),
            AgentInfo.version_no == version_no,
            AgentInfo.delete_flag == 'N',
        ).first()

        if agent is not None:
            tenant_id = agent.tenant_id

        # Query tool instances snapshot
        tools = session.query(ToolInstance).filter(
            ToolInstance.agent_id == agent_id,
            ToolInstance.tenant_id == tenant_id,
            ToolInstance.version_no == version_no,
            ToolInstance.delete_flag == 'N',
        ).all()

        # Query relations snapshot
        relations = session.query(AgentRelation).filter(
            AgentRelation.parent_agent_id == agent_id,
            AgentRelation.tenant_id == tenant_id,
            AgentRelation.version_no == version_no,
            AgentRelation.delete_flag == 'N',
        ).all()

        agent_dict = as_dict(agent) if agent else None
        tools_list = [as_dict(t) for t in tools]
        relations_list = [as_dict(r) for r in relations]

        return agent_dict, tools_list, relations_list


def query_agent_draft(
    agent_id: int,
    tenant_id: str,
) -> Tuple[Optional[dict], List[dict], List[dict]]:
    """
    Query agent draft data (version_no=0)
    """
    return query_agent_snapshot(agent_id, tenant_id, version_no=0)


def insert_version(
    version_data: dict,
) -> int:
    """
    Insert a new version metadata record
    Returns: version id
    """
    with get_db_session() as session:
        result = session.execute(
            insert(AgentVersion).values(**version_data).returning(AgentVersion.id)
        )
        return result.scalar_one()


def update_version_status(
    agent_id: int,
    tenant_id: str,
    version_no: int,
    status: str,
    updated_by: str,
) -> int:
    """
    Update version status
    Returns: number of rows affected
    """
    with get_db_session() as session:
        result = session.execute(
            update(AgentVersion)
            .where(
                AgentVersion.agent_id == agent_id,
                AgentVersion.tenant_id == tenant_id,
                AgentVersion.version_no == version_no,
                AgentVersion.delete_flag == 'N',
            )
            .values(status=status, updated_by=updated_by, update_time=func.now())
        )
        return result.rowcount


def update_version(
    agent_id: int,
    tenant_id: str,
    version_no: int,
    version_name: Optional[str] = None,
    release_note: Optional[str] = None,
    updated_by: Optional[str] = None,
) -> int:
    """
    Update version metadata (version_name and release_note)
    Returns: number of rows affected
    """
    # Build update values dynamically
    update_values = {}
    if version_name is not None:
        update_values["version_name"] = version_name
    if release_note is not None:
        update_values["release_note"] = release_note
    if updated_by is not None:
        update_values["updated_by"] = updated_by

    if not update_values:
        return 0

    update_values["update_time"] = func.now()

    with get_db_session() as session:
        result = session.execute(
            update(AgentVersion)
            .where(
                AgentVersion.agent_id == agent_id,
                AgentVersion.tenant_id == tenant_id,
                AgentVersion.version_no == version_no,
                AgentVersion.delete_flag == 'N',
            )
            .values(**update_values)
        )
        return result.rowcount


def update_agent_current_version(
    agent_id: int,
    tenant_id: str,
    current_version_no: int,
) -> int:
    """
    Update agent draft's current_version_no
    Returns: number of rows affected
    """
    with get_db_session() as session:
        result = session.execute(
            update(AgentInfo)
            .where(
                AgentInfo.agent_id == agent_id,
                AgentInfo.tenant_id == tenant_id,
                AgentInfo.version_no == 0,
                AgentInfo.delete_flag == 'N',
            )
            .values(current_version_no=current_version_no)
        )
        return result.rowcount


def insert_agent_snapshot(
    agent_data: dict,
) -> None:
    """
    Insert agent snapshot (copy from draft to new version)
    """
    with get_db_session() as session:
        session.execute(insert(AgentInfo).values(**agent_data))


def insert_tool_snapshot(
    tool_data: dict,
) -> None:
    """
    Insert tool instance snapshot
    """
    with get_db_session() as session:
        session.execute(insert(ToolInstance).values(**tool_data))


def insert_relation_snapshot(
    relation_data: dict,
) -> None:
    """
    Insert relation snapshot
    """
    with get_db_session() as session:
        session.execute(insert(AgentRelation).values(**relation_data))


def update_agent_snapshot(
    agent_id: int,
    tenant_id: str,
    version_no: int,
    agent_data: dict,
) -> int:
    """
    Update agent snapshot data (used for rollback restore)
    Returns: number of rows affected
    """
    with get_db_session() as session:
        result = session.execute(
            update(AgentInfo)
            .where(
                AgentInfo.agent_id == agent_id,
                AgentInfo.tenant_id == tenant_id,
                AgentInfo.version_no == version_no,
                AgentInfo.delete_flag == 'N',
            )
            .values(**agent_data)
        )
        return result.rowcount


def delete_agent_snapshot(
    agent_id: int,
    tenant_id: str,
    version_no: int,
    deleted_by: str,
) -> int:
    """
    Soft delete agent snapshot for a version
    Returns: number of rows affected
    """
    with get_db_session() as session:
        result = session.execute(
            update(AgentInfo)
            .where(
                AgentInfo.agent_id == agent_id,
                AgentInfo.tenant_id == tenant_id,
                AgentInfo.version_no == version_no,
                AgentInfo.delete_flag == 'N',
            )
            .values(delete_flag='Y', updated_by=deleted_by, update_time=func.now())
        )
        return result.rowcount


def delete_tool_snapshot(
    agent_id: int,
    tenant_id: str,
    version_no: int,
    deleted_by: str = None,
) -> int:
    """
    Delete all tool snapshots for a version (used before restoring from rollback)
    Returns: number of rows affected
    """
    with get_db_session() as session:
        values = {'delete_flag': 'Y'}
        if deleted_by:
            values['updated_by'] = deleted_by
            values['update_time'] = func.now()
        result = session.execute(
            update(ToolInstance)
            .where(
                ToolInstance.agent_id == agent_id,
                ToolInstance.tenant_id == tenant_id,
                ToolInstance.version_no == version_no,
                ToolInstance.delete_flag == 'N',
            )
            .values(**values)
        )
        return result.rowcount


def delete_relation_snapshot(
    agent_id: int,
    tenant_id: str,
    version_no: int,
    deleted_by: str = None,
) -> int:
    """
    Delete all relation snapshots for a version (used before restoring from rollback)
    Returns: number of rows affected
    """
    with get_db_session() as session:
        values = {'delete_flag': 'Y'}
        if deleted_by:
            values['updated_by'] = deleted_by
            values['update_time'] = func.now()
        result = session.execute(
            update(AgentRelation)
            .where(
                AgentRelation.parent_agent_id == agent_id,
                AgentRelation.tenant_id == tenant_id,
                AgentRelation.version_no == version_no,
                AgentRelation.delete_flag == 'N',
            )
            .values(**values)
        )
        return result.rowcount


# ============== Restore Draft from Version Snapshot ==============
# Used by rollback: copies a published version's data back into draft (version_no=0)

def restore_agent_draft(
    agent_id: int,
    tenant_id: str,
    target_version_no: int,
    target_agent_snapshot: dict,
    target_tool_snapshots: List[dict],
    target_relation_snapshots: List[dict],
    target_skill_snapshots: List[dict],
) -> None:
    """
    Atomically restore the agent draft (version_no=0) from a published version snapshot.
    This replaces all draft data with the target version's data.

    Operations in a single transaction:
    1. Hard-delete current draft tools, relations, skills (version_no=0) to free up PK slots
    2. Update agent draft record with target version's agent data
    3. Bulk-insert tools copied from target version with version_no=0
    4. Bulk-insert relations copied from target version with version_no=0
    5. Bulk-insert skills copied from target version with version_no=0
    6. Update current_version_no to point to target_version_no
    """

    with get_db_session() as session:
        # 1. Hard-delete current draft tools to free up (tool_instance_id, version_no=0) keys
        session.execute(
            delete(ToolInstance).where(
                ToolInstance.agent_id == agent_id,
                ToolInstance.tenant_id == tenant_id,
                ToolInstance.version_no == 0,
            )
        )

        # 2. Hard-delete current draft relations
        session.execute(
            delete(AgentRelation).where(
                AgentRelation.parent_agent_id == agent_id,
                AgentRelation.tenant_id == tenant_id,
                AgentRelation.version_no == 0,
            )
        )

        # 3. Hard-delete current draft skills
        session.execute(
            delete(SkillInstance).where(
                SkillInstance.agent_id == agent_id,
                SkillInstance.tenant_id == tenant_id,
                SkillInstance.version_no == 0,
            )
        )

        # 4. Update agent draft record with target version's data
        draft_values = {k: v for k, v in target_agent_snapshot.items()
                        if k not in ('version_no', 'current_version_no')}
        draft_values['current_version_no'] = target_version_no
        session.execute(
            update(AgentInfo)
            .where(
                AgentInfo.agent_id == agent_id,
                AgentInfo.tenant_id == tenant_id,
                AgentInfo.version_no == 0,
                AgentInfo.delete_flag == 'N',
            )
            .values(**draft_values)
        )

        # 5. Bulk-insert tools from target version (with version_no=0)
        for tool in target_tool_snapshots:
            tool_copy = {k: v for k, v in tool.items()
                         if k not in ('version_no',)}
            tool_copy['version_no'] = 0
            session.execute(insert(ToolInstance).values(**tool_copy))

        # 6. Bulk-insert relations from target version (with version_no=0)
        for rel in target_relation_snapshots:
            rel_copy = {k: v for k, v in rel.items()
                        if k not in ('version_no',)}
            rel_copy['version_no'] = 0
            session.execute(insert(AgentRelation).values(**rel_copy))

        # 7. Bulk-insert skills from target version (with version_no=0)
        for skill in target_skill_snapshots:
            skill_copy = {k: v for k, v in skill.items()
                          if k not in ('version_no',)}
            skill_copy['version_no'] = 0
            session.execute(insert(SkillInstance).values(**skill_copy))


def delete_skill_snapshot(
    agent_id: int,
    tenant_id: str,
    version_no: int,
    deleted_by: str = None,
) -> int:
    """
    Delete all skill instance snapshots for a version (used when deleting a version)
    Returns: number of rows affected
    """
    with get_db_session() as session:
        values = {'delete_flag': 'Y'}
        if deleted_by:
            values['updated_by'] = deleted_by
            values['update_time'] = func.now()
        result = session.execute(
            update(SkillInstance)
            .where(
                SkillInstance.agent_id == agent_id,
                SkillInstance.tenant_id == tenant_id,
                SkillInstance.version_no == version_no,
                SkillInstance.delete_flag == 'N',
            )
            .values(**values)
        )
        return result.rowcount


def get_next_version_no(
    agent_id: int,
    tenant_id: str,
) -> int:
    """
    Calculate the next version number for an agent
    """
    with get_db_session() as session:
        max_version = session.query(func.max(AgentInfo.version_no)).filter(
            AgentInfo.agent_id == agent_id,
            AgentInfo.tenant_id == tenant_id,
            AgentInfo.delete_flag == 'N',
        ).scalar()
        return (max_version or 0) + 1


def delete_version(
    agent_id: int,
    tenant_id: str,
    version_no: int,
    deleted_by: str,
) -> int:
    """
    Soft delete a version by setting delete_flag='Y'
    Returns: number of rows affected
    """
    with get_db_session() as session:
        logger.info(f"Attempting to delete version: agent_id={agent_id}, tenant_id={tenant_id}, version_no={version_no}, deleted_by={deleted_by}")
        result = session.execute(
            update(AgentVersion)
            .where(
                AgentVersion.agent_id == agent_id,
                AgentVersion.tenant_id == tenant_id,
                AgentVersion.version_no == version_no,
                AgentVersion.delete_flag == 'N',
            )
            .values(delete_flag='Y', updated_by=deleted_by, update_time=func.now())
        )
        rows_affected = result.rowcount
        logger.info(f"Delete version result: rows_affected={rows_affected} for agent_id={agent_id}, tenant_id={tenant_id}, version_no={version_no}")
        return rows_affected


# ============== Skill Instance Snapshot Functions ==============

def query_skill_instances_snapshot(
    agent_id: int,
    tenant_id: str,
    version_no: int,
) -> List[dict]:
    """
    Query skill instances snapshot for a specific version.
    """
    with get_db_session() as session:
        skills = session.query(SkillInstance).filter(
            SkillInstance.agent_id == agent_id,
            SkillInstance.tenant_id == tenant_id,
            SkillInstance.version_no == version_no,
            SkillInstance.delete_flag == 'N',
        ).all()
        return [as_dict(s) for s in skills]


def insert_skill_snapshot(
    skill_data: dict,
) -> None:
    """
    Insert skill instance snapshot.
    """
    with get_db_session() as session:
        session.execute(insert(SkillInstance).values(**skill_data))