"""HistoryProjector: projects conversation history from database into ContextItem instances."""

import json
from typing import Any, Callable, Dict, List, Optional

from .context_item import AuthorityTier, ContextItem, ContextItemType, RepresentationTier
from .item_handler_registry import ItemHandlerRegistry
from nexent.monitor import (
    get_monitoring_manager,
    OPENINFERENCE_SPAN_KIND_CHAIN,
    OPENINFERENCE_SPAN_KIND_RETRIEVER,
    OPENINFERENCE_INPUT_VALUE,
    OPENINFERENCE_OUTPUT_VALUE,
)


class HistoryProjector:
    """Projects conversation history from database into ContextItem instances.

    Uses dependency injection for database queries to maintain SDK/backend separation.
    Produces HISTORY_TURN and TOOL_CALL_RESULT ContextItems.
    """

    def __init__(self, query_units_fn: Callable[[int, Optional[int]], List[Dict[str, Any]]]):
        """Initialize with a database query function.

        Args:
            query_units_fn: Function that takes (conversation_id, message_id) and returns
                           a list of unit dictionaries ordered by message_id, step_index, unit_index.
                           This is typically get_message_units_by_message_id from conversation_db.
        """
        self.query_units_fn = query_units_fn

    def project(
        self,
        conversation_id: int,
        message_id: Optional[int] = None,
        purpose: str = "model_context",
    ) -> List[ContextItem]:
        """Project conversation history into ContextItem instances.

        Args:
            conversation_id: The conversation to project.
            message_id: Optional specific message to project (None = all messages).
            purpose: Projection purpose - "model_context" or "chat".

        Returns:
            List of ContextItem instances.

        Raises:
            ValueError: If purpose is not recognized.
        """
        monitoring_manager = get_monitoring_manager()
        with monitoring_manager.trace_operation(
            "context.history_project",
            OPENINFERENCE_SPAN_KIND_CHAIN,
            **{
                "context.conversation_id": conversation_id,
                "context.message_id": message_id,
                "context.purpose": purpose,
                OPENINFERENCE_INPUT_VALUE: {
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "purpose": purpose,
                },
            },
        ):
            with monitoring_manager.trace_operation(
                "context.history_query",
                OPENINFERENCE_SPAN_KIND_RETRIEVER,
                **{
                    "context.conversation_id": conversation_id,
                    "context.message_id": message_id,
                    OPENINFERENCE_INPUT_VALUE: {
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                    },
                },
            ):
                units = self.query_units_fn(conversation_id, message_id)
                if monitoring_manager.is_enabled:
                    unit_types = {}
                    for u in units:
                        ut = u.get("unit_type", "unknown")
                        unit_types[ut] = unit_types.get(ut, 0) + 1
                    monitoring_manager.set_openinference_output({
                        "unit_count": len(units),
                        "unit_types": unit_types,
                    })

            if purpose == "model_context":
                items = self._project_model_context(units)
            elif purpose == "chat":
                items = self._project_chat_context(units)
            else:
                raise ValueError(f"Unknown purpose: {purpose}")
            
            if monitoring_manager.is_enabled:
                monitoring_manager.set_openinference_output({
                    "item_count": len(items),
                    "item_types": [item.item_type.value for item in items],
                })
            
            return items

    def _project_model_context(self, units: List[Dict[str, Any]]) -> List[ContextItem]:
        """Project units into HISTORY_TURN and TOOL_CALL_RESULT items for model context.

        Groups units by message_id and step_index, then:
        - Pairs user messages with assistant final_answer -> HISTORY_TURN
        - Extracts merged tool_call rows -> TOOL_CALL_RESULT
        - Excludes model_output_thinking and model_output_deep_thinking
        """
        items: List[ContextItem] = []

        messages = self._group_by_message(units)

        for message_id, steps in messages.items():
            for step_index, step_units in steps.items():
                history_turn = self._extract_history_turn(step_units, message_id, step_index)
                if history_turn:
                    items.append(history_turn)

                tool_results = self._extract_tool_call_results(step_units, message_id, step_index)
                items.extend(tool_results)

        for item in items:
            ItemHandlerRegistry.get(item.item_type)

        return items

    def _project_chat_context(self, units: List[Dict[str, Any]]) -> List[ContextItem]:
        """Project units into HISTORY_TURN items for chat display.

        Similar to model_context but includes thinking units for full transparency.
        """
        items: List[ContextItem] = []

        messages = self._group_by_message(units)

        for message_id, steps in messages.items():
            for step_index, step_units in steps.items():
                chat_turn = self._extract_chat_turn(step_units, message_id, step_index)
                if chat_turn:
                    items.append(chat_turn)

        return items

    def _group_by_message(
        self, units: List[Dict[str, Any]]
    ) -> Dict[int, Dict[int, List[Dict[str, Any]]]]:
        """Group units by message_id and step_index.

        Returns:
            Dict[message_id, Dict[step_index, List[unit]]]
        """
        messages: Dict[int, Dict[int, List[Dict[str, Any]]]] = {}
        for unit in units:
            message_id = unit.get("message_id") or 0
            step_index = unit.get("step_index") or 0
            if message_id not in messages:
                messages[message_id] = {}
            if step_index not in messages[message_id]:
                messages[message_id][step_index] = []
            messages[message_id][step_index].append(unit)
        return messages

    def _extract_history_turn(
        self,
        units: List[Dict[str, Any]],
        message_id: int,
        step_index: int,
    ) -> Optional[ContextItem]:
        """Extract a HISTORY_TURN item from user input and final_answer units.

        Returns None if no user input or final_answer found.
        """
        user_units = [u for u in units if u.get("unit_type") == "user_input"]
        answer_units = [u for u in units if u.get("unit_type") == "final_answer"]

        if not user_units or not answer_units:
            return None

        user_content = user_units[0].get("unit_content", "")
        answer_content = answer_units[0].get("unit_content", "")

        content = {
            "user_query": user_content,
            "assistant_response": answer_content,
        }

        source_refs = [
            f"unit:{user_units[0]['unit_id']}",
            f"unit:{answer_units[0]['unit_id']}",
        ]

        return ContextItem(
            item_id=f"history_turn:{message_id}:{step_index}",
            item_type=ContextItemType.HISTORY_TURN,
            source_refs=source_refs,
            authority_tier=AuthorityTier.AGENT_INFERENCE,
            minimum_fidelity=RepresentationTier.STRUCTURED,
            current_representation=RepresentationTier.FULL,
            content=content,
            token_estimate=(len(user_content) + len(answer_content)) // 4,
            metadata={"message_id": message_id, "step_index": step_index},
        )

    def _extract_tool_call_results(
        self,
        units: List[Dict[str, Any]],
        message_id: int,
        step_index: int,
    ) -> List[ContextItem]:
        """Extract TOOL_CALL_RESULT items from merged tool_call rows."""
        items: List[ContextItem] = []
        for unit in units:
            if unit.get("unit_type") != "tool_call":
                continue
            try:
                content = json.loads(unit.get("unit_content", "{}"))
            except (json.JSONDecodeError, TypeError):
                continue
            items.append(ContextItem(
                item_id=f"tool_call_result:{unit['unit_id']}",
                item_type=ContextItemType.TOOL_CALL_RESULT,
                source_refs=[f"unit:{unit['unit_id']}"],
                authority_tier=AuthorityTier.TOOL_RESULT,
                minimum_fidelity=RepresentationTier.STRUCTURED,
                current_representation=RepresentationTier.FULL,
                content=content,
                token_estimate=len(unit.get("unit_content", "")) // 4,
                metadata={"message_id": message_id, "step_index": step_index},
            ))
        return items

    def _extract_chat_turn(
        self,
        units: List[Dict[str, Any]],
        message_id: int,
        step_index: int,
    ) -> Optional[ContextItem]:
        """Extract a chat turn including thinking for display purposes."""
        relevant_types = {
            "user_input",
            "model_output_thinking",
            "model_output_code",
            "final_answer",
        }
        relevant_units = [u for u in units if u.get("unit_type") in relevant_types]

        if not relevant_units:
            return None

        content = {
            "units": [
                {
                    "type": u.get("unit_type"),
                    "content": u.get("unit_content", ""),
                }
                for u in relevant_units
            ]
        }

        source_refs = [f"unit:{u['unit_id']}" for u in relevant_units]

        return ContextItem(
            item_id=f"chat_turn:{message_id}:{step_index}",
            item_type=ContextItemType.HISTORY_TURN,
            source_refs=source_refs,
            authority_tier=AuthorityTier.AGENT_INFERENCE,
            minimum_fidelity=RepresentationTier.FULL,
            current_representation=RepresentationTier.FULL,
            content=content,
            token_estimate=sum(len(u.get("unit_content", "")) for u in relevant_units) // 4,
            metadata={"message_id": message_id, "step_index": step_index, "includes_thinking": True},
        )
