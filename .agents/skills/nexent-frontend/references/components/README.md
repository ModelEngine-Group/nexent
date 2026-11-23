# Component references

This directory contains component-level constraints and focused Markdown references for the Nexent frontend.

## How to use these references

1. Read [Components and UI](../components-ui.md) for the shared baseline.
2. Read [Component contracts](component-contracts.md) for the default component requirements.
3. Read the component-specific document that matches the component being changed:
   - [Font](font.md)
   - [Icon](icon.md)
   - [Style](style.md)
   - [Button](button.md)
   - [Drawer](drawer.md)
   - [Modal](modal.md)
   - [Card](card.md)
   - [Paginator](paginator.md)
   - [Input](input.md)
4. Read any additional component-specific document that matches the feature being changed.

Add a focused Markdown file here when a component has behavior or constraints that are easy to miss from the shared rules. Prefer one document per reusable component or coherent component family. Use lowercase kebab-case filenames, for example `agent-config-form.md` or `resource-card.md`.

Component references are guidance for implementation and review. They must not change existing HTTP contracts, localization keys, or product behavior unless the task explicitly requires that change.
