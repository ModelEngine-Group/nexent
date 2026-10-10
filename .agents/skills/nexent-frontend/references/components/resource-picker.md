# Resource picker drawers

Reuse `AddResourceDrawer` from `@/components/resource-picker/AddResourceDrawer` for resource association selection. Existing shared geometry is a right Ant Design drawer, width 760px, body padding 24px, vertical gap 16px, masked background, fixed close/confirm footer, and a scrollable content area. Keep the existing translated resourcePicker labels and shared visual tokens.

The default search row, selected chips, list header, pagination, and confirm button remain enabled. Existing controllers can provide `searchContent` (including null) and disable duplicate sections through `showSelection`, `showListHeader`, and `showPagination`. `title` accepts ReactNode for existing toolbar actions; `selectedTrailing` renders extra actions alongside chips. Hide confirm only when the owning controller applies selection immediately.

`AddModelDrawer` accepts optional `models`, ordered `selectedModelIds`, `onSelectionChange`, `disabled`, and `selectedTrailing`. Controlled selection emits remaining IDs in original order and appends newly chosen IDs; selected chips retain that order. Without controlled props, standalone selection stays local. The caller owns permissions, form synchronization, persistence, priority, and parameter overrides.

Agent knowledge selection opts into `KnowledgeBaseSelectorModal` with `presentation="drawer"`. Other consumers keep the modal default. Skill, tool, and child-Agent controllers reuse the shell while retaining richer filters, parameter/detail dialogs, dependencies, and relation metadata. Knowledge and child-Agent draft selections apply on confirmation; model, tool, and skill association timing remains owned by their existing controllers. Opening, closing, or rendering must never create a resource or save an association.
