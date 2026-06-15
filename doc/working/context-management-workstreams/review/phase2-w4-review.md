# Phase 2: W4 Review

## Assessment

W4 fixes a real isolation blocker and has a clear trusted identity-resolution model.
It supports only a single owning user per conversation.

## Findings and Risks

- **CM-007 (Medium, scope-exclusion):** Release one now explicitly uses immutable
  single-owner conversations/sessions and rejects sharing, membership, and transfer.
- **CM-013 (Critical):** The accepted minimum requires current server-issued
  authorization at model-dispatch and governed-persistence boundaries; caller
  assertions are untrusted.
- **CM-025 (Medium):** Delegated/subagent access and mutation scopes are undefined.

## Recommendations

- Enforce the accepted single-owner rejection contract; delegated mutation remains
  separately governed by CM-025.
- Keep authorization decisions mandatory at trusted dispatch and governed-persistence
  boundaries.
- Add negative tests for cross-tenant lookup timing and cleanup selectors.

**Readiness:** Ready for single-owner scope only.
