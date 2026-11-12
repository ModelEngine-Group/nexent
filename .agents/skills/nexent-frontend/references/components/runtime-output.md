# Nexent output boundary and common conversation presentation

`frontend/lib/nexentOutputAdapter.ts` normalizes public execution envelopes into the existing Nexent event protocol. It creates no React nodes or assistant-ui parts and does not select behavior by Core name. Live SSE and saved units use the same state machine; rendering remains owned by the original chat parsers and components.

- Remove the M5 `runtime-output` renderer path. Reasoning, Markdown, ToolFallback and SubAgentContainer render all Core outputs.
- Ordinary model process text uses the established process event type. Preserve explicit provider reasoning separately in metadata and never invent reasoning text.
- Only a validated, sealed successful RunResult confirms final content. Failed/stopped/missing/repeated/order-invalid results retain partial and never become completed by EOF.
- Correlate tool results by turn, invocation and local ID. Tool error and child execution status are generic presentation inputs for every Core.
- Deserialize envelopes only at the saved-unit boundary. Live model JSON remains ordinary text.
- Unknown token counts remain explicitly unknown in the shared usage component; do not display zero as a substitute.
- Historical rendering uses saved events and persisted status, never the Agent's current Core selection.
