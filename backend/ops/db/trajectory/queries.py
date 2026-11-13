# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PG-only list projection; no filesystem dependencies are permitted here."""

from datetime import UTC

from sqlalchemy import bindparam, text

# isort: split
from contracts.errors.trajectory import QueryError
from management.db.trajectory.models import TrajectoryStatistics
from management.db.trajectory.repository import scope_uuid
from ops.db.trajectory.catalog import _session

READABLE = "('success','error','partial')"
BASE = """
SELECT e.*, c.created_by AS user_id, c.conversation_title,
       u.user_email AS user_name, ut.tenant_id
FROM nexent.trajectory_execution_t e
JOIN nexent.conversation_record_t c ON c.conversation_id=e.conversation_id AND c.delete_flag='N'
JOIN nexent.user_tenant_t ut ON ut.user_id=c.created_by AND ut.delete_flag='N'
JOIN nexent.user_account_t u ON u.user_id=c.created_by AND u.delete_flag='N'
WHERE e.delete_flag='N' AND ut.tenant_id IN :tenants
"""


def strict_sum(column):
    return f"CASE WHEN count(*) FILTER (WHERE status IN {READABLE}) = count({column}) FILTER (WHERE status IN {READABLE}) THEN sum({column}) FILTER (WHERE status IN {READABLE}) END"


def _statement(sql):
    return text(sql).bindparams(bindparam("tenants", expanding=True))


