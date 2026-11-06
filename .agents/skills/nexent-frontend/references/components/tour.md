# Explanatory tour

Use native Ant Design `Tour` directly in the owning feature. The agent creation guide owns its targets, localized copy, step state, previous/next/skip/finish actions and browser-local completion preference.

- Use the central brand theme for colors and body typography. Use native `styles`, `classNames` and documented component tokens only for required visual differences.
- Use native `placement`, `gap` and `scrollIntoViewOptions` for target alignment and scrolling. Start with built-in overflow adjustment; do not add DOM observers, translated panels/arrows or per-step CSS offsets without a demonstrated native limitation.
- Use native `closable`, `disabledInteraction`, `indicatorsRender` and `actionsRender` for the guide's interaction requirements. These options alone do not justify a common wrapper.
- Keep Escape dismissal, initial/final focus and browser-local completion handling in the owning guide. Dismissal must not save configuration or invoke business actions.
- Do not add a shared Tour component for a single feature. A future abstraction needs a concrete reusable interaction beyond native props and central theme defaults.
