# Card

## Style

- Background: `#fff`.
- No border by default.
- Support configuring the border.
- Border radius: `8px` by default.
- Support adjusting the border radius.
- Support setting the width.
- Support setting the height.
- Support custom content and additional configuration.

Tailwind CSS:

```text
bg-[#fff] border-0 rounded-[8px]
```

Use `rounded-[8px]` as the default radius and allow a caller-provided class to adjust it. Use Ant Design `Card` for the card behavior.

Use the reusable component:

```tsx
import { StandardCard } from "@/components/common/StandardCard";
```

## Agent repository tag row

`app/[locale]/agent-space/components/AgentCardTags.tsx` is feature-local to the repository and mine cards. Pass already localized `labels: string[]`; it does not load resource data. Empty labels render nothing. The row uses one `h-6` line with `gap-2`, caps chips at `max-w-[120px]`, and preserves complete text through native title hints. It measures chip widths and observes row resize so the visible prefix and `+N` count follow the available width, including after a hidden tab becomes visible. The focusable overflow button opens all labels on hover, click or focus; tag interactions stop propagation to card navigation. Repository tool counts remain alongside the tag row without wrapping.
