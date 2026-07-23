"""Domain constants for MCP marketplace listing statuses."""

# Listing status: not_shared (未共享), pending_review (待审核),
# rejected (审核驳回), shared (已共享)
STATUS_NOT_SHARED = "not_shared"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_REJECTED = "rejected"
STATUS_SHARED = "shared"

VALID_MARKET_STATUSES = frozenset({
    STATUS_NOT_SHARED,
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
    STATUS_SHARED,
})
