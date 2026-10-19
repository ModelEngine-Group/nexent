"""Explicit, bounded migration of trusted model snapshots in the existing model row."""

from database.client import as_dict, get_db_session
from database.db_models import ModelRecord
from sqlalchemy import select, update


def provision_runtime_outlet_batch(builder, *, after_model_id=0, batch_size=100, tenant_id=None, dry_run=True):
    """Serialize with management saves; retain idempotent snapshots and sanitized failures."""
    if type(batch_size) is not int or not 1 <= batch_size <= 1000:
        raise ValueError("MODEL_OUTLET_BATCH_SIZE_INVALID")
    with get_db_session() as session:
        query = select(ModelRecord).where(
            ModelRecord.model_id > after_model_id, ModelRecord.delete_flag == "N",
            ModelRecord.model_type.in_(("llm", "chat")),
        ).order_by(ModelRecord.model_id).limit(batch_size)
        if tenant_id is not None:
            query = query.where(ModelRecord.tenant_id == tenant_id)
        records = session.scalars(query.with_for_update()).all()
        results = []
        for model in records:
            record = as_dict(model)
            snapshot = builder(record)
            status = "failed" if not snapshot or snapshot.get("error") else (
                "ready" if snapshot == record.get("runtime_outlet_snapshot") else "migrated"
            )
            if not dry_run and snapshot != record.get("runtime_outlet_snapshot"):
                session.execute(update(ModelRecord).where(ModelRecord.model_id == model.model_id)
                                .values(runtime_outlet_snapshot=snapshot, updated_by="runtime-outlet-migration"))
            results.append({"model_id": model.model_id, "status": status})
        return results
