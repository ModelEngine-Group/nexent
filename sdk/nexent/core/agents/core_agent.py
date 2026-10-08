"""Stable public Agent entry point.

Execution remains delegated to the existing CodeAgent implementation.
Future runtime selection belongs at this public boundary.
"""

from .execution.code.legacy_agent import CoreAgent

__all__ = ["CoreAgent"]
