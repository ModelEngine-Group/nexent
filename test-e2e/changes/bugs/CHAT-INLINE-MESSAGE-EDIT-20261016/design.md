# Inline user message editing

Observed on 2026-10-16 on feat_gt_261016. No separate nexent-doc checkout is available. Inspected frontend tests and formal Case YAML did not expose an existing inline-message-edit contract; this is a lightweight bug design, not a new full chat SPEC.

## Scope and final behavior

The user message pencil enters assistant-ui's existing edit runtime. An inline, rounded multiline composer replaces the message display while editing. It starts with the original message text. Cancel or Escape discards edits; Send or Ctrl/Cmd+Enter uses the existing edit runtime and its message branching behavior. Plain Enter inserts a newline. The existing read-only/share restrictions remain in place. No backend route or persistence contract changes are included.

## Root cause and implementation

`frontend/app/[locale]/newchat/assistant-ui/thread.tsx` used the children render path of `ThreadPrimitive.Messages` without an edit composer. `ActionBarPrimitive.Edit` therefore changed runtime state without rendering an editor. Register `UserMessageEditComposer` with the library's message component dispatch so the library selects and scopes the edit composer. Reuse composer Input, Send and Cancel primitives rather than copying message text to the bottom composer. Keep the send button a non-submit button to avoid a second form submission after its primitive click handler.

## Acceptance and evidence

| Requirement | Intended proof | Current evidence |
| --- | --- | --- |
| Pencil shows the original text inline | Component regression and browser interaction | Implemented; interaction not executed |
| Cancel/Escape preserve original content and answer | Component regression and browser interaction | Uses existing runtime cancellation; not executed |
| Send submits once; empty drafts cannot send | Component regression and runtime journey | Uses existing runtime send guard; not executed |
| Multiline editing and responsive rounded layout | Component assertions and visual inspection | Implemented; browser visual verification pending |
| Read-only and share views do not expose an editor | Component regression | Registration gated by existing view flags; not executed |

No tests were added or run because they were not requested. Traditional frontend UT and higher-boundary interaction/visual verification remain outstanding; no formal D1-D5 pass is claimed. Python UT is not applicable to the frontend-only implementation. No existing formal Cases were modified or removed.

`npm run type-check` was run. It reports existing errors elsewhere in the checkout, including skill-space ref types and unavailable testing dependencies. No diagnostics referenced either changed product file. Formatting was applied to the two changed product files. This does not establish browser or model behavior.
