const { EventSchemas } = require('./node_modules/.pnpm/@ag-ui+core@0.0.59/node_modules/@ag-ui/core/dist/index.js');

const events = [
  {"type": "RUN_STARTED", "threadId": "202", "runId": "run_4b50a2aa12eb", "timestamp": 1789042084484, "metadata": {"nexus_input": {"query": "test"}}},
  {"type": "RAW", "event": {"type": "conversation_created", "content": {"conversation_id": 202}}, "source": "conversation_created", "timestamp": 1789042084484},
  {"type": "TOOL_CALL_START", "toolCallId": "tc_123", "toolCallName": "search", "timestamp": 1789042085094},
  {"type": "TEXT_MESSAGE_START", "messageId": "msg_123", "role": "assistant", "timestamp": 1789042085094},
  {"type": "TEXT_MESSAGE_CONTENT", "messageId": "msg_123", "delta": "Hello", "timestamp": 1789042085094},
  {"type": "STEP_STARTED", "stepName": "step_abc", "timestamp": 1789042085094},
  {"type": "REASONING_MESSAGE_START", "messageId": "msg_reason", "timestamp": 1789042085094},
  {"type": "SUBAGENT_STARTED", "subagentRunId": "run_abc", "name": "SubAgent", "timestamp": 1789042085094},
  {"type": "STATE_DELTA", "delta": [{"plan": "..."}], "timestamp": 1789042085094},
  {"type": "RUN_FINISHED", "threadId": "202", "runId": "run_4b50a2aa12eb", "timestamp": 1789042084484, "outcome": {"type": "success"}},
];

for (const ev of events) {
  const result = EventSchemas.safeParse(ev);
  if (result.success) {
    console.log(`✅ ${ev.type}`);
  } else {
    console.log(`❌ ${ev.type}:`, JSON.stringify(result.error.issues));
  }
}
