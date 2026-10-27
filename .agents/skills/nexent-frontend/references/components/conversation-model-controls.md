# Conversation model controls lifetime

`frontend/features/model-controls/ConversationModelControlsProvider.tsx` owns the optional in-memory model-control cache for one ordinary Agent chat page. Mount it above chat loading and Agent landing views; key its owner by tenant/user identity. It is not a global singleton or backend persistence layer. Leaving/reloading the page starts a new owner.

`useConversationModelControls` keeps the existing tenant/user/Agent/thread session key and per-model reasoning, sampling and rejected-selection scopes. Consumers without this provider keep their local state ownership, including Workbench and creator callers. Changing ownership must not change selection/default resolution, validation, immutable turn snapshots, or wire serialization. An unavailable explicit model must still block sending instead of silently selecting another model.

The ordinary page uses `ConversationLoadingBoundary` to retain mounted chat content while history is pending. Hidden content is inert and the page passes `readOnly` to Chat. The existing localized loading status remains accessible outside the inert subtree. Do not replace the children conditionally, or let loading submit a message or alter model configuration.

When the first run returns a server conversation ID, bind it to the draft's original local thread key. A server-backed history entry resolves through that first binding, including edits made after the response. Register only new-conversation callbacks; existing histories must not be rebound. Duplicate and background callbacks must not replace the original anchor or another session's controls. The binding map shares the provider's account/page lifetime and does not copy or change turn snapshots or wire parameters. Callers without the ordinary page provider keep their local identity behavior.

Regression evidence belongs in `ConversationModelControls.test.tsx`, `ConversationModelThreadIdentity.test.tsx`, `ConversationLoadingBoundary.test.tsx`, and the cold/new-history journeys in `WB-CONTROLS-D4-003`.
