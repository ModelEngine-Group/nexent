# Phase 2: W3 Review

## Assessment

Cache-aware assembly is feasible, but it must share the exact final serializer with W4
and degrade according to an explicit provider capability registry.

## Findings and Risks

- **CM-016 (High):** Cache directives now require an approved capability profile;
  unknown cache capability disables directives and unknown metrics remain proxy-only.
- **CM-023 (High):** The accepted boundary makes W3 produce only a partition plan;
  W4 computes fingerprints from the exact final dispatched payload.

## Recommendations

- Compute stable-prefix and full-prompt fingerprints from the exact dispatched bytes.
- Make W4/W3 one final assembly contract with provider-versioned serialization.
- Treat unavailable cache metrics as clearly labeled proxy evidence.

**Readiness:** Implementation-ready with W4 as the single final payload owner.