def _iso(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


class ExecutionCatalog:
    def list_records(self, tenants, filters, *, view, limit, sort_by, sort_order):
        where, params = [], {"tenants": tenants, "limit": limit + 1}
        for name, column in (
            ("target_user_id", "user_id"),
            ("conversation_id", "conversation_id"),
        ):
            if filters.get(name):
                where.append(f"b.{column} = :{name}")
                params[name] = (
                    int(filters[name]) if name == "conversation_id" else filters[name]
                )
        query = filters.get("id_query", "").strip()
        if query:
            where.append(
                "CAST(b.conversation_id AS varchar) LIKE :id_query ESCAPE '\\'"
            )
            params["id_query"] = (
                "%"
                + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                + "%"
            )
        predicates = []
        for name, expression in (
            ("agent_id", "b.agent_id = :agent_id"),
            ("model", "b.models @> ARRAY[:model]::varchar(100)[]"),
            ("started_from", "b.started_at >= :started_from"),
            ("started_to", "b.started_at <= :started_to"),
        ):
            if filters.get(name) is not None:
                predicates.append(expression)
                params[name] = (
                    int(filters[name]) if name == "agent_id" else filters[name]
                )
        match = " AND ".join(predicates) or "TRUE"
        conditions = " AND ".join(where) or "TRUE"
        status = ""
        if filters.get("status"):
            status = (
                " AND l.status = :status"
                if view == "conversation"
                else " AND b.status = :status"
            )
            params["status"] = filters["status"]
        scoped = f"SELECT b.* FROM ({BASE}) b WHERE {conditions}"
        if view == "conversation":
            sql = f"""WITH base AS ({scoped}),
            latest AS (SELECT DISTINCT ON (conversation_id) * FROM base ORDER BY conversation_id,turn_no DESC,trajectory_id),
            grouped AS (
              SELECT b.conversation_id,
                {strict_sum("duration_ms")} AS duration_ms,
                {strict_sum("input_tokens")} AS input_tokens,
                {strict_sum("output_tokens")} AS output_tokens,
                {strict_sum("total_tokens")} AS total_tokens,
                max(turn_no) AS execution_count,
                count(*) FILTER (WHERE turn_no>0 AND ({match})) AS matching_execution_count,
                bool_or({match}) AS matches,
                jsonb_agg(jsonb_build_object('id',trajectory_id,'status',status,'turn',turn_no,'matches',({match}))) AS runs
              FROM base b WHERE {conditions} GROUP BY b.conversation_id
            )
            SELECT l.*, g.duration_ms AS cumulative_duration_ms,
              g.input_tokens AS cumulative_input_tokens,g.output_tokens AS cumulative_output_tokens,
              g.total_tokens AS cumulative_total_tokens,g.execution_count,g.matching_execution_count,g.runs,
              ARRAY(SELECT DISTINCT unnest(models) FROM base WHERE conversation_id=l.conversation_id) AS all_models
            FROM latest l JOIN grouped g USING(conversation_id) WHERE g.matches {status}
            """
            sort_column = {
                "started_at": "l.started_at",
                "duration_ms": "g.duration_ms",
                "total_tokens": "g.total_tokens",
            }[sort_by]
        else:
            sql = f"""WITH base AS ({BASE}) SELECT b.*,
            jsonb_build_array(jsonb_build_object('id',trajectory_id,'status',status,'turn',turn_no,'matches',TRUE)) AS runs
            FROM base b WHERE {conditions} AND ({match}) {status}"""
            sort_column = "b." + sort_by
        sql += f" ORDER BY {sort_column} {'DESC' if sort_order == 'desc' else 'ASC'} NULLS LAST, conversation_id, trajectory_id LIMIT :limit"
        with _session() as session:
            rows = session.execute(_statement(sql), params).mappings().all()
        if len(rows) > limit:
            raise QueryError("candidate_budget_exceeded", 503, retry_after=2)
        return [self._dto(dict(row), view) for row in rows]

    @staticmethod
    def _dto(row, view):
        status = row["status"]
        known = status in {"success", "error", "partial"}
        prefix = "cumulative_" if view == "conversation" else ""
        tokens = {
            key: row.get(prefix + key + "_tokens")
            for key in ("input", "output", "total")
        }
        # PostgreSQL SUM(BIGINT) yields NUMERIC/Decimal; JSON token counts stay integers.
        tokens = {key: int(value) if value is not None else None for key, value in tokens.items()}
        usage = {**tokens, "complete": all(v is not None for v in tokens.values())}
        result = {
            "tenant_id": row["tenant_id"],
            "tenant_name": None,
            "user_id": row["user_id"],
            "user_name": row["user_name"] or row["user_id"],
            "conversation_id": str(row["conversation_id"]),
            "conversation_title": row["conversation_title"],
            "trajectory_id": str(row["trajectory_id"]) if known else None,
            "root_agent_id": str(row["agent_id"])
            if row["agent_id"] is not None
            else None,
            "root_agent_name": None,
            "root_agent_version_no": row["agent_version_no"],
            "root_agent_version_name": None,
            "models": sorted(row.get("all_models", row["models"])),
            "status": status if status in {"success", "error"} else None,
            "business_status": None,
            "availability": "available" if status in {"success", "error"} else status,
            "started_at": _iso(row["started_at"]),
            "finished_at": _iso(row["finished_at"]),
            "duration_ms": row.get("cumulative_duration_ms", row["duration_ms"]),
            "usage": usage,
            "coverage": {"complete": False, "reasons": [], "scope": view},
            "cleanup_reason": None,
            "_runs": row["runs"],
        }
        if view == "conversation":
            result.update(
                round_count=row["execution_count"],
                execution_count=row["execution_count"],
                matching_execution_count=row["matching_execution_count"],
            )
        return result

    def validate(self, tenants, members):
        """Check frozen identities in one PG query without adding new executions."""
        expected = {
            r["id"]: (m["tenant_id"], m["user_id"], r["status"])
            for m in members
            for r in m["_runs"]
        }
        if not expected:
            return
        base = BASE.replace("e.delete_flag='N'", "(e.delete_flag='N' OR e.turn_no=0)")
        stmt = _statement(
            f"WITH base AS ({base}) SELECT trajectory_id,tenant_id,user_id,status FROM base WHERE trajectory_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        with _session() as session:
            rows = session.execute(
                stmt, {"tenants": tenants, "ids": list(expected)}
            ).all()
        current = {str(r[0]): (r[1], r[2], r[3]) for r in rows}
        if current.keys() != expected.keys() or any(
            current[k][:2] != value[:2]
            or current[k][2] in {"expired", "corrupt"}
            and value[2] not in {"expired", "corrupt"}
            for k, value in expected.items()
        ):
            raise QueryError("snapshot_reset", 409)

    def statistics(self, tenants, *, global_scope=False):
        kind, identity = (
            ("global", "global") if global_scope else ("tenant", tenants[0])
        )
        with _session() as session:
            row = session.get(TrajectoryStatistics, scope_uuid(kind, identity))
            data = (
                {
                    c.name: getattr(row, c.name)
                    for c in TrajectoryStatistics.__table__.columns
                }
                if row
                else {}
            )

        def metric(prefix):
            return {
                **{f"p{p}_ms": data.get(f"{prefix}_p{p}_ms") for p in (50, 90, 99)},
                "sample_count": data.get(prefix + "_sample_count", 0),
            }

        return {
            "scope_type": kind,
            "scope_id": identity,
            "computed_at": _iso(data.get("computed_at")),
            "source_revision": data.get("source_revision", 0),
            "computed_revision": data.get("computed_revision", 0),
            "complete": data.get("complete", False),
            "conversation_count": data.get("conversation_count"),
            "execution_count": data.get("execution_count"),
            "duration": {**metric("duration"), "mean_ms": data.get("duration_mean_ms")},
            "conversation_duration": metric("conversation_duration"),
            "ttft": metric("ttft"),
            "coverage": {
                "complete": data.get("complete", False),
                "execution_count": data.get("execution_count", 0),
            },
        }

    def facets(self, tenants, filters, facet, search, after, limit):
        column = {
            "agents": "agent_id",
            "conversations": "conversation_id",
            "models": "model",
        }[facet]
        params = {
            "tenants": tenants,
            "limit": limit + 1,
            "search": "%"
            + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%",
        }
        conditions = ["TRUE"]
        if filters.get("target_user_id"):
            conditions.append("user_id=:owner")
            params["owner"] = filters["target_user_id"]
        if filters.get("agent_id"):
            conditions.append("agent_id=:agent")
            params["agent"] = int(filters["agent_id"])
        extra = ", unnest(models) AS model" if facet == "models" else ""
        label = (
            "max(conversation_title)"
            if facet == "conversations"
            else f"CAST({column} AS varchar)"
        )
        sql = f"WITH base AS ({BASE}) SELECT tenant_id,CAST({column} AS varchar) AS id,{label} AS name FROM base {extra} WHERE {' AND '.join(conditions)} AND {column} IS NOT NULL GROUP BY tenant_id,{column}"
        if facet == "agents":
            from contracts.constants.constants import ASSET_OWNER_TENANT_ID

            params["shared"] = ASSET_OWNER_TENANT_ID
            sql = f"""SELECT tenant_id,id,(SELECT coalesce(a.display_name,a.name)
              FROM nexent.agent_info_t a WHERE a.agent_id=CAST(options.id AS integer)
              AND a.version_no=0 AND a.delete_flag='N' AND a.tenant_id IN (options.tenant_id,:shared)
              ORDER BY CASE WHEN a.tenant_id=options.tenant_id THEN 0 ELSE 1 END LIMIT 1) AS name
              FROM ({sql}) options"""
        sql = f"SELECT * FROM ({sql}) options WHERE (id ILIKE :search ESCAPE '\\' OR name ILIKE :search ESCAPE '\\')"
        if after:
            sql = f"SELECT * FROM ({sql}) options WHERE (tenant_id,id) > (:after_tenant,:after_id)"
            params.update(after_tenant=after[0], after_id=after[1])
        sql += " ORDER BY tenant_id,id LIMIT :limit"
        with _session() as session:
            return [
                dict(r)
                for r in session.execute(_statement(sql), params).mappings().all()
            ]
