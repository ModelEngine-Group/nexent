"""Reason code constants for context policy decisions.

These codes provide traceability for why items were selected, excluded,
or transformed during context management operations.
"""

# Selection reason codes
SELECTED_MANDATORY_MINIMUM = "selected_mandatory_minimum"
SELECTED_BUDGET_UPGRADE = "selected_budget_upgrade"

# Exclusion reason codes
EXCLUDED_BUDGET = "excluded_budget"
EXCLUDED_POLICY_DISABLED = "excluded_policy_disabled"
EXCLUDED_LOWER_AUTHORITY = "excluded_lower_authority"

# Memory operation reason codes
MEMORY_OPERATION_ALLOWED = "memory_operation_allowed"
MEMORY_OPERATION_DENIED = "memory_operation_denied"
CONFIRMATION_REQUIRED = "confirmation_required"

# Reduction reason codes
MINIMUM_FIDELITY_VIOLATION = "minimum_fidelity_violation"
REDUCER_FAILED = "reducer_failed"
REPRESENTATION_STALE = "representation_stale"
