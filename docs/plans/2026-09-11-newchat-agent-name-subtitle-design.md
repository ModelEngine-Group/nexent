# Newchat Agent Name Subtitle Design

## Context

After a user selects an agent and sends messages in `/newchat`, the header shows the conversation title on its first line and a fixed conversation label on its second line. The fixed label does not identify the agent answering the conversation.

## Decision

Keep the first-line title unchanged. For populated, non-embedded conversations, render the selected agent's existing `displayName` in the second-line subtitle. `displayName` already resolves `agent.display_name` first and falls back to `agent.name`.

## Scope and verification

The change is limited to the `Thread` header and a source-level regression test. Empty conversations, embedded threads, sharing controls, and conversation-title generation remain unchanged. The regression test verifies that the populated-conversation subtitle uses `displayName`.
