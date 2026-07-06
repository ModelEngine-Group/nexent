# NL2AGENT Gap Merge Plan

## Goal

Close the implementation gaps between the current NL2AGENT changes and the original plan in
`C:\Users\deng_\.claude\plans\polymorphic-riding-bunny.md`.

## 1. Fix the Core ID Contract

- Change `POST /nl2agent/session/start` to return explicit IDs:

```json
{
  "nl2agent_agent_id": 123,
  "draft_agent_id": 456,
  "conversation_id": 789,
  "draft_name": "draft_abcd1234"
}
```

- Keep `agent_id` only if needed for compatibility, but avoid using it internally because it is ambiguous.
- In `start_session`, query the seeded `name="nl2agent"` agent and return its ID separately from the draft ID.
- Frontend entry buttons should navigate to:
  `/[locale]/chat?agent_id=<nl2agent_agent_id>&conversation_id=<conversation_id>&draft_agent_id=<draft_agent_id>`.

## 2. Pass Draft Context Into Agent Runs

- Add optional `draft_agent_id` to the chat run request model, likely `AgentRequest` in `backend/consts/model.py`.
- Update `conversationService.runAgent` to include `draft_agent_id` when present.
- Update `chatInterface.tsx` to read `draft_agent_id` and `conversation_id` from URL/session storage/local storage.
- Persist a small frontend mapping such as `nl2agentDraftByConversation:{conversation_id -> draft_agent_id}` so refresh/resume still has the draft ID.
- In `create_agent_config`, inject `draft_agent_id` into NL2AGENT tool metadata instead of the running NL2AGENT agent ID.

## 3. Use the Created Conversation

- Update chat initialization so the `conversation_id` from `start_session` becomes the selected conversation.
- Avoid creating a second conversation on first message when `conversation_id` is already supplied.
- Refresh or load the conversation list after navigation so the sidebar can display the newly created NL2AGENT conversation.

## 4. Wire the NL2AGENT Prompt YAML

- Add a branch in `create_agent_config` or `prepare_prompt_templates`:
  if `agent_info["name"] == "nl2agent"`, load `backend/prompts/nl2agent_system_prompt_en.yaml` or `_zh.yaml`.
- Render that YAML `system_prompt` as the actual agent prompt.
- Keep the fixture `duty_prompt` as a fallback only.
- Fix encoding for the Chinese YAML/docs if mojibake is actually present on disk.

## 5. Fix Local Resource Search

- In `recommend_local_resources`, change the synchronous call to `list_all_tools` into an awaited call:

```python
all_tools = await list_all_tools(tenant_id=tenant_id, labels=None)
```

- Filter tool sources to `{local, mcp, langchain}` so NL2AGENT builtin tools are not recommended back to the user.
- Consider excluding disabled or unavailable tools if `list_all_tools` returns them.

## 6. Fix Skill Binding

- For local skills, create or update `SkillInstance` rows for the draft agent using `SkillInstanceInfoRequest` and `SkillService.create_or_update_skill_instance` or `skill_db.create_or_update_skill_by_skill_info`.
- Do not treat already-installed tenant skills as official skills to reinstall.
- For web skill install, keep tenant-level install separate. After install, either tell the user to apply it locally or bind it immediately if that is the intended button behavior.

## 7. Fix Card Rendering

- Change markdown language extraction from:

```ts
/language-(\w+)/
```

to something that accepts hyphens:

```ts
/language-([^\s]+)/
```

- Add tests or a small component-level fixture for:
  - `nl2agent-local-resources`
  - `nl2agent-web-mcp`
  - `nl2agent-web-skills`
  - `nl2agent-finalize`

## 8. Wire Web MCP Install

- Add an NL2AGENT MCP install handler near the chat or markdown rendering boundary.
- Mount `AddMcpServiceModal` in the chat page or a wrapper component.
- Pass `onInstallMcp` into `tryRenderNl2AgentCard`.
- Map card fields to the modal's expected props, including `server_name` or `name`, `server_url` or `url`, transport, and source where supported.

## 9. Clean Up Finalize Flow

- Ensure `finalize_agent` always targets `draft_agent_id`.
- Decide whether finalization should remove the `draft_` prefix immediately or keep it hidden until publish.
- The original plan says "draft ready, review and publish"; the conservative choice is to keep it accessible by direct ID and only visible in the main list if product wants it visible before publish.
- Make `FinalizeCard` link to `/[locale]/agents?agent_id=<draft_agent_id>`.
- Ensure agent detail loading can fetch hidden drafts by direct ID.

## 10. Align Backend Routing and Seeding

- Confirm `seed_nl2agent_default_agent()` runs in every deployment path that needs it.
- It currently runs in `config_app` startup; if runtime can receive `/nl2agent/session/start` before config startup, add defensive seeding/query fallback.
- If multi-tenant support matters, seed per tenant or create the default NL2AGENT lazily for the authenticated tenant.

## 11. Tests

- Backend unit tests:
  - `start_session` returns both builder and draft IDs.
  - `recommend_local_resources` awaits `list_all_tools` and filters sources.
  - `apply_local_resources_batch` creates both `ToolInstance` and `SkillInstance`.
  - `finalize_agent` uses the draft ID.
- Frontend tests:
  - Agent Builder button stores or navigates with builder ID, draft ID, and conversation ID.
  - Markdown renderer handles hyphenated NL2AGENT fences.
  - Web MCP install callback is invoked.
- Add one regression test specifically for "draft ID must not equal running NL2AGENT agent ID."

## 12. Manual E2E Verification

1. Start backend and frontend.
2. Click Agent Builder.
3. Confirm URL or run payload has:
   - `agent_id = nl2agent`
   - `draft_agent_id = draft agent`
   - `conversation_id = created conversation`
4. Send a prompt.
5. Verify NL2AGENT asks clarifying questions and can call `search_local_resources`.
6. Verify cards render interactively.
7. Apply local tools and skills, then inspect DB rows for the draft agent.
8. Install a web MCP and confirm the modal opens.
9. Finalize and open the draft config page.
