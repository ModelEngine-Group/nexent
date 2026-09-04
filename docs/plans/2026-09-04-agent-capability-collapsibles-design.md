# Agent Capability Collapsibles Design

## Goal

Show the Tools & Skills tab as two direct, independent collapsibles: Tools
first and Skills second.

## Selected design

Move the two existing capability views out of `AgentCapability`'s internal tab
control and render them as two `ConfigSection` instances in `agent-config.tsx`.
Extract the existing tool and skill view contents into separately exported
components, while `AgentCapability` keeps ownership of shared modal state and
data hooks.

The Tools collapsible opens by default; Skills is closed by default. An
NL2Agent focus request for either capability expands its matching collapsible.

## Alternatives

1. **Selected:** direct sibling collapsibles in the tab, with extracted view
   components. This avoids nesting an accordion within the existing outer
   section and preserves the application-wide section styling.
2. Replace the internal tabs with collapsibles inside `AgentCapability`. This
   leaves an unnecessary outer Tools & Skills collapsible and creates a third
   visual level.
3. Keep tabs and only rename their headers. This does not meet the requested
   interaction model.

## Validation

The frontend has no component-test runner configured. Validate through the
TypeScript compiler, targeted source review, and user interaction testing.
