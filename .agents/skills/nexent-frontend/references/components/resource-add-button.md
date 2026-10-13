# Resource add button

Use `ResourceAddButton` from `@/components/common/ResourceAddButton` for the inspected Agent resource entry. It uses Ant Design `Button` and preserves keyboard, loading, disabled, and click behavior. The caller owns resource selection and supplies localized children; the component contains no API calls or default copy.

Confirmed source values: height 48px, radius 8px, horizontal padding 12px, vertical padding 8px, borderless background `#191919` at 3% opacity. The centered content group is 32px high, with a 24px icon and 12px gap. The label is 14px, regular 400, line-height 22px, tracking 0px, color `#191919`. Huawei Sans is the observed font family; the application owns font loading and fallback because the repository has no corresponding font file.

Tailwind mapping:

```text
h-12 w-full rounded-lg border-0 bg-[rgba(25,25,25,0.03)] px-3 py-2
text-sm font-normal leading-[22px] tracking-[0px] text-[#191919] shadow-none
inline-flex h-8 items-center justify-center gap-3
```

For the inspected empty resource row, the caller uses two columns and an 8px gap. Only the first column contains the add button. At 1213px row width this yields 602.5px for each column. The application uses `grid grid-cols-1 gap-2 sm:grid-cols-2` to keep the measured desktop columns while allowing readable localized labels below the small-screen breakpoint. Do not force a 602.5px width on smaller viewports.

The public props extend Ant Design `ButtonProps`, with controlled `children` and an optional `icon` (default Lucide 24px plus). Visual `type`, `variant`, and automatic CJK spacing are owned by the component. A `className` permits caller adjustments. No extra hover, focus, or disabled visual tokens are introduced. Preserve Ant Design interaction, visible keyboard focus, and disabled semantics.
