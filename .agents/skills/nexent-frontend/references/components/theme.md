# Brand theme

`frontend/const/brand.ts` is the source for the approved Nexent Light palette, semantic roles, NEXENT_THEME, native button defaults and generated CSS variables. RootProvider applies these to the normal tree and legacy static portals. Do not add independent primary colors in nested providers. Context-bound App APIs remain preferred for new message/modal/notification code.

Default primary is brand-50 (#0067D1), hover brand-40 (#2E86DE), pressed brand-60 (#004EA8), disabled primary fill brand-20 (#8ABEF3), and selection surfaces brand-05 (#E6F2FD). Checked control accents and large selected surfaces are distinct roles. Dark currently inherits Light brand roles; no independent Dark palette has been approved.

Native AntD components consume global/component tokens. Custom controls can use useToken or CSS variables such as --color-brand, --color-brand-hover, --color-brand-active and --color-select. Prefer semantic Tailwind colors to page-local hex values. AntD state tokens are explicitly mapped rather than relying solely on its seed-color algorithm to reproduce the brand palette. Shared defaults must preserve native danger, ghost, loading and disabled behavior.

Theme-covered styling does not require a common wrapper. Common is justified by reusable composition or interaction beyond native props and theme defaults. Preserve existing shadcn primitives where used, without mandating a library migration. See ../architecture.md#theme-and-common-ownership.

## Radius roles

BRAND_RADII supplies both AntD component mappings and shared CSS variables.

| Role | Value | Use |
| --- | --- | --- |
| radius-none | 0px | Side navigation |
| radius-xs | 2px | Checkboxes and dropdown option states |
| radius-base | 4px | Buttons, inputs, dropdown panels, pagination, tooltips/popovers, tags, counters and alerts |
| radius-lg | 8px | Modals and cards |
| radius-full | Fully rounded (9999px in CSS) | Scrollbars, sliders, switches and progress bars |

Use --radius-none/xs/base/lg/full or rounded-none/xs/base/lg/full. --radius-control remains an alias for base; legacy sm/md classes map to base for compatibility, not to AntD's size names. Large controls still use base; surface components use lg. Select popup.listItem uses xs independently of the base control/panel. Badge counters use base while dot/status indicators remain circular. Do not collapse every role to 4px or derive component ownership solely from its CSS size name.

## Body typography

Use the shared body size roles in [Font](font.md#body-sizes). BRAND_BODY_FONT_SIZES maps body-1/2/3 to AntD fontSizeSM/fontSize/fontSizeLG and CSS variables; body-2 (14px) is the application default. Use text-body-1/2/3 for custom content. Keep native size variants and documented heading roles rather than forcing all component text to the default.
