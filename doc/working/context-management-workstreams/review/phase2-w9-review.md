# Phase 2: W8 Review

## Assessment

The lifecycle API surface is coherent for linear history. The state machine does not
fully control concurrent active workers or ambiguous external effects.

## Findings and Risks

- **CM-001 (Critical):** Restore/resume can encounter uncertain external tool effects.
- **CM-003 (Critical):** Per-session mutation serialization does not fence already-running workers.
- **CM-007 (Medium, scope-exclusion):** Release-one lifecycle APIs now explicitly reject
  shared-session membership and ownership transfer.
- **CM-011 (Medium):** The accepted minimum treats API, SDK, UI, hooks, and runbook
  dates as planning targets; readiness depends on claim-scoped gates and evidence.

## Recommendations

- Reject lifecycle mutations that conflict with active runs until fencing exists.
- Expose ambiguous-effect state and require explicit resolution.
- Enforce the accepted single-owner lifecycle contract and explicit unsupported errors.

**Readiness:** Feasible with serialized, single-owner, ambiguity-stop scope.
