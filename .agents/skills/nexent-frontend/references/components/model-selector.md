# Shared model selector

Workbench and current Agent chat (`/newchat`) use `ModelSelector` through the shared Composer. Model selection, deep thinking, effort and budget retain their existing callbacks and assistant-ui model context registration.

Both entry points derive available effort/budget controls from the selected model's supported capability, independent of saved/current thinking enablement. The switch controls activation only. Missing, unknown or unsupported effort capability must not fabricate generic levels. Preserve valid Agent/model/session defaults; resolve stale selections against supported values. Forward all existing ReasoningEffort IDs through callbacks and run configuration without aliasing high to xhigh. Automatic retains provider-default behavior and disabled thinking omits active reasoning overrides. Workbench's root generation configuration remains authoritative over ordinary-chat model context.

Use the shared Radix Select for effort options. Its SelectContent portal prevents clipping by the model popover; mark it with data-model-effort-popup so the model popover outside-interaction guard recognizes it as well as the advanced parameter panel. Keep the disabled empty state when no supported effort controls exist.

Use w-fit on the effort trigger so its width is just the selected text, chevron and standard padding/gap. Give the dropdown at least min-w-32 and preserve item pr-8 for the right-hand checkmark. Do not replace reserved indicator space with symmetric padding. End-align the nested effort dropdown and the convenience model panel so selection-label length does not shift their anchors; retain Radix collision handling and the compound Content's explicit alignment API.

`ModelSelector` renders Advanced settings below effort by default. Omit `parameterSettings` for frontend-only values isolated by `parameterSettingsScopeKey` and the selected model during this component's lifetime. Composer supplies the active thread scope and running/disabled guard. Controlled callers retain `value`, `defaultValue`, `onChange` and `scopeKey` ownership; Workbench keeps its existing parent state. Compound consumers can render `ModelSelector.AdvancedSettings` inside `ModelSelector.Content`.

Reuse `ModelParameterSettings` for integer levels 1–100, synchronized sliders/numeric fields, keyboard interaction and restoring defaults. Defaults are temperature 50 and Top P 90 from `const/modelParameterSettings.ts`. Disable editing while running, when the caller is disabled or when no matching model is selected.

Sampling values never enter `ModelSelectorModelContext`, generation/configuration requests or backend persistence. Future provider conversion remains an adapter responsibility. The legacy `/chat` route was removed on develop; current chat uses `/newchat`.
