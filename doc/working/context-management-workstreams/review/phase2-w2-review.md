# Phase 2: W2 Review

## Assessment

The pure budget calculator is feasible and well bounded. Correctness depends on the
provider capability contract and on preventing local recalculation.

## Findings and Risks

- **CM-016 (High):** When required tokenizer, reasoning-window, or provider-overhead
  behavior is incomplete, the accepted minimum adds one 10% context-window uncertainty
  reserve instead of separately guessing each reserve.
- **CM-013 (Critical):** The accepted boundary treats SDK/client budgets as advisory;
  trusted server-side dispatch resolves or verifies the enforced W2 snapshot and
  rejects caller-expanded limits.

## Recommendations

- Keep the accepted resolved-budget enforcement at the trusted dispatch boundary.
- Apply and expose the accepted 10% uncertainty reserve in addition to output reserve.
- Test override authorization and configuration drift, not only arithmetic.

**Readiness:** Ready to start implementation. Production dispatch activation remains
gated by W1 capacity snapshots, W3 trusted-dispatch integration, and release evidence.
