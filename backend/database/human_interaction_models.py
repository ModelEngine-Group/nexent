"""Compatibility imports; canonical HITL models inherit TableBase in db_models."""

from .db_models import HumanEvent, HumanExecution, HumanRequest, HumanRun

__all__ = ["HumanEvent", "HumanExecution", "HumanRequest", "HumanRun"]
