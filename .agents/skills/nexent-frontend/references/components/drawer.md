# Drawer

## Style

- Open from the right side by default.
- Keep the background unavailable while the drawer is open.
- Fill the available height.
- Use `24px` padding.
- Default width: `560px`.
- Support overriding the width.
- Shadow: `x -2px`, `y 0`, blur `12px`, spread `0`, color `#000000` at `8%` opacity.

Tailwind CSS:

```text
flex h-full flex-col overflow-hidden p-6
```

Width Tailwind CSS:

```text
w-[560px]
```

Shadow Tailwind CSS:

```text
shadow-[-2px_0_12px_0_rgba(0,0,0,0.08)]
```

The reusable component exposes a `width` prop for an adjusted width. The Ant Design `Drawer` width property controls the panel width.

Use `mask={{ closable: false }}` so clicking the background does not close the drawer.

## Header

### Layout

- Full width.
- Height: `28px`.
- Space items between the two sides.
- Place the title on the left and the close icon on the right.
- Limit the title width to `300px` and hide overflowing text.

Tailwind CSS:

```text
flex h-[28px] w-full shrink-0 items-center justify-between
```

Title Tailwind CSS:

```text
max-w-[300px] overflow-hidden whitespace-nowrap
```

### Style

Title:

- Font size: `20px`.
- Letter spacing: `0px`.
- Line height: `28px`.
- Color: `#191919`.

Title Tailwind CSS:

```text
text-[20px] ![letter-spacing:0px] leading-[28px] text-[#191919]
```

Close icon:

- Width and height: `14px`.
- Use an X icon only.
- Do not show a border when clicked.
- Cursor: `pointer`.
- Center vertically.

Close icon Tailwind CSS:

```text
flex h-[14px] w-[14px] items-center justify-center
cursor-pointer border-0 bg-transparent p-0
```

### Behavior

Clicking the close icon closes the drawer.

## Content

### Layout

- Full width.
- Occupy the remaining height between the header and footer.

Tailwind CSS:

```text
min-h-0 w-full flex-1
```

### Style

- Scroll the content area when necessary.
- Do not scroll the entire drawer.
- Vertical padding: `16px`.
- Horizontal padding: `0`.

Tailwind CSS:

```text
overflow-y-auto px-0 py-4
```

### Behavior

The content area contains the drawer's content.

## Footer

### Layout

- The footer may be omitted; it is present by default.
- Full width.
- Height: `32px`.

Tailwind CSS:

```text
h-8 w-full shrink-0
```

### Behavior

- Place buttons on the right.
- Use `16px` between multiple buttons.
- Keep multiple buttons on one line.
- Render only the close button by default.
- Support an optional confirm button.
- Use the [primary button](button.md#primary-button) style for the confirm button.

Button container Tailwind CSS:

```text
flex h-8 w-full shrink-0 flex-nowrap items-center justify-end gap-4
```

Use the reusable component:

```tsx
import { StandardDrawer } from "@/components/common/StandardDrawer";
```
