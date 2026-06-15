# Phase 2: W3 Review

## Assessment

The hard fit invariant is necessary. The specification overstates immediate
implementability because several stages depend on W10-W13 and semantic guarantees are
not mechanically enforceable.

## Findings and Risks

- **CM-008 (High):** The accepted staged contract ships an independent minimal hard-fit
  gateway before later reducers, artifact offload, policy, and governed compaction.
- **CM-013 (Critical):** The accepted minimum restricts production provider capability
  to a trusted server-side gateway that verifies W4/W10/W2/W3 inputs and denies direct
  paths.
- **CM-016 (High):** Unknown hard capacity now blocks production dispatch; unknown
  exact-counting behavior uses W2's 10% uncertainty reserve and cannot be labeled exact.
- **CM-018 (High):** Mandatory minimum and recent-pair preservation can exceed capacity;
  semantic adequacy cannot be guaranteed.
- **CM-023 (High):** The accepted boundary makes W16 a cache-partition-plan producer
  and W3 the sole final payload serializer/fingerprint owner.
- **CM-026 (Low):** Multimodal fit is required without a modality contract.

## Recommendations

- Deliver a minimal gateway that can reject, remove optional content, and apply bounded
  deterministic fallback before richer stages arrive.
- Define the exact dispatched-byte serialization boundary shared with W16.
- Separate structural fit/minimum checks from W15-measured semantic retention.

**Readiness:** Implementation-ready with the accepted staged scope and single final
payload owner.
