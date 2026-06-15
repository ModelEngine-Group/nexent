# Phase 2: W6 Review

## Assessment

W6 provides a coherent projection architecture and strong separation of concerns.
Complexity is concentrated in restore lineage, schema evolution, conflict resolution,
and potentially unbounded decision output.

## Findings and Risks

- **CM-002 (High):** Projection replay after physical deletion needs explicit partial-state semantics.
- **CM-005 (High, claim-gated):** W6 consumes W5 canonical current-form events; W5 owns
  the accepted current-plus-previous reader/upcaster contract before the first
  production event-schema upgrade.
- **CM-009 (High):** On-demand replay cost is not sized for long sessions.
- **CM-017 (Medium):** Working Memory conflict resolution is not a complete taxonomy.
- **CM-022 (Low):** Recording every exclusion/transformation can create high-volume sensitive traces.

## Recommendations

- Add projection statuses for complete, partial-after-erasure, and unsupported-version.
- Define replay/materialization thresholds from representative workloads.
- Bound decision records and govern them through W14.
- Specify supported conflict classes and escalation behavior.

**Readiness:** Architecturally coherent; operational contracts remain.
