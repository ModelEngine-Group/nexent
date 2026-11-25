# Thread lifecycle

Use these rules whenever backend or SDK code creates threads, sends blocking work to an executor, starts a background event loop, or holds a streaming network response.

## Ownership

- Route, service, and SDK code must submit Nexent-owned thread work through the process-local `ThreadManager`.
- Do not add direct `threading.Thread`, `ThreadPoolExecutor`, `asyncio.to_thread`, or `run_in_executor(None, ...)` calls outside the thread-manager implementation or an explicitly reviewed allowlist.
- Application lifespan owns manager startup and shutdown. Locate lane policies in `backend/management/thread_management.py` or `backend/runtime/thread_management.py` and shared primitives in `sdk/nexent/core/concurrency/`. Services receive the manager through dependency injection. SDK entry points accept the manager or explicit runtime configuration.
- Put each workload in a named lane with a bounded worker count and bounded queue. Describe work with `ManagedTaskSpec`, including `task_name`, `owner`, and available run or attempt identifiers.

## Admission and queueing

- Capacity covers running and queued work. A full lane rejects the request synchronously before it creates a worker thread, response stream, persistence reservation, or producer channel.
- Do not fall back to an unmanaged thread when admission fails.
- Give queued work a finite queue deadline. For request-owned streams, wait for managed execution to enter its starting state before returning the stream. For a persistent AgentOS run, follow the submit and subscription contracts separately. Submission returns a run reference after admission, and subscribers attach to that run.
- A queue timeout cancels the queued future atomically. The target callable must never begin after the timeout response is returned.
- Map capacity rejection and queue timeout to stable domain errors. The HTTP layer returns a machine-readable error code, retryability, and `Retry-After` when retrying is appropriate.

## Cancellation and streams

- Give each agent run one cancellation scope. Register every blocking stream or transport resource with that scope as soon as it is created.
- Resource close callbacks must be thread-safe and idempotent. Cancellation closes registered resources so a worker blocked in network reads can wake up.
- Every streaming attempt closes its response in `finally` and unregisters its callback. Check cancellation before retrying. A close-induced network exception after cancellation is a cancellation outcome.
- Configure finite connect, read, write, and pool timeouts. Apply a separate model-concurrency limit when upstream capacity is lower than the runtime worker limit.
- Treat client disconnect according to ownership. Runtime's ephemeral stream in `runtime/agentos/ephemeral.py` closes its request-owned execution. The persistent producer in `runtime/agentos/prepared_run.py` follows the run lifecycle, and a disconnected subscriber can reattach by event cursor. See [AgentOS](agentos.md) for replay and projection.

## MCP and A2A

- Give every MCP context one managed session owner in the `mcp-session` lane. Run each blocking MCP tool invocation in `model-tool-io` with a finite deadline.
- The session owner runs the MCP async context and event loop on its ThreadManager worker. Do not use MCPAdapt's synchronous context because it creates a private event-loop thread and performs an unbounded join during close.
- Register every `asyncio.run_coroutine_threadsafe()` call-tool Future with the session owner. Tool timeout, run cancellation, and Agent completion cancel all active Futures before exiting the async context, then wait only for the configured close grace period.
- Do not report an MCP execution as reclaimed while its worker is alive. A close-grace failure remains `STUCK` and must reduce readiness.
- Register each active A2A asyncio task and `httpx.AsyncClient` with the run cancellation scope. Cancellation must set the stop event, cancel the active task on its event loop, and close the client once.
- Apply the A2A deadline to the whole request, including complete SSE consumption. Per-read timeouts alone do not bound a stream that emits occasional chunks forever.

## Timeout logging

- Emit a structured WARNING at the boundary that decides a model stream, MCP operation, or A2A call has timed out. Use stable event names and include the resource identifier, configured threshold, phase, attempt where applicable, and exception type.
- Distinguish waiting for the first chunk from waiting for a later chunk when the stream exposes that state. Keep prompts, histories, tool arguments, authorization values, response bodies, and URL query parameters out of timeout logs.
- Do not re-log the same timeout as ERROR in a generic outer exception handler. A separate ERROR remains appropriate when the resource exceeds its cancellation or close grace period and is confirmed `STUCK`.
