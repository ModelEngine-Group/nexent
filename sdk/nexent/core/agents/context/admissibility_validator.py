"""Admissibility validator for reduction results against policy and item constraints."""

import hashlib
from typing import Dict

from .context_item import ContextItem, RepresentationTier
from .policy_models import ContextPolicy
from .reducer_models import ReductionResult


# Tier ordering: higher rank = higher fidelity
_TIER_RANK: Dict[RepresentationTier, int] = {
    RepresentationTier.POINTER: 0,
    RepresentationTier.STRUCTURED: 1,
    RepresentationTier.COMPRESSED: 2,
    RepresentationTier.FULL: 3,
}


class AdmissibilityValidator:
    """Validate reduction results against policy and item constraints."""

    @staticmethod
    def validate(
        item: ContextItem,
        result: ReductionResult,
        target: RepresentationTier,
        policy: ContextPolicy | None = None,
    ) -> ReductionResult:
        """Validate a reduction result and return it or mark as inadmissible.

        Reject if:
        - target tier is below item.minimum_fidelity (return admissible=False with reason)
        - result.content is None when target != POINTER
        - source_fingerprint is empty string
        """
        if _TIER_RANK[target] < _TIER_RANK[item.minimum_fidelity]:
            return ReductionResult(
                representation=result.representation,
                source_fingerprint=result.source_fingerprint,
                token_count=result.token_count,
                generator=result.generator,
                generator_version=result.generator_version,
                admissible=False,
                loss_metadata={"reason": "minimum_fidelity_violation"},
                content=result.content,
            )

        if not result.admissible:
            return result

        if target != RepresentationTier.POINTER and result.content is None:
            return ReductionResult(
                representation=result.representation,
                source_fingerprint=result.source_fingerprint,
                token_count=result.token_count,
                generator=result.generator,
                generator_version=result.generator_version,
                admissible=False,
                loss_metadata={"reason": "content_required_but_none"},
                content=result.content,
            )

        fingerprint = result.source_fingerprint
        if not fingerprint:
            fingerprint = hashlib.sha256(str(item.content).encode()).hexdigest()[:16]

        return ReductionResult(
            representation=result.representation,
            source_fingerprint=fingerprint,
            token_count=result.token_count,
            generator=result.generator,
            generator_version=result.generator_version,
            admissible=result.admissible,
            loss_metadata=result.loss_metadata,
            content=result.content,
        )
