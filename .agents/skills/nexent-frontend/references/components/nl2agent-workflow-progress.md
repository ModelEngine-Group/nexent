# NL2Agent workflow progress

Feature-only implementation: `app/[locale]/newchat/assistant-ui/nl2agent-workflow-progress.tsx`.

The header stays outside the message viewport, below the creator-history toolbar. Native AntD Steps and central theme tokens provide four read-only stages; no click handler advances the workflow. Below 420px container width the compact view names the current stage and position, retaining accessible labels for the full flow.

The stage row shows names, numbers and completion icons without repeated completion or current-progress descriptions. Only skipped stages retain an explanatory label. The footer owns current progress, waiting, paused and error details in both desktop and compact layouts; matching details must not hide a waiting or paused state.

The header is not permanently rendered. An empty draft description and the start of a conversation do not establish creation intent. Explicit full-generation tool intent enables the header, including generation without resources; prompt-only context reads keep it hidden regardless of the description. On history replay, scoped resource cards, validated retrieval receipts and completion receipts restore visibility even when the description has already been saved and the original tool invocation is absent. Explicit recommend/bind-only intent and prompt-only saves do not enable a creation header. Idle/new conversations and local optimization stay hidden, including a new optimization turn after creation completed. This is presentation state only; no keyword intent classifier or additional model output is introduced.

`Nl2AgentWorkflowProgress` takes one presentation value. `Nl2AgentWorkflowHeader` derives that value from the current assistant-ui thread and the optional existing flow phase. It creates no business state, provider request or model output requirement. Standalone panels without a flow provider remain supported.

Only parsed server receipts, typed cards and execution state establish facts. Text, user intent and tool starts cannot establish completion. Semantic/fuzzy mode follows scoped retrieval events; an absent embedding model is normal fuzzy mode. Waiting and stopped states never spin. Skipped binding is not a successful binding.

The live and history adapters retain bounded validated receipt metadata using `recordNl2AgentState`. Raw control JSON must not become fallback assistant prose. Agent/conversation changes reset the displayed facts; current-run sequence checks prevent stale progress. Saved prompt fields alone do not establish final completion.

All strings are localized under `nl2agent.workflow.*`. The component does not own configuration, card actions, authorization, cache policy or model orchestration. Regression proof lives in workflow/component and history tests, plus `NL2A-WORKFLOW-D4-001` for the real panel and controlled SSE/history boundary.
