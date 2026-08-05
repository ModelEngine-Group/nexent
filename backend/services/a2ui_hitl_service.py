"""
A2UI Human-In-The-Loop (HITL) Interaction Service.

Manages Agent-to-UI interaction lifecycle:
  create interaction -> send form to frontend -> wait for response -> timeout handling

Usage:
    from services.a2ui_hitl_service import A2UIHITLService

    service = A2UIHITLService.get_instance()
    interaction = await service.create_interaction(...)
    response = await service.wait_for_response(interaction.interaction_id)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class InteractionStatus(str, Enum):
    PENDING = "pending"
    RESPONDED = "responded"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class PendingInteraction:
    """Represents a single pending HITL interaction."""

    interaction_id: str
    conversation_id: str
    agent_id: str
    user_id: str
    question: str
    payload: dict = field(default_factory=dict)
    status: InteractionStatus = InteractionStatus.PENDING
    response: Optional[dict] = None
    created_at: float = field(default_factory=time.time)
    timeout_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "interaction_id": self.interaction_id,
            "status": self.status.value,
            "response": self.response,
            "question": self.question,
            "payload": self.payload,
            "created_at": self.created_at,
        }


class A2UIHITLService:
    """Singleton service that manages all HITL interactions.

    Interactions are stored in-memory keyed by interaction_id.  Each
    interaction has an associated asyncio.Event that is set when the
    user submits a response (or the interaction is cancelled / times out).
    """

    _instance: Optional["A2UIHITLService"] = None

    def __new__(cls) -> "A2UIHITLService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._interactions: dict[str, PendingInteraction] = {}
            cls._instance._events: dict[str, asyncio.Event] = {}
        return cls._instance

    @classmethod
    def get_instance(cls) -> "A2UIHITLService":
        """Return the singleton instance."""
        return cls()

    # ------------------------------------------------------------------
    # Interaction lifecycle
    # ------------------------------------------------------------------

    async def create_interaction(
        self,
        conversation_id: str,
        agent_id: str,
        user_id: str,
        question: str,
        payload: Optional[dict] = None,
        timeout_seconds: Optional[float] = None,
    ) -> PendingInteraction:
        """Create a new pending interaction.

        Args:
            conversation_id: The conversation this interaction belongs to.
            agent_id: The agent that created the interaction.
            user_id: The user being prompted.
            question: The question / prompt text shown to the user.
            payload: Arbitrary JSON payload (form schema, options, etc.).
            timeout_seconds: If set, the interaction will time out after
                this many seconds.

        Returns:
            The newly created PendingInteraction.
        """
        iid = uuid.uuid4().hex
        interaction = PendingInteraction(
            interaction_id=iid,
            conversation_id=conversation_id,
            agent_id=agent_id,
            user_id=user_id,
            question=question,
            payload=payload or {},
            timeout_at=(
                time.time() + timeout_seconds
                if timeout_seconds
                else None
            ),
        )
        self._interactions[iid] = interaction
        self._events[iid] = asyncio.Event()
        logger.info(
            "Created HITL interaction %s for conversation %s",
            iid,
            conversation_id,
        )
        return interaction

    async def wait_for_response(
        self,
        interaction_id: str,
        timeout: Optional[float] = None,
    ) -> Optional[dict]:
        """Block until the interaction receives a response (or times out).

        Args:
            interaction_id: The interaction to wait on.
            timeout: Override the interaction's configured timeout.  When
                ``None`` and the interaction has a ``timeout_at`` the
                remaining time is used automatically.

        Returns:
            The response dict submitted by the user, or ``None`` if the
            interaction timed out or was cancelled.
        """
        interaction = self._interactions.get(interaction_id)
        if interaction is None:
            logger.warning(
                "wait_for_response: interaction %s not found", interaction_id
            )
            return None

        if interaction.status != InteractionStatus.PENDING:
            if interaction.status == InteractionStatus.RESPONDED:
                return interaction.response
            return None

        event = self._events.get(interaction_id)
        if event is None:
            return None

        effective_timeout: Optional[float] = timeout
        if effective_timeout is None and interaction.timeout_at:
            effective_timeout = max(
                0.0, interaction.timeout_at - time.time()
            )

        try:
            if effective_timeout is not None:
                await asyncio.wait_for(
                    event.wait(), timeout=effective_timeout
                )
            else:
                await event.wait()
        except asyncio.TimeoutError:
            logger.info(
                "HITL interaction %s timed out", interaction_id
            )
            interaction.status = InteractionStatus.TIMEOUT
            self._cleanup(interaction_id)
            return None

        if interaction.status == InteractionStatus.RESPONDED:
            return interaction.response

        return None

    def submit_response(
        self, interaction_id: str, response: dict
    ) -> bool:
        """Submit a user response to a pending interaction.

        Args:
            interaction_id: The target interaction.
            response: Arbitrary JSON data representing the user's reply.

        Returns:
            ``True`` if the response was accepted, ``False`` otherwise.
        """
        interaction = self._interactions.get(interaction_id)
        if interaction is None:
            logger.warning(
                "submit_response: interaction %s not found", interaction_id
            )
            return False
        if interaction.status != InteractionStatus.PENDING:
            logger.warning(
                "submit_response: interaction %s is %s, not pending",
                interaction_id,
                interaction.status.value,
            )
            return False

        interaction.status = InteractionStatus.RESPONDED
        interaction.response = response
        event = self._events.get(interaction_id)
        if event:
            event.set()
        logger.info(
            "Response submitted for interaction %s", interaction_id
        )
        return True

    def cancel_interaction(self, interaction_id: str) -> bool:
        """Cancel a pending interaction.

        Args:
            interaction_id: The interaction to cancel.

        Returns:
            ``True`` if the interaction was found and cancelled.
        """
        interaction = self._interactions.get(interaction_id)
        if interaction is None:
            return False
        if interaction.status == InteractionStatus.PENDING:
            interaction.status = InteractionStatus.CANCELLED
            event = self._events.get(interaction_id)
            if event:
                event.set()
        self._cleanup(interaction_id)
        logger.info("Cancelled interaction %s", interaction_id)
        return True

    def get_interaction(
        self, interaction_id: str
    ) -> Optional[PendingInteraction]:
        """Return the interaction with the given id, or ``None``."""
        return self._interactions.get(interaction_id)

    def get_pending_interactions(
        self,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> list[PendingInteraction]:
        """Return pending interactions, optionally filtered.

        Args:
            conversation_id: If set, only return interactions for this
                conversation.
            user_id: If set, only return interactions for this user.

        Returns:
            A list of PendingInteraction objects with status PENDING.
        """
        return [
            i
            for i in self._interactions.values()
            if i.status == InteractionStatus.PENDING
            and (not conversation_id or i.conversation_id == conversation_id)
            and (not user_id or i.user_id == user_id)
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cleanup(self, interaction_id: str) -> None:
        """Remove interaction and its event from internal storage."""
        self._interactions.pop(interaction_id, None)
        self._events.pop(interaction_id, None)


# ------------------------------------------------------------------
# Convenience high-level API
# ------------------------------------------------------------------


async def request_user_feedback(
    agent_run_info: Any,
    conversation_id: str,
    user_id: str,
    agent_id: str,
    question: str,
    options: Optional[list] = None,
    allow_custom_input: bool = False,
    timeout_seconds: Optional[float] = None,
    observer: Any = None,
) -> Optional[dict]:
    """High-level entry point for requesting user feedback from an agent run.

    This function:
      1. Creates an A2UI HITL interaction via :class:`A2UIHITLService`.
      2. Builds an A2UI surface with the question and optional quick-reply
         buttons / text area.
      3. Emits the surface and component messages through the observer.
      4. Blocks until the user responds (or the interaction times out).

    Args:
        agent_run_info: The agent run info (used for context).
        conversation_id: Conversation identifier.
        user_id: User identifier.
        agent_id: Agent identifier.
        question: The prompt / question displayed to the user.
        options: List of quick-reply options (strings or dicts).
        allow_custom_input: Whether to show a free-text input area.
        timeout_seconds: Interaction timeout in seconds.
        observer: Optional MessageObserver for emitting A2UI messages.

    Returns:
        The user's response dict, or ``None`` if timed out / cancelled.
    """
    from nexent.core.a2ui.a2ui_builder import A2UIBuilder
    from nexent.core.utils.observer import ProcessType

    service = A2UIHITLService.get_instance()

    interaction = await service.create_interaction(
        conversation_id=conversation_id,
        agent_id=agent_id,
        user_id=user_id,
        question=question,
        payload={
            "options": options or [],
            "allow_custom_input": allow_custom_input,
        },
        timeout_seconds=timeout_seconds,
    )

    if observer:
        builder = A2UIBuilder(
            surface_id=f"hitl_{interaction.interaction_id}"
        )
        surface_msg = builder.build_create_surface(
            catalog="hitl", title=question
        )
        observer.add_message(
            "",
            ProcessType.A2UI_SURFACE,
            json.dumps(surface_msg, ensure_ascii=False),
        )

        builder.add_text(question, "hitl_q", "subtitle")

        if options:
            builder.add_quick_replies(options, "hitl_opts")

        if allow_custom_input:
            builder.add_text_area(
                "Additional input",
                "Please enter...",
                "hitl_ta",
                "hitl.custom_input",
            )

        components_msg = builder.build_update_components()
        observer.add_message(
            "",
            ProcessType.A2UI_COMPONENTS,
            json.dumps(components_msg, ensure_ascii=False),
        )

    response = await service.wait_for_response(
        interaction.interaction_id, timeout_seconds
    )

    if observer:
        status_payload = {
            "interaction_id": interaction.interaction_id,
            "status": interaction.status.value,
            "response": response,
        }
        observer.add_message(
            "",
            ProcessType.HITL_FORM_RESPONSE,
            json.dumps(status_payload, ensure_ascii=False),
        )

    return response