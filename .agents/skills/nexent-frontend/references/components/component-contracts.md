# Component contracts

Use these constraints as the default contract for new or substantially changed frontend components. A more specific component reference may add stricter rules when the component requires them.

## Ownership and placement

Apply the [component decision workflow](../architecture.md#component-decision-before-implementation) before choosing where to implement a UI requirement; shared styling and capability gaps should be resolved in the appropriate existing or new common component before the business caller repeats them.

- Place feature-only components under `frontend/app/[locale]/{feature}/components/`.
- Follow the [three-layer architecture](../architecture.md#component-layers): reusable brand presentation and generic interactions belong in common; business conditions and operation implementations remain domain-owned. Prefer an existing applicable common component before using a primitive directly or repeating project styles.
- Keep feature-private components private to their feature. Do not import another feature's internal component; promote shared behavior instead.
- Keep route entries thin. A page should compose components and coordinate routing, authentication, and feature-level data rather than contain a large reusable UI implementation.

## Public API

- Define a named TypeScript props contract for project-owned reusable components. Preserve upstream-native prop types for managed basic controls.
- Keep the public API minimal and coherent. Prefer semantic props and callbacks over exposing internal state, DOM details, or implementation-specific wrappers.
- Use controlled behavior when the parent needs to own the value or lifecycle; otherwise keep transient state inside the component.
- Review an interface when it accumulates roughly 7 to 10 props, repeated pass-through props, or several unrelated concerns. Extract a focused component or group only a coherent concern.
- Preserve existing callers and payload contracts when changing a shared component. Make compatibility changes explicit instead of silently changing default behavior.

## Data, state, and side effects

- Keep API calls in `frontend/services/` and shared client data in the established React Query patterns.
- Keep reusable state and effects in `frontend/hooks/`; avoid putting feature-wide state into a presentational component's local state.
- Prefer passing already loaded data and explicit callbacks into reusable visual components. A component may own local interaction state, loading state, or validation when that ownership is clear.
- Provide meaningful loading, empty, disabled, and error states for asynchronous or data-dependent UI.
- Use `frontend/lib/logger.ts` for logging. Do not add direct `console.log` calls in new or changed components.

## Visual and interaction behavior

- Prefer shadcn/ui Radix basic controls. Common components must not import Ant Design; domain components migrate incrementally without expanding the legacy budget. Shared brand presentation, interaction defaults, layout and accessibility are valid common-component responsibilities; avoid wrappers that only rename or forward unchanged props.
- Use theme tokens or CSS variables and responsive layout primitives. Keep necessary component CSS colocated with the component.
- Use `lucide-react` for new icons; preserve legacy icon imports only in unmigrated consumers.
- Use common Modal and domain drawer shells over the basic Dialog/Sheet for shared content contracts. Legacy useConfirmModal consumers migrate with their domain. Destructive actions retain danger-button and warning-title treatment.
- Ensure keyboard focus, narrow-screen layout, disabled states, and error recovery remain usable when extracting or reusing a component.

## Copy, localization, and accessibility

- Localize all user-facing text through `useTranslation`; group descriptive keys by feature or namespace and follow the project's fallback behavior.
- Use `Trans` when translated content contains structure, links, emphasis, or other rich content.
- Keep labels, handlers, and accessible names consistent. Interactive controls must expose a meaningful label or accessible name, including icon-only controls.
- Do not hard-code user-facing copy in a reusable component when the text may need localization.

## Component documentation

For a reusable component with non-obvious behavior, document:

- purpose and intended scope;
- where it belongs and who owns its state;
- public props, callbacks, and important defaults;
- loading, empty, error, disabled, and destructive-action behavior;
- localization and accessibility requirements;
- styling or layout constraints; and
- related components, hooks, services, or translation namespaces.

Keep the document focused on decisions that an implementer or reviewer could otherwise miss. Update it when the component's contract changes.

## Shared resource descriptions

ResourceItem owns two-line description truncation and full-content Ant Design Tooltip behavior for tools, skills, knowledge and Workbench compatibility rows. Consumers must not add nested description tooltips for individual resource sources. Preserve renderDescription markup; use the full item description for tooltip content, falling back to the rendered description when no plain description exists. Empty descriptions produce no empty tooltip. Hovering never selects or persists a resource; action controls remain separate. MCP service headers use their existing standalone tooltip because they are not ResourceItem rows.
