# Phase 6: W2 Post-Acceptance Review

> Phase 6 is the post-acceptance review track opened 2026-06-16 after the W1
> end-to-end retrospective. It uses the same review format and CM-NNN
> numbering convention as Phase 2 single-W reviews, applied to specs that
> have been Accepted but have not yet been implemented or have just begun
> implementation. The goal is to catch under-specifications that would
> reproduce W1-style post-acceptance surprises.

## Assessment

W2's pure budget calculator is architecturally sound and the existing Phase 2
review (`phase2-w2-review.md`) correctly flagged CM-013 and CM-016. Re-reading
the spec with implementation-readiness in mind surfaces four additional
under-specifications. None invalidate the architecture; each would leave a
concrete code or configuration decision unresolved at implementation time
and risks the same "one-sentence spec hides multiple decisions" failure mode
that produced W1 KL-1.

## Findings and Risks

- **CM-027 (Medium):** `soft_limit_ratio` has no default value; compaction
  trigger point is undefined until implementation picks a number. Without a
  spec-level default, implementations diverge and operators have no shared
  expectation.
- **CM-028 (Medium):** "may be overridden per agent or per request" hides two
  distinct contracts. Per-agent needs a DB column and an agent-edit UI;
  per-request needs an API body field. The W2 task list does not reflect
  this; both paths must be either in scope with a frontend sub-plan or
  explicitly deferred.
- **CM-029 (High):** Every model call (primary, compaction, summary) needs
  its own W1→W2 snapshot pair. W13's compaction model is a separate
  `model_record_t` with its own capacity; reusing the main run's snapshot
  would misjudge the compaction budget. This is the same defect class as
  W1 KL-1 — assuming one model's parameters apply to all calls.
- **CM-030 (High):** Implementation Plan Step 5 reads "consistently" without
  saying whether it is a rename or the CM-013 trusted-dispatch enforcement
  contract. The interpretations have very different code scope and security
  semantics; implementation needs an explicit answer.

## Recommendations

- Accept the proposed defaults and contracts in `findings-registry.md` for
  CM-027 through CM-030 and merge them into `W2_Output_and_Safety_Capacity_Reserve.md`
  before implementation begins.
- For CM-028, decide in the W2 spec which of the two override paths is in
  W2 scope versus deferred to a follow-up; record the decision in W2
  alongside the per-agent column migration plan if in scope.
- For CM-029, cross-link W13 spec: when W13 is re-reviewed, verify W13
  invokes the W1→W2 chain with the compaction model's identity and does
  not inherit the main run's snapshot. Add the same per-model-snapshot
  rule to W13's `Repository Touchpoints` enumeration of compaction call
  sites.
- For CM-030, add the explicit server-side assertion in the SDK or backend
  dispatch wrapper and include a negative test that a caller-supplied
  `max_tokens` kwarg is rejected or coerced.

**Readiness:** Not ready for implementation as written. Once CM-027 through
CM-030 are reflected in the W2 spec (and CM-029's cross-link to W13 is
recorded), W2 returns to Ready to start implementation. Production dispatch
activation continues to depend on the W1 snapshot, W3 trusted-dispatch
integration, and release evidence already cited in the Phase 2 W2 review.
