# Nexent ThreadManager

`ThreadManager` owns thread execution inside one service process. A service
creates one manager, starts it from the application lifespan, installs it with
`set_default_thread_manager()`, then clears and shuts it down during lifespan
exit.

Use `agent-run` for an Agent loop, `model-tool-io` for blocking model or tool
calls, `control-io` for short control-plane I/O, `evaluation` for evaluation
work, `sandbox` for sandbox cleanup, and `background-service` for registered
long-running services. Every lane requires a worker limit and queue limit.

SDK code can call `run_blocking()` without importing backend modules. Direct
SDK embedding uses a bounded fallback manager. The embedding process can close
that fallback with `shutdown_fallback_thread_manager()`.

Long-running services use `register_service()` and `start_service()`. Their
target receives a cancellation event, and a close hook should release any
blocking socket, stream, server, or queue wait. Shutdown reports executions
that remain `STUCK` after the grace period.

Config exposes a trusted-network diagnostic snapshot on port 5010 at
`GET /internal/thread-capacity`. The `lanes` array reports configured pool
capacity and current occupancy. The `executions` array reports active managed
work for the Config process, including task name, owner, state,
dedicated-thread flag, Python thread name, liveness, and age. Reading the
snapshot does not emit lifecycle logs or telemetry. Other service processes
publish their state changes through telemetry and do not expose this route.

Each managed state change emits one immediate OpenTelemetry statistics span.
In Phoenix, select the configured Nexent project and filter the custom
attribute `nexent.span.kind = thread`. The span retains the standard OTel
`SpanKind.INTERNAL` and OpenInference `CHAIN` classification.

Data Process integration is intentionally outside this module's current
migration scope and will be handled by its own SPEC.
