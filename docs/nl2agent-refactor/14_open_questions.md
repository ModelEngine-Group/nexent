# Open questions

These questions could not be resolved conclusively from the canonical design, current code/tests, Git history or existing architecture. Everything else is decided in the plan.

1. The requested primary file `docs/nl2agent-refactor/current-implementation-design.md` is absent. Is `doc/docs/zh/developer-guide/nl2agent-design.md`—which names the requested baseline/snapshot and contains the complete behavior—the intended authoritative document, or is an unpublished English revision missing?
2. What is the exact release migration identifier and authoritative set of fresh-install SQL paths on the clean branch? The supplied repository overview names `docker/init.sql` and a K8s file, while this snapshot changes `deploy/sql/init.sql`.
3. Which always-on scheduler, if any, is guaranteed in Docker, Kubernetes and local deployments? This determines whether retention/expired-operation cleanup can move from opportunistic Session start to a scheduled job without a deployment gap.
4. Does the existing official Skill installer guarantee or expose rollback for filesystem success followed by database/binding failure? If not, the durable reconciliation checkpoint described in PR4 is required.
5. Must private-network MCP endpoints remain usable in any supported first-release deployment? The prompt explicitly permits deferring private/loopback blocking, but product/network policy determines whether the minimum fallback should disable redirects or rely on deployment egress controls.

No answer changes the required user-visible feature set. Questions 3–5 only select an implementation adapter or deferred-security fallback.
