# NL2Agent prompt confirmation

The feature-only `newchat/ui/prompt-generation-card.tsx` renders server-owned
`prompt_generation` cards. It preserves complete multiline text, offers an
expand/collapse preview, and follows the existing resource-card spacing, colors,
14px title and 12px body/button contract.

Pending cards support local editing with native AntD TextArea, preview and restore
generated content. Apply actions carry `card_id`, `prompt_revision` and the exact
edited `prompt` through the existing creator run endpoint. Cancel remains
identity-only. Reject blank edits and retain local text after rejection. Disable
duplicate submissions immediately, restore retry on HTTP rejection, and mark the
accepted operation read-only. Ordinary dialogue stays available while pending.

History outcomes come from parsed server cards. Only the latest proposal can
register as interactive; a later persisted prompt also disables old proposals.
Terminal cards remain readable. Full-creation steps display waiting/cancelled
facts without treating either as successful persistence or completion.

The backend owns authorization, original/binding revision checks, exact text
persistence and full-generation continuation. Native AntD buttons and semantic
tokens provide presentation. Strings live under `nl2agent.promptGeneration.*`.
Unit/component checks and `NL2A-PROMPT-D4-001` cover actions, retry, preview, narrow
layout and historical/superseded outcomes; D3 proves actual storage and MCP/SSE.
