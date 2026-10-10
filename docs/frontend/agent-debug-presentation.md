# Agent debug presentation

`AgentDebugPanel` owns transient conversation mode and clear actions; the Agent editor owns visibility, comparison and fullscreen layout. The panel consumes the existing draft store and run/stop adapters. Its mounted single and comparison runtimes retain conversations when hidden or resized. Switching Agents remounts the panel. Fullscreen restores the previous generation and version pane visibility on exit or close.

`Thread` and `Composer` accept `debugLayout`, defaulting to `false`. This opt-in presentation is intended for the Agent editor only. `Thread` also accepts `emptyFooterContent` (visible only before messages) and `footerContent` (always visible). Existing welcome content remains supported. These slots do not initiate requests or change runtime behavior. Default chat and generation callers retain their existing presentation.

Debug layout uses the measured 488px pane and 440px inner content at a 1920px desktop viewport, with 24px padding, a 164px composer, and 40px controls. The pane contracts at narrower widths; the thread viewport scrolls while the composer remains accessible. Attachments may increase composer height. Welcome names and questions may wrap rather than being truncated or silently discarded.

The question slot scrolls when stored questions exceed the available height. Its cap reserves the measured 28px header, 168px minimum welcome, 214px composer/disclaimer area and 16px gap. This preserves the three-question source geometry while keeping long legacy lists and composer controls reachable.

`AgentDebugWelcome` renders draft name, greeting (description fallback), and avatar (uploaded icon with default avatar fallback). `AgentDebugSuggestions` receives immutable questions and invokes `onSelect` with the exact question; the runtime owner fills the composer without auto-sending. Empty questions omit the suggestions section.

The header uses Ant Design controls and an accessible localized dropdown for execution/planning, single/comparison, and close. Clear cancels the active run and resets the active conversation while retaining model selection. Sending, attachment handling, disabled state and stop behavior stay in the existing assistant-ui composer/runtime. Configuration read-only state does not disable chat actions.

All static labels use the `common` translation namespace (`agent.debug.*` and existing composer labels). Question buttons support keyboard focus; icon controls expose localized accessible names. Source font files and exact gradient geometry are unavailable; their limitations and all inspector measurements are recorded in [the design handoff](../handoffs/2026-10-09-agent-debug-high-fidelity-analysis.md).
