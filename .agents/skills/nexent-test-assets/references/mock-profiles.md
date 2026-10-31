# Mock and Real Smoke profiles

Introduce profiles only after migration equivalence passes. Supported formal profiles are `mock` and `real_smoke`. Keep results separate by `Case ID + profile`.

Mock service IDs are `model-provider`, `mcp-server`, `knowledge-provider`, `memory-provider`, `a2a-agent`, and `http-fixture`. OAuth/CAS identity Mock remains optional. PostgreSQL, Elasticsearch, Redis, MinIO, and Nexent application services remain real local services.

A2A is fully covered: protocol contract, runtime integration, fixed Playwright discovery, registration, binding, and invocation journeys, failure recovery, and Real Smoke. A missing A2A Mock prerequisite is `blocked`, not policy-skipped.
