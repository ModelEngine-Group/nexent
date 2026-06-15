# Phase 1: Program Goal Matrix

## Review Basis

Source: `../context-management-production-plan.md`.

This phase extracts program goals without judging W1-W16. Goals are stated as
verifiable outcomes because the plan is intended for multiple implementation teams.

## Goal Matrix

| ID | Category | Goal | Explicit success evidence | Implicit success condition |
| --- | --- | --- | --- | --- |
| G-01 | Business | Position Nexent as a production-grade Context and Memory Control Plane. | Approved production-readiness evidence for the enabled release scope. | Product claims are narrower than demonstrated capabilities. |
| G-02 | Product | Preserve existing conversation and UI behavior during migration. | Compatibility projection passes approved fixtures. | Rollback and mixed-version operation do not corrupt user-visible history. |
| G-03 | Product | Make long-running sessions inspectable, compactable, restorable, and resettable. | Authorized lifecycle APIs and replayable outcomes. | Operations remain understandable during failures and concurrency. |
| G-04 | Functional | Every model request uses correct capacity semantics and fits provider limits. | Serialized-request fit tests and provider overflow evidence. | Every dispatch path, including compaction, is covered. |
| G-05 | Functional | Preserve rich execution evidence without injecting raw history into prompts. | Typed event log plus purpose-specific bounded projections. | Projection growth is controlled as event detail grows. |
| G-06 | Functional | Recover effective context and Working Memory after restart or worker change. | Cross-worker restart and replay tests. | Recovery distinguishes state replay from external-effect replay. |
| G-07 | Functional | Govern context selection and memory lifecycle through one policy contract. | Bypass tests and explainable decisions. | Enforcement happens at a trusted boundary. |
| G-08 | Functional | Degrade context progressively while preserving mandatory minimums. | Minimum-fidelity and tool-pair tests. | Structural validity is not confused with semantic adequacy. |
| G-09 | Functional | Offload large outputs while retaining authorized deterministic retrieval. | Large-output and pointer-resolution tests. | Cross-store publication and repair are defined. |
| G-10 | Functional | Preserve prompt-cache reuse without changing correctness or authority. | Stable-prefix determinism and cache metrics. | Provider-specific capabilities are declared. |
| G-11 | Security | Prevent cross-tenant and cross-user context leakage. | Collision, authorization, cleanup, and audit tests. | Unsupported sharing and delegation modes fail closed. |
| G-12 | Privacy | Redact, retain, expire, and delete governed data across all stores. | Secret fixtures and deletion proof reports. | Physical erasure has documented replay consequences. |
| G-13 | Reliability | No worker crash, stale cache, compaction failure, or lifecycle operation silently corrupts context state. | Fault, CAS, invalidation, and writeback tests. | Fencing and repair behavior match supported concurrency claims. |
| G-14 | Scalability | Support production multi-worker load with bounded storage, replay, hashing, and projection cost. | Representative load/capacity evidence. | Workload model and topology limits are explicit. |
| G-15 | Operability | Make context decisions, faults, and recovery observable and actionable. | Dashboards, alerts, reason codes, replay, and runbooks. | Trace volume, privacy, retention, and cardinality are bounded. |
| G-16 | Maintainability | Allow schemas, policies, providers, and algorithms to evolve without losing historical sessions. | Compatibility window, upcasters, version tests, and ADRs. | Mixed-version deployments and rollback are supported. |
| G-17 | Quality | Enforce measurable context quality, safety, durability, latency, and cost targets. | Numeric SLO registry and release gates. | Missing evidence fails only the claims that require it. |
| G-18 | Delivery | Deliver an implementation-ready, multi-team plan with realistic dependencies and ownership. | Accepted contracts, dependency gates, and scoped milestones. | Calendar targets do not substitute for readiness evidence. |

## Success-Criteria Summary

The program succeeds only when the enabled capability claims are correct, isolated,
durable, governed, operable, and evidenced. A bounded pilot can succeed before
production-scale topology, automatic side-effect-safe resume, unsupported modalities,
or shared/delegated session mutation are delivered, provided those exclusions are
explicit and enforced.
