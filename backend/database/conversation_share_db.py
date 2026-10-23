from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update

from database.client import as_dict, filter_property, get_db_session
from database.db_models import ConversationShare, ConversationShareAsset


def create_conversation_share(share_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    with get_db_session() as session:
        payload = filter_property(share_data, ConversationShare)
        payload["created_by"] = user_id
        payload["updated_by"] = user_id
        record = ConversationShare(**payload)
        session.add(record)
        session.flush()
        session.refresh(record)
        return as_dict(record)


def create_conversation_share_assets(
    share_token: str,
    assets: List[Dict[str, Any]],
    user_id: str,
) -> List[Dict[str, Any]]:
    if not assets:
        return []

    with get_db_session() as session:
        records = []
        for asset in assets:
            payload = filter_property(asset, ConversationShareAsset)
            payload["share_token"] = share_token
            payload["created_by"] = user_id
            payload["updated_by"] = user_id
            record = ConversationShareAsset(**payload)
            session.add(record)
            records.append(record)
        session.flush()
        for record in records:
            session.refresh(record)
        return [as_dict(record) for record in records]


def get_active_conversation_share(share_token: str) -> Optional[Dict[str, Any]]:
    with get_db_session() as session:
        stmt = select(ConversationShare).where(
            ConversationShare.share_token == share_token,
            ConversationShare.delete_flag == "N",
            ConversationShare.status == "active",
        )
        record = session.scalars(stmt).first()
        if record is None:
            return None

        data = as_dict(record)
        expire_time = data.get("expire_time")
        if expire_time:
            if isinstance(expire_time, str):
                expire_time = datetime.fromisoformat(expire_time)
            if expire_time < datetime.now():
                return None
        return data


def get_share_asset(share_token: str, asset_id: str) -> Optional[Dict[str, Any]]:
    with get_db_session() as session:
        stmt = select(ConversationShareAsset).where(
            ConversationShareAsset.share_token == share_token,
            ConversationShareAsset.asset_id == asset_id,
            ConversationShareAsset.delete_flag == "N",
        )
        record = session.scalars(stmt).first()
        return None if record is None else as_dict(record)


def revoke_conversation_share(share_token: str, user_id: str) -> bool:
    with get_db_session() as session:
        stmt = update(ConversationShare).where(
            ConversationShare.share_token == share_token,
            ConversationShare.created_by == user_id,
            ConversationShare.delete_flag == "N",
        ).values(status="revoked", updated_by=user_id)
        result = session.execute(stmt)
        return result.rowcount > 0
