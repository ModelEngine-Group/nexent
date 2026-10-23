# Conversation model controls lifetime

`frontend/features/model-controls/ConversationModelControlsProvider.tsx` owns the optional in-memory model-control cache for one ordinary Agent chat page. Mount it above chat loading and Agent landing views; key its owner by tenant/user identity. It is not a global singleton or backend persistence layer. Leaving/reloading the page starts a new owner.

`useConversationModelControls` keeps the existing tenant/user/Agent/thread session key and per-model reasoning, sampling and rejected-selection scopes. Consumers without this provider keep their local state ownership, including Workbench and creator callers. Changing ownership must not change selection/default resolution, validation, immutable turn snapshots, or wire serialization. An unavailable explicit model must still block sending instead of silently selecting another model.

The ordinary page uses `ConversationLoadingBoundary` to retain mounted chat content while history is pending. Hidden content is inert and the page passes `readOnly` to Chat. The existing localized loading status remains accessible outside the inert subtree. Do not replace the children conditionally, or let loading submit a message or alter model configuration.

Regression evidence belongs in `ConversationModelControls.test.tsx`, `ConversationLoadingBoundary.test.tsx`, and the cold-history journey in `WB-CONTROLS-D4-003`.
