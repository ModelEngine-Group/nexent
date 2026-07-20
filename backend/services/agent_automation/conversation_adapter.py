import json
import logging
from typing import Any, Dict, Optional

from consts.model import MessageRequest, MessageUnit
from services.conversation_management_service import (
    get_conversation_history_service,
    save_message,
    save_message_unit,
    update_unit_content,
)

logger = logging.getLogger("agent_automation.conversation_adapter")


class AutomationConversationAdapter:
    """Persist automation UI events through the existing conversation service."""

    def append_proposal_exchange(
        self,
        conversation_id: int,
        user_instruction: str,
        payload: Dict[str, Any],
        user_id: str,
        tenant_id: str,
    ) -> Dict[str, int]:
        history_payload = get_conversation_history_service(conversation_id, user_id)
        messages = history_payload[0].get("message", []) if history_payload else []
        user_request = MessageRequest(
            conversation_id=conversation_id,
            message_idx=len(messages),
            role="user",
            message=[MessageUnit(type="string", content=user_instruction)],
        )
        user_message_id = save_message(user_request, user_id, tenant_id)
        user_unit_id = save_message_unit(
            message_id=user_message_id,
            conversation_id=conversation_id,
            unit_index=0,
            unit_type="string",
            unit_content=user_instruction,
            user_id=user_id,
        )
        content = json.dumps(payload, ensure_ascii=False)
        request = MessageRequest(
            conversation_id=conversation_id,
            message_idx=len(messages) + 1,
            role="assistant",
            message=[MessageUnit(type="automation_proposal", content=content)],
        )
        message_id = save_message(request, user_id, tenant_id)
        unit_id = save_message_unit(
            message_id=message_id,
            conversation_id=conversation_id,
            unit_index=0,
            unit_type="automation_proposal",
            unit_content=content,
            user_id=user_id,
        )
        return {
            "user_message_id": user_message_id,
            "user_unit_id": user_unit_id,
            "message_id": message_id,
            "unit_id": unit_id,
        }

    def update_proposal(
        self,
        unit_id: Optional[int],
        payload: Dict[str, Any],
        user_id: str,
    ) -> None:
        if not unit_id:
            return
        update_unit_content(
            unit_id,
            json.dumps(payload, ensure_ascii=False),
            user_id,
        )


automation_conversation_adapter = AutomationConversationAdapter()
