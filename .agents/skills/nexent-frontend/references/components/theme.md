# Brand theme

`frontend/const/brand.ts` is the source for the approved Nexent Light palette, semantic roles, NEXENT_THEME, native button defaults and generated CSS variables. RootProvider applies these to the normal tree and legacy static portals. Do not add independent primary colors in nested providers. Context-bound App APIs remain preferred for new message/modal/notification code.

Default primary is brand-50 (#0067D1), hover brand-40 (#2E86DE), pressed brand-60 (#004EA8), disabled primary fill brand-20 (#8ABEF3), and selection surfaces brand-05 (#E6F2FD). Checked control accents and large selected surfaces are distinct roles. The base control radius is 4px; components with a separate specification, such as the 8px modal/card surface, retain that specification. Dark currently inherits Light brand roles; no independent Dark palette has been approved.

Native AntD components consume global/component tokens. Custom controls can use useToken or CSS variables such as --color-brand, --color-brand-hover, --color-brand-active and --color-select. Prefer semantic Tailwind colors to page-local hex values. AntD state tokens are explicitly mapped rather than relying solely on its seed-color algorithm to reproduce the brand palette. Shared defaults must preserve native danger, ghost, loading and disabled behavior.

Theme-covered styling does not require a common wrapper. Common is justified by reusable composition or interaction beyond native props and theme defaults. Preserve existing shadcn primitives where used, without mandating a library migration. See ../architecture.md#theme-and-common-ownership.
