# UI specification

## Color sources and use

This document defines UI color roles, chart and company palettes, functional-color Light states, usage constraints, and Tailwind translations. Keep these categories together in this document.

| Category | Reference |
| --- | --- |
| Usage principles | [Applying the specification](#applying-the-specification) |
| Variable definitions and integration | [Shared CSS variables](#shared-css-variables) |
| Software-product emphasis and interaction states | [Highlight colors](#highlight-colors) |
| Text hierarchy | [Text colors](#text-colors) |
| Icon hierarchy and states | [Icon colors](#icon-colors) |
| Default borders, interaction borders and separators | [Border colors](#border-colors) |
| Container surfaces and mask | [Background colors](#background-colors) |
| Component fills | [Fill colors](#fill-colors) |
| Error, alert, warning, success, information and ineffective status | [Functional colors](#functional-colors) |
| Chart palettes, tail color and gradients | [Chart specification](#chart-specification) |
| Chromatic and neutral scales | [Company palette](#company-palette) |
| Auxiliary colors and priority | [Company auxiliary colors](#company-auxiliary-colors) |

This document specifies Light-theme configurations only. Typography sizes, spacing, radius, shadows, animation, and breakpoints follow separately documented rules.

### Applying the specification

- Choose the semantic role first. Tokens with identical values remain distinct roles; for example, primary text and primary icons are both `#191919`, but should remain independently themeable.
- The application must define every semantic color CSS variable in shared global styles and import them centrally. Align existing same-name variables with this specification and add missing variables. Components and pages must consume variables instead of HEX/RGB literals.
- Every semantic token must map to a same-name CSS variable: `color-brand` → `--color-brand`. Existing matching Tailwind `@theme` aliases may be reused only when backed by these shared variables. Value columns define variables; Tailwind columns show variable references.
- Percentages in the tables are color alpha, not whole-component opacity. For example, `#191919` at 5% is `rgb(25 25 25 / 5%)`; use `bg-[var(--color-hover)]`, not `opacity-5`, which would fade text, icons, and children too. Do not replace an alpha color with its white-background composite.
- The specification labels a selected state as `focus` and a pressed state as `active`. Preserve this distinction: represent persistent selection with the component's selected/checked/ARIA state; use `:active` for pressing. Keyboard `:focus-visible` still needs a visible indicator and is not itself persistent selection. These state mappings guide implementation.
- Check enabled, hover, selected, pressed, and disabled states where specified. Disabled styling must accompany the control's actual disabled semantics; hover/active styles should not override disabled appearance.
- The palette alone does not establish accessibility conformance. Check actual foreground/background pairings and retain semantic labels/icons for status; if a required pairing conflicts with an applicable contrast requirement, report the conflict rather than silently changing the supplied palette or claiming it passes.

### Shared CSS variables

Shared variable definitions are provided in [color-tokens.css](color-tokens.css). Integrate this file into the existing global stylesheet entry point and import it once. This specification asset does not claim that the application integration is already complete.

- `--palette-<hue>-<shade>`: raw company palette, for example `--palette-blue-20`.
- `--aux-<color>`: company auxiliary colors, for example `--aux-orange`.
- `--color-<role>`: semantic colors consumed by components, pages, and charts, for example `--color-error-subtler`. Keep independent variables for distinct roles even when values match.
- Alpha roles store the complete `rgb(... / ...%)` value; do not apply alpha again at the usage site.
- Semantic variables should reference their corresponding `--palette-*` variables to avoid duplicate solid values. Complete alpha colors and confirmed exceptional mappings may be defined directly. Keep raw HEX/RGB definitions in the shared CSS.
- SVG/Canvas variable consumption, palette switching, and series capacity follow [Chart specification](#chart-specification).

```css
:root {
  --color-brand: var(--palette-brand-50);
  --color-error-subtler: var(--palette-red-05);
  --color-hover: rgb(25 25 25 / 5%);
}

.status-error {
  color: var(--color-error);
  background-color: var(--color-error-subtler);
}
```

This excerpt requires the complete variable file. This document defines design meaning and target values; the companion CSS defines executable variables. Update both files and both language versions together; neither silently overrides the other.

## Highlight colors

Software products use brand-50 as their default emphasis for buttons, text links, and key actions. Use the explicit state variables below rather than deriving new values.

| Semantic token | Palette shade | Value | Usage / state |
| --- | --- | --- | --- |
| `color-brand` | brand-50 | `#0067D1` | Default emphasis |
| `color-brand-hover` | brand-40 | `#2E86DE` | Hover |
| `color-brand-focus` | brand-50 | `#0067D1` | Selected |
| `color-brand-active` | brand-60 | `#004EA8` | Pressed |
| `color-brand-disabled` | brand-20 | `#8ABEF3` | Disabled |

Tailwind value translation for a filled primary action:

```text
bg-[var(--color-brand)] enabled:hover:bg-[var(--color-brand-hover)] enabled:active:bg-[var(--color-brand-active)] disabled:bg-[var(--color-brand-disabled)]
```

Use `data-[selected=true]:bg-[var(--color-brand-focus)]` or the component's equivalent selected-state binding for selection. For text links use the corresponding `text-*` color utilities instead of a background. The specification does not define a separate focus-ring width or geometry.

## Text colors

Establish text hierarchy through color even when text size and weight are equal.

| Semantic token | Palette shade | Value | Usage | Tailwind value translation |
| --- | --- | --- | --- | --- |
| `color-text-primary` | gray-90 | `#191919` | Primary text | `text-[var(--color-text-primary)]` |
| `color-text-secondary` | gray-50 | `#777777` | Secondary text | `text-[var(--color-text-secondary)]` |
| `color-text-placeholder` | gray-30 | `#AEAEAE` | Placeholder text | `placeholder:text-[var(--color-text-placeholder)]` |
| `color-text-disabled` | gray-20 | `#C9C9C9` | Disabled text | `disabled:text-[var(--color-text-disabled)]` |
| `color-text-inverse` | gray-0 | `#FFFFFF` | Inverse text | `text-[var(--color-text-inverse)]` |

Use inverse text on an appropriate contrasting surface. Placeholder color is a role, not a substitute for a visible input label.

## Icon colors

Action icons often accompany text; match the overall icon color hierarchy to the text hierarchy.

| Semantic token | Palette shade | Value | Usage / state | Tailwind value translation |
| --- | --- | --- | --- | --- |
| `color-icon-primary` | gray-90 | `#191919` | Primary icon | `text-[var(--color-icon-primary)]` |
| `color-icon-secondary` | gray-50 | `#777777` | Secondary icon | `text-[var(--color-icon-secondary)]` |
| `color-icon-tertiary` | gray-40 | `#939393` | Tertiary icon | `text-[var(--color-icon-tertiary)]` |
| `color-icon-placeholder` | gray-30 | `#AEAEAE` | Placeholder icon | `text-[var(--color-icon-placeholder)]` |
| `color-icon-disabled` | gray-20 | `#C9C9C9` | Disabled icon | `text-[var(--color-icon-disabled)]` |
| `color-icon-inverse` | gray-0 | `#FFFFFF` | Inverse icon | `text-[var(--color-icon-inverse)]` |
| `color-icon-hover` | brand-40 | `#2E86DE` | Hover | `text-[var(--color-icon-hover)]` |
| `color-icon-focus` | brand-50 | `#0067D1` | Selected | `text-[var(--color-icon-focus)]` |
| `color-icon-active` | brand-60 | `#004EA8` | Pressed | `text-[var(--color-icon-active)]` |

These utilities assume SVG `stroke`/`fill` uses `currentColor`. Apply state variants on the interactive control or through its group/state bindings; a decorative SVG need not become a separate hover or keyboard target.

## Border colors

Borders and separators organize information regions and provide interaction feedback.

| Semantic token | Palette shade | Value | Usage / state | Tailwind value translation |
| --- | --- | --- | --- | --- |
| `color-border` | gray-20 | `#C9C9C9` | Default border | `border-[var(--color-border)]` |
| `color-border-hover` | gray-90 | `#191919` | Hover border | `border-[var(--color-border-hover)]` |
| `color-border-focus` | brand-50 | `#0067D1` | Selected border | `border-[var(--color-border-focus)]` |
| `color-border-disabled` | gray-20 | `#C9C9C9` | Disabled border | `border-[var(--color-border-disabled)]` |
| `color-border-separator` | gray-10 | `#DFDFDF` | Separator | `border-[var(--color-border-separator)]` |
| `color-border-separator-subtle` | gray-05 | `#F3F3F3` | Subtle separator | `border-[var(--color-border-separator-subtle)]` |

Hover border is dark neutral, not brand blue. Use the default width and style below unless a component explicitly specifies otherwise; retain separately documented radius. Map selected/focused input presentation through the component's actual state contract.

### Default border

- Color: `#c9c9c9`.
- Width: `1px`.
- Style: `solid`.

Tailwind CSS:

```text
border border-solid border-[var(--color-border)]
```

## Background colors

Neutral surfaces at different depths fill page containers.

| Semantic token | Palette shade | Value | Usage | Tailwind value translation |
| --- | --- | --- | --- | --- |
| `color-bg-1` | gray-05 | `#F3F3F3` | Page background | `bg-[var(--color-bg-1)]` |
| `color-bg-2` | gray-0 | `#FFFFFF` | Side navigation / sliding panel | `bg-[var(--color-bg-2)]` |
| `color-bg-3` | gray-0 | `#FFFFFF` | Sliding panel | `bg-[var(--color-bg-3)]` |
| `color-bg-4` | gray-0 | `#FFFFFF` | Dropdown panel / popup | `bg-[var(--color-bg-4)]` |
| `color-bg-5` | gray-0 | `#FFFFFF` | White card | `bg-[var(--color-bg-5)]` |
| `color-bg-6` | gray-20 at 20% | `rgb(201 201 201 / 20%)` | Card with tinted background | `bg-[var(--color-bg-6)]` |
| `color-bg-mask` | gray-90 at 30% | `rgb(25 25 25 / 30%)` | Mask / overlay | `bg-[var(--color-bg-mask)]` |

The duplicate white values are intentional semantic roles. Keep the two sliding-panel roles; the specification does not define a further distinction between `color-bg-2` and `color-bg-3`. Mask alpha applies to the overlay background, not the dialog contents.

## Fill colors

Component fills distinguish interaction states.

| Semantic token | Palette shade | Value | Usage | Tailwind value translation |
| --- | --- | --- | --- | --- |
| `color-hover` | gray-90 at 5% | `rgb(25 25 25 / 5%)` | General hover | `bg-[var(--color-hover)]` |
| `color-select` | brand-05 | `#E6F2FD` | General selected state | `bg-[var(--color-select)]` |
| `color-table-header` | gray-90 at 5% | `rgb(25 25 25 / 5%)` | Table header background | `bg-[var(--color-table-header)]` |
| `color-table-zebra` | gray-40 at 5% | `rgb(147 147 147 / 5%)` | Table zebra background | `bg-[var(--color-table-zebra)]` |
| `color-fill` | gray-90 at 5% | `rgb(25 25 25 / 5%)` | Unstarted step, unselected radio, image/file upload default fill | `bg-[var(--color-fill)]` |
| `color-fill-subtle` | gray-0 | `#FFFFFF` | Input and similar controls: white fill, visually unfilled on white | `bg-[var(--color-fill-subtle)]` |
| `color-fill-disabled` | gray-10 | `#DFDFDF` | Disabled fill without an outline: radio/checkbox, pagination, scrollbar, default label | `bg-[var(--color-fill-disabled)]` |
| `color-fill-disabled-subtle` | gray-90 at 5% | `rgb(25 25 25 / 5%)` | Disabled fill with an outline: standard button, input, search field, selector | `bg-[var(--color-fill-disabled-subtle)]` |

Keep outlined and unoutlined disabled fills distinct. The white `color-fill-subtle` value is opaque, even when it visually blends into a white surface.

## Functional colors

### Usage and attention overview

This overview describes usage and attention only; it does not duplicate token values. Functional-color configurations are maintained in the Light state tables below.

| Category | Usage | Attention |
| --- | --- | --- |
| Error | Express errors or failures | High |
| Alert | Express alerts; pair with icons/text | High |
| Warning | Express reminders; pair with icons/text | High |
| Success | Express success | Medium |
| Information | Express primary/secondary information | Medium |
| Ineffective status | Express ineffective/inactive status; distinct from disabled controls | Unspecified |

Keep orange alert distinct from yellow warning. Low-attention error, alert, warning, success, and generic information colors use `subtler` (shade 05); `subtle` retains the lighter variant configuration. Ineffective status follows its separate base `color-none` and pale `color-none-subtle` convention; do not add `color-none-subtler`.

### Functional-color Light state specifications

Each token is defined once in the state tables below. Generic and tiered information tokens may coexist; matching values do not require merging, and distinct roles are not automatically aliases. Primary information has no specified hover, pressed, or disabled values; do not derive them from secondary states.

#### Error states

| Semantic token | Usage / state | Light palette / value |
| --- | --- | --- |
| `color-error` | Error | red-50 / `#E02128` |
| `color-error-hover` | Hover | red-40 / `#E7434A` |
| `color-error-active` | Pressed | red-60 / `#C7000B` |
| `color-error-disabled` | Disabled | red-10 / `#FABDC1` |
| `color-error-subtle` | Subtle | red-20 / `#F59297` |
| `color-error-subtler` | Subtler | red-05 / `#FEE7E8` |

#### Alert states

| Semantic token | Usage / state | Light palette / value |
| --- | --- | --- |
| `color-alert` | Alert | orange-50 / `#F4840C` |
| `color-alert-hover` | Hover | orange-40 / `#F69E39` |
| `color-alert-active` | Pressed | orange-60 / `#C76207` |
| `color-alert-disabled` | Disabled | orange-05 / `#FEF5E8` |
| `color-alert-subtle` | Subtle | orange-20 / `#FCCE92` |
| `color-alert-subtler` | Subtler | orange-05 / `#FEF5E8` |

#### Warning states

| Semantic token | Usage / state | Light palette / value |
| --- | --- | --- |
| `color-warning` | Reminder/warning | yellow-50 / `#FCC800` |
| `color-warning-hover` | Hover | yellow-40 / `#FCD72E` |
| `color-warning-active` | Pressed | yellow-60 / `#D19F00` |
| `color-warning-disabled` | Disabled | yellow-10 / `#FEF8B8` |
| `color-warning-bold` | Strong emphasis | yellow-80 / `#614500` |
| `color-warning-subtle` | Subtle | yellow-20 / `#FEF08A` |
| `color-warning-subtler` | Subtler | yellow-05 / `#FEFCE0` |

#### Success states

| Semantic token | Usage / state | Light palette / value |
| --- | --- | --- |
| `color-success` | Success | mint-40 / `#09AA71` |
| `color-success-hover` | Hover | mint-40 / `#36C18D` |
| `color-success-active` | Pressed | mint-60 / `#058358` |
| `color-success-disabled` | Disabled | mint-10 / `#BCF2DB` |
| `color-success-subtle` | Subtle | mint-20 / `#8FE5C2` |
| `color-success-subtler` | Subtler | mint-05 / `#E7FBF2` |

The default success color follows the user-confirmed `mint-40 / #09AA71` mapping dated 2026-11-05. This explicit semantic-token mapping does not change the raw company palette, where mint-40 remains `#36C18D`; do not overwrite that palette or rederive success from the shade name.

#### Information states

- Use `color-info`, `color-info-subtle`, and `color-info-subtler` for ordinary information without a primary/secondary hierarchy.
- Use `color-info-primary*` and `color-info-secondary*` when a screen needs an explicit information hierarchy.
- Choose the semantic group before the state. Matching values do not make roles interchangeable. The `subtle` suffix does not imply one shade across every group; use the table values.

| Semantic token | Usage / state | Light palette / value |
| --- | --- | --- |
| `color-info` | Generic information | blue-50 / `#2070F3` |
| `color-info-subtle` | Subtle generic information | blue-20 / `#B0BFFD` |
| `color-info-subtler` | Subtler generic information; low attention | blue-05 / `#EEF3FE` |
| `color-info-primary` | Primary information | blue-50 / `#2070F3` |
| `color-info-primary-subtle` | Subtle primary information | blue-30 / `#8CA3FA` |
| `color-info-primary-subtler` | Subtler primary information | blue-05 / `#EEF3FE` |
| `color-info-secondary` | Secondary information | blue-30 / `#8CA3FA` |
| `color-info-secondary-hover` | Secondary hover | blue-20 / `#B0BFFD` |
| `color-info-secondary-active` | Secondary pressed | blue-40 / `#668CF7` |
| `color-info-secondary-disabled` | Secondary disabled | blue-10 / `#D0D8FD` |
| `color-info-secondary-subtle` | Subtle secondary information | blue-05 / `#EEF3FE` |

#### Ineffective-status states

These describe ineffective/inactive status (失效); use the disabled entry only for this role's disabled state, not as a replacement for every disabled-control token.

| Semantic token | Usage / state | Light palette / value |
| --- | --- | --- |
| `color-none` | Ineffective status | gray-30 / `#AEAEAE` |
| `color-none-subtle` | Subtle | gray-05 / `#F3F3F3` |
| `color-none-hover` | Hover | gray-20 / `#C9C9C9` |
| `color-none-active` | Pressed | gray-40 / `#939393` |
| `color-none-disabled` | Disabled | gray-10 / `#DFDFDF` |

### Compatibility naming

- Normalize legacy `color-erroe-subtle` to `color-error-subtle`.
- Normalize legacy `color-warning-blod` to `color-warning-bold`.
- Normalize legacy secondary-role spelling `seconday` to `secondary`.
- These are documentation naming conventions, not completed code migrations; inspect existing callers before adding aliases or renaming tokens.

### Theme and Tailwind translation

Choose text, background, or border usage from the semantic role and component contract. Follow [Shared CSS variables](#shared-css-variables) for integration.

Consume alert fill variables as follows:

```text
bg-[var(--color-alert)] enabled:hover:bg-[var(--color-alert-hover)] enabled:active:bg-[var(--color-alert-active)] disabled:bg-[var(--color-alert-disabled)]
```

## Chart specification

### Default chart palette

Choose colors by data categories or dimensions. Prefer the following six colors, in order from left to right, for categorical chart series.

| Semantic token | Palette token | Value | Tailwind value translation |
| --- | --- | --- | --- |
| `color-chart-1` | blue-50 | `#2070F3` | `fill-[var(--color-chart-1)]` / `stroke-[var(--color-chart-1)]` |
| `color-chart-2` | green-50 | `#62B42E` | `fill-[var(--color-chart-2)]` / `stroke-[var(--color-chart-2)]` |
| `color-chart-3` | indigo-50 | `#715AFB` | `fill-[var(--color-chart-3)]` / `stroke-[var(--color-chart-3)]` |
| `color-chart-4` | cyan-50 | `#2CB8C9` | `fill-[var(--color-chart-4)]` / `stroke-[var(--color-chart-4)]` |
| `color-chart-5` | orange-40 | `#F69E39` | `fill-[var(--color-chart-5)]` / `stroke-[var(--color-chart-5)]` |
| `color-chart-6` | brand-30 | `#5CA2E9` | `fill-[var(--color-chart-6)]` / `stroke-[var(--color-chart-6)]` |

These colors apply to ring/donut charts, grouped and stacked bars, and line charts. For SVG, use fill for solid marks and stroke for lines. Bind color consistently to category identity across charts rather than reassigning it when data order changes.

### Tail color

For ring charts and stacked bars needing a tail color, use `--color-chart-tail`, mapped to blue-70 `#1B3F86`. Depending on the business scenario, replace the final series color; when seven categories are needed, the seventh may explicitly use the tail after the default six. The tail is excluded from `--chart-series-count`, is never appended automatically, and does not automatically extend four-color palettes. Design additional distinguishable encodings for more categories rather than cycling indistinguishable colors.

### Accessible chart colors

This darker alternative is intended to improve recognition for people with limited color perception. It uses the same chart roles and order as the default palette; select one palette consistently for the relevant chart context.

| Semantic token | Palette token | Value |
| --- | --- | --- |
| `color-chart-1` | blue-60 | `#1F55B5` |
| `color-chart-2` | green-60 | `#488E20` |
| `color-chart-3` | indigo-60 | `#5531EB` |
| `color-chart-4` | cyan-60 | `#1C94A4` |
| `color-chart-5` | orange-60 | `#C76207` |
| `color-chart-6` | brand-40 | `#2E86DE` |

Contrast requirements: Under [WCAG 1.4.3](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html), ordinary text needs 4.5:1; large text (at least 18pt regular or 14pt bold) needs 3:1. Under [WCAG 1.4.11](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html), meaningful graphical parts and control/state cues generally need 3:1 against adjacent colors, independent of a 24px cutoff. The palette name alone does not establish compliance. Measure actual pairs, including adjacent segments and backgrounds, and use labels, shapes, line styles, or patterns when color alone cannot distinguish the data.

### Extended chart palettes

For business-specific alternatives, use an alternating `50-40-50-40-…` shade pattern and replacement of hues. The sequences below correspond to selectors `extended-1`, `extended-2`, and `extended-3`:

| Alternative | Ordered palette tokens | Ordered values |
| --- | --- | --- |
| 1 | mint-50, indigo-40, cyan-50, purple-40 | `#09AA71`, `#8E81F4`, `#2CB8C9`, `#BF68FA` |
| 2 | indigo-50, yellow-40, blue-50, green-40 | `#715AFB`, `#FCD72E`, `#2070F3`, `#87C859` |
| 3 | purple-50, green-40, cyan-50, orange-40 | `#B62BF7`, `#87C859`, `#2CB8C9`, `#F69E39` |

Alternative 1 explicitly uses cyan-50 in its third position; retain the documented examples rather than forcing a different shade to regularize the pattern. These are alternatives to the default series palette, not additional status meanings.

### Palette switching and variable consumption

Set `data-chart-palette` explicitly on each chart container. The companion CSS includes the following local overrides; charts continue to consume the same `--color-chart-1` and related variables after switching.

| Palette value | Series colors | Rule |
| --- | --- | --- |
| `default` | 6 | Default palette; also resets a chart from another palette |
| `accessible` | 6 | Accessible alternative; actual contrast still requires checking |
| `extended-1` | 4 | Extended alternative 1 |
| `extended-2` | 4 | Extended alternative 2 |
| `extended-3` | 4 | Extended alternative 3 |

- `--chart-series-count` is palette capacity, not the number of data categories. Four-color palettes set roles 5 and 6 to `initial`, preventing inheritance of stale six-color values.
- Select a palette with enough capacity for the data. For more than four categories, choose a six-color palette or explicitly design an extension; do not mix in default colors, cycle colors, or append the tail automatically.
- SVG directly consumes `var(--color-chart-1)`. Canvas/chart libraries read the resolved value using `getComputedStyle(chartContainer).getPropertyValue("--color-chart-1").trim()`. Read only roles within `--chart-series-count`.
- After a palette switch, reread colors and invoke the chart instance's existing update API; CSS variable changes do not repaint Canvas automatically.
- Avoid nesting one palette container inside another. Give separate charts their own attributes so they do not change each other's palette.

### Gradient rules

- In ToB charts, prioritize accurate data interpretation and avoid gradients because visual variation may distort reading.
- In ToC charts, gradients may be used when tied to business meaning, such as a gauge indicating a trend or proximity to a warning interval; do not use them solely as decoration.
- For a single hue, select its `30` and `50` shades. Examples: brand-30 `#5CA2E9` → brand-50 `#0067D1`; orange-30 `#F9B766` → orange-50 `#F4840C`. Gradient direction follows the encoded meaning; no CSS angle is mandated.
- A neighboring-hue gradient may use three shade-`50` stops: blue-50 `#2070F3` → purple-50 `#B62BF7` → red-50 `#E02128`. Choose hues with neighboring angles below 60° on the hue circle. This three-stop combination is an example, not a requirement for every gradient.
- For SVG chart gradients, define gradient stops and use `fill="url(#…)"` or `stroke="url(#…)"`; Tailwind fill/stroke utilities can reference that paint server. For CSS surfaces, use the project's supported gradient syntax with the same explicit stops. Reference palette variables for stops, for example `stop-color: var(--palette-blue-50)`, instead of repeating HEX values in components. Define chart scales, alert thresholds, stop percentages, and interpolation models separately from business requirements.

## Company palette

These palettes extend the company colors for digital interfaces. Each hue has ten named shades (`05`, `10`, `20`, …, `90`), ordered light to dark; white and black are the endpoints. Names use the English hue plus shade, such as `red-50`; `05` is the lightest and `90` the darkest hue shade. Normalize color-name capitalization to lowercase without conflating **blue** and **brand**.

### Chromatic palette

| Shade | rose | red | orange | yellow | green | mint | cyan | blue | indigo | purple | pink | brand |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 05 | `#FEE5F2` | `#FEE7E8` | `#FEF5E8` | `#FEFCE0` | `#F2FBE9` | `#E7FBF2` | `#E8FCFD` | `#EEF3FE` | `#EEEEFE` | `#F7EDFE` | `#FDE6FC` | `#E6F2FD` |
| 10 | `#FCC3E0` | `#FABDC1` | `#FDE2BD` | `#FEF8B8` | `#DFF4CC` | `#BCF2DB` | `#C9F6F9` | `#D0D8FD` | `#D5D3FD` | `#E8CFFE` | `#F9C5F6` | `#B8D9F9` |
| 20 | `#F99AC7` | `#F59297` | `#FCCE92` | `#FEF08A` | `#C6E9A8` | `#8FE5C2` | `#A4ECF1` | `#B0BFFD` | `#BFB9FA` | `#D9B1FD` | `#F39DEC` | `#8ABEF3` |
| 30 | `#F470AB` | `#EE696F` | `#F9B766` | `#FDE55C` | `#A8DB81` | `#63D5A8` | `#7DDFE7` | `#8CA3FA` | `#A89FF9` | `#CB8EFB` | `#EB74DF` | `#5CA2E9` |
| 40 | `#ED448A` | `#E7434A` | `#F69E39` | `#FCD72E` | `#87C859` | `#36C18D` | `#55CCD9` | `#668CF7` | `#8E81F4` | `#BF68FA` | `#E049CE` | `#2E86DE` |
| 50 | `#E61866` | `#E02128` | `#F4840C` | `#FCC800` | `#62B42E` | `#09AA71` | `#2CB8C9` | `#2070F3` | `#715AFB` | `#B62BF7` | `#D41DBC` | `#0067D1` |
| 60 | `#C40054` | `#C7000B` | `#C76207` | `#D19F00` | `#488E20` | `#058358` | `#1C94A4` | `#1F55B5` | `#5531EB` | `#8A21BC` | `#9F1C8D` | `#004EA8` |
| 70 | `#811439` | `#850F12` | `#954304` | `#9E7400` | `#316614` | `#036142` | `#127180` | `#1B3F86` | `#3F21B5` | `#651B8B` | `#751868` | `#003D83` |
| 80 | `#540D24` | `#59080A` | `#642802` | `#614500` | `#1B3E0A` | `#02422E` | `#094C57` | `#112857` | `#281675` | `#41125A` | `#4C0F43` | `#002E6A` |
| 90 | `#330614` | `#350305` | `#3D1601` | `#2E1F00` | `#0C2004` | `#00291D` | `#04282F` | `#081635` | `#160B48` | `#260937` | `#2E0728` | `#00214B` |

### Neutral palette

Unlike hue palettes, gray includes explicit white `0` and black `100` endpoints.

| Palette token | Value | Palette token | Value | Palette token | Value |
| --- | --- | --- | --- | --- | --- |
| gray-0 (White) | `#FFFFFF` | gray-30 | `#AEAEAE` | gray-70 | `#393939` |
| gray-05 | `#F3F3F3` | gray-40 | `#939393` | gray-80 | `#2A2A2A` |
| gray-10 | `#DFDFDF` | gray-50 | `#777777` | gray-90 | `#191919` |
| gray-20 | `#C9C9C9` | gray-60 | `#595959` | gray-100 (Black) | `#000000` |

Palette entries are raw color choices, not additional semantic roles. Prefer the semantic UI and chart tokens above when their role applies. For a chosen raw token, bind its raw palette variable to the required Tailwind property (for example, `mint-40` → `bg-[var(--palette-mint-40)]`, `blue-70` → `stroke-[var(--palette-blue-70)]`); do not assume Tailwind's built-in color names have these values. Keep palette colors opaque unless a separate role explicitly specifies alpha.

## Company auxiliary colors

### Neutral auxiliary colors

| Color name | Value | Tailwind value translation |
| --- | --- | --- |
| BLACK | `#000000` | `bg-[var(--aux-black)]` |
| DARK GRAY | `#393939` | `bg-[var(--aux-dark-gray)]` |
| GRAY | `#777777` | `bg-[var(--aux-gray)]` |
| LIGHT GRAY | `#C9C9C9` | `bg-[var(--aux-light-gray)]` |
| WHITE | `#FFFFFF` | `bg-[var(--aux-white)]` |

These match gray-100, gray-70, gray-50, gray-20, and gray-0 respectively. Use the existing semantic text, icon, border, and surface roles when their meaning applies; these swatches do not replace the role-specific hierarchy.

### Chromatic auxiliary colors

| Color name | Value | Tailwind value translation |
| --- | --- | --- |
| ROSE | `#E61866` | `bg-[var(--aux-rose)]` |
| ORANGE | `#F36900` | `bg-[var(--aux-orange)]` |
| YELLOW | `#FDC000` | `bg-[var(--aux-yellow)]` |
| GREEN | `#4FA700` | `bg-[var(--aux-green)]` |
| CYAN | `#54BCCE` | `bg-[var(--aux-cyan)]` |

### Extended auxiliary hues — third priority

The following hue extensions are **third-priority choices** (限制第三优先级使用). Prefer applicable primary and base auxiliary colors before these extensions. The specification does not specify a complete first/second-priority decision tree or prohibit their use altogether.

| Color name | Value | Tailwind value translation |
| --- | --- | --- |
| PINK | `#D41DBC` | `bg-[var(--aux-pink)]` |
| PURPLE | `#B62BF7` | `bg-[var(--aux-purple)]` |
| INDIGO | `#5531EB` | `bg-[var(--aux-indigo)]` |
| BLUE | `#2070F3` | `bg-[var(--aux-blue)]` |
| MINT | `#00A874` | `bg-[var(--aux-mint)]` |

Palette distinction: this auxiliary palette is not an alias for the numbered [Company palette](#company-palette). In particular, auxiliary ORANGE `#F36900`, YELLOW `#FDC000`, GREEN `#4FA700`, CYAN `#54BCCE`, and MINT `#00A874` differ from their hue-50 entries (`#F4840C`, `#FCC800`, `#62B42E`, `#2CB8C9`, and `#09AA71`). Auxiliary INDIGO matches indigo-60, not indigo-50. Retain both documented contexts, use role-specific UI/chart values where specified, and do not silently overwrite numbered tokens with these auxiliary swatches. Report a conflict if a requested property explicitly requires both differing values. The auxiliary priority does not reorder the separately specified chart palettes.

The `bg-*` utilities above reference shared auxiliary variables; use the corresponding `text-*`, `border-*`, `fill-*`, or `stroke-*` utility only when the intended role calls for that property and the actual contrast is suitable. Auxiliary variables use `--aux-*`, distinct from semantic `--color-*` and raw `--palette-*` variables.
