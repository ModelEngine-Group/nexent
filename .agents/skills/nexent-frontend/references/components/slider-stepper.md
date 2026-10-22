# Sampling slider and stepper

Use `components/common/SliderStepper` for the shared Agent and model sampling control. Its parent owns the optional numeric value and receives changes; the displayed fallback does not emit a change or create a stored override. Clearing emits `undefined`. Explicit zero remains a value.

Pass a localized label, numeric fallback, bounds and step. Temperature uses 0–2 and Top P 0–1, both with step 0.1. Pointer dragging, numeric entry, increment/decrement and arrow/Home/End keys share the same bounds. Disabled controls cannot emit changes. Preserve the existing Agent control's segmented track and default 112×32px numeric stepper. Model advanced configuration places temperature and Top P side by side in its existing two-column grid and sets `compact` for an 88×32px numeric stepper with an 8px track gap.

Model configuration passes `showFallbackValue={false}` so an unset numeric input remains blank without a placeholder. The fallback remains the slider and stepper interaction starting point, without emitting a stored value on mount. The default is `true` to preserve existing Agent parameter controls. Configured values, including zero, always remain visible.

When the fallback is hidden and the value is unset, render only the gray track and ticks, without a filled segment, thumb or numeric ARIA value. Explicit input, track interaction or stepper/keyboard changes supply a configured value and restore the normal visual state. Clearing returns to the empty state.
