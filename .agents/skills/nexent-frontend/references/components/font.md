# Font

## Default

- Color: `#191919`.
- Body font size: `font-body-2` (14px).
- Letter spacing: `0px`.

Tailwind CSS:

```text
text-[#191919] text-body-2 ![letter-spacing:0px]
```

## Body sizes

| Role | Size | Ant Design token | Tailwind utility |
| --- | --- | --- | --- |
| font-body-1 | 12px | fontSizeSM | text-body-1 |
| font-body-2 | 14px (default) | fontSize | text-body-2 |
| font-body-3 | 16px | fontSizeLG | text-body-3 |

`BRAND_BODY_FONT_SIZES` in `frontend/const/brand.ts` is the shared source. It generates `--font-body-1/2/3` CSS variables. The global body inherits body-2; use the semantic utilities for explicit body sizes. Tailwind v4 maps these through `--text-body-1/2/3` in `globals.css`; `tailwind.config.js` mirrors the mapping for configuration consumers. Do not use Tailwind's `--font-*` theme namespace for font sizes: it represents font families.

Keep existing heading sizes and component-specific typography intentional. A component's explicit size or local font-size can override the default; this mapping does not force every piece of text to 14px. Theme-covered typography does not justify a common wrapper.

## Title

- Font size: `20px`.
- Letter spacing: `0px`.
- Color: `#191919`.

Tailwind CSS:

```text
text-[20px] ![letter-spacing:0px] text-[#191919]
```

## Title 2

- Font size: `16px`.
- Letter spacing: `0px`.
- Color: `#1a1a1a`.
- Font weight: bold.

Tailwind CSS:

```text
text-[16px] ![letter-spacing:0px] text-[#1a1a1a] font-bold
```

## Title 1

- Font size: `18px`.
- Letter spacing: `0px`.
- Color: `#191919`.

Tailwind CSS:

```text
text-[18px] ![letter-spacing:0px] text-[#191919]
```

## Description 1

- Color: `#777777`.
- Body font size: `font-body-2` (14px).
- Letter spacing: `0px`.

Tailwind CSS:

```text
text-[#777777] text-body-2 ![letter-spacing:0px]
```
