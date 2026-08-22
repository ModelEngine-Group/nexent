"""Domain constants for agent marketplace repository listings."""

# Listing status: not_shared (未共享), pending_review (待审核),
# rejected (审核驳回), shared (已共享)
STATUS_NOT_SHARED = "not_shared"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_REJECTED = "rejected"
STATUS_SHARED = "shared"

VALID_REPOSITORY_STATUSES = frozenset({
    STATUS_NOT_SHARED,
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
    STATUS_SHARED,
})

OWNERSHIP_ALL = "all"
OWNERSHIP_CREATED = "created"
OWNERSHIP_OTHERS = "others"

VALID_OWNERSHIP_FILTERS = frozenset({
    OWNERSHIP_ALL,
    OWNERSHIP_CREATED,
    OWNERSHIP_OTHERS,
})
