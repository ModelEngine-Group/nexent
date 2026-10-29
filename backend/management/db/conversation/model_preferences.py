# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Private conversation configuration; never expose preferences as runtime metadata."""

from copy import deepcopy

from contracts.errors.exceptions import ConversationNotFoundError, ModelOutletConflictError, ModelOutletValidationError
from sqlalchemy import func, select

from management.db.client import get_db_session
from management.db.models import ConversationRecord


def model_preferences(conversation_id, user_id, *, expected_version=None, outlet_id=None, resolve_values=None, selected_model_id=None):
    """Read or atomically patch user-owned preferences in the existing conversation row."""
    with get_db_session() as session:
        statement = select(ConversationRecord).where(ConversationRecord.conversation_id == conversation_id,
            ConversationRecord.created_by == user_id, ConversationRecord.delete_flag == "N")
        updating = resolve_values is not None or selected_model_id is not None
        if updating:
            statement = statement.with_for_update()
        record = session.scalars(statement).first()
        if record is None:
            raise ConversationNotFoundError("Conversation not found")
        version = int(record.model_parameter_preferences_version or 0)
        preferences = deepcopy({} if record.model_parameter_preferences is None
                               else record.model_parameter_preferences)
        if not isinstance(preferences, dict):
            raise ModelOutletValidationError("CONVERSATION_PREFERENCES_INVALID")
        if updating:
            if type(expected_version) is not int or expected_version != version:
                raise ModelOutletConflictError()
            if selected_model_id is not None:
                record.selected_model_id = selected_model_id
            else:
                key = str(outlet_id)
                values = resolve_values(deepcopy(preferences.get(key, {})))
                if values:
                    preferences[key] = values
                else:
                    preferences.pop(key, None)
            version += 1
            record.model_parameter_preferences = preferences
            record.model_parameter_preferences_version = version
            record.updated_by = user_id
            record.update_time = func.current_timestamp()
            session.flush()
        return {"model_parameter_preferences": preferences, "version": version,
                "selected_model_id": getattr(record, "selected_model_id", None)}
