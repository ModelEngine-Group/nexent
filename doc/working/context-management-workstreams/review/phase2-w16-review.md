# Phase 2: W16 Review

## Assessment

Cache-aware assembly is feasible, but it must share the exact final serializer with W3
and degrade according to an explicit provider capability registry.

## Findings and Risks

- **CM-016 (High):** Cache directives now require an approved capability profile;
  unknown cache capability disables directives and unknown metrics remain proxy-only.
- **CM-023 (High):** Cache fingerprints may be computed before W3 changes the final payload.

## Recommendations

- Compute stable-prefix and full-prompt fingerprints from the exact dispatched bytes.
- Make W3/W16 one final assembly contract with provider-versioned serialization.
- Treat unavailable cache metrics as clearly labeled proxy evidence.

**Readiness:** Implementation-ready after assembly ownership is unified.
