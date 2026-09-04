# Agent Configuration Tab Layout Design

## Goal

Reorganize the agent configuration UI into three tabs in this order: Basic
Settings, Tools & Skills, and Advanced Settings.

## Selected approach

Use the existing i18n, section, and focus-routing conventions. Add a dedicated
`tools_skills` tab, move the existing tools and skills collapsible into it, and
place the existing guardrail collapsible at the end of Advanced Settings. The
Security Settings tab will be removed entirely.

## Alternatives considered

1. **Selected:** update the UI, tab type, focus routing, and English/Chinese
   translations together. This keeps direct navigation to a section correct.
2. Move only the visible collapsibles. This risks routing a focus request to a
   removed or incorrect tab.
3. Hard-code the new Chinese tab label. This would break the existing English
   localization.

## Behavior

- Tools and skills appears only in the second tab.
- Guardrail appears only at the end of Advanced Settings.
- Focus requests for `tools_skills` activate the second tab; `guardrail`
  activates Advanced Settings.
- Existing section state, actions, and rendered component instances remain
  unchanged.

## Verification

Use the frontend TypeScript check and formatting check. The repository has no
configured unit-test runner for this component, so the change will also be
validated by reviewing the tab and focus-routing mappings.
