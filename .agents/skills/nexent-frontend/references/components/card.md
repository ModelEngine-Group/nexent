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
