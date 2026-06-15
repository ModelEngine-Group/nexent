# Phase 2: W8 Review

## Assessment

Centralized fail-closed validation is sound. Full-prefix hashing and invalidation need a
cost model and durable-version compatibility rules.

## Findings and Risks

- **CM-014 (Medium):** Historical checkpoint/projection schema compatibility is incomplete.
- **CM-015 (Low):** Rehashing complete event ranges can become O(history) per checkpoint.
- **CM-020 (High):** Deletion/redaction invalidation delivery needs cross-store repair semantics.

## Recommendations

- Compute append-time incremental prefix hashes and store component digests.
- Define compatibility/upcast behavior before accepting historical checkpoints.
- Treat eager invalidation as an optimization; retain centralized lazy validation as
  the correctness backstop with repair monitoring.

**Readiness:** Implementation-ready with measured hashing strategy.
