# Button

## Layout

The standard button has a height of `32px`, content-sized width, vertical padding of `5px`, and horizontal padding of `16px`.

Tailwind CSS:

```text
h-8 w-fit py-[5px] px-4
```

## Common button

### Style

- Use the default font.
- Line height: `22px`.
- Use the default border.
- Border radius: `4px`.
- Background: transparent or `#fff`.
- Cursor: `pointer`.

Tailwind CSS:

```text
text-[#191919] text-[14px] ![letter-spacing:0px] leading-[22px]
[&>span]:![letter-spacing:0px]
border border-solid border-[#c9c9c9]
rounded-[4px] bg-transparent cursor-pointer
```

Use `bg-white` instead of `bg-transparent` when the white background is required.

## Primary button

The primary button inherits the common button layout and uses:

- Text color: `#fff`.
- No border.
- Border radius: `4px`.
- Background: `#0067d1`.

Tailwind CSS:

```text
text-white border-0 rounded-[4px] bg-[#0067d1]
```

Use the reusable component:

```tsx
import { StandardButton } from "@/components/common/StandardButton";
```

The reusable component disables Ant Design automatic spacing between adjacent CJK characters so localized labels are rendered exactly as provided.
