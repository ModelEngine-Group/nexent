# Modal

## Behavior

- Open the modal from a button or operation.
- Keep the modal above the current page layer.
- Do not allow other page operations while the modal is open.
- Center the modal by default.
- The close icon, cancel button, and confirm button support callbacks.
- A callback returning `false` prevents the modal from closing.
- Button labels support custom localized text.

The reusable component uses Ant Design `Modal` with `mask={{ closable: false }}` and `keyboard={false}` so the modal is closed only through the configured actions.

## Style

- Border radius: `8px`.
- Default width: `480px`.
- Height: auto.
- Padding: `24px`.
- Shadow: `x 0`, `y 0`, blur `15px`, spread `0`, color `#1a1a1a` at `10%` opacity.

Tailwind CSS:

```text
rounded-[8px] w-[480px] h-auto p-6 shadow-[0_0_15px_0_rgba(26,26,26,0.1)]
```

The reusable component exposes a `width` prop for an adjusted width.

## Layout

Use a three-part header, content, and footer layout.

### Header

#### Layout

- Align the title and close icon on opposite sides.
- Use the title 2 font for the title.
- Vertically center the close icon.

Tailwind CSS:

```text
flex h-6 w-full items-center justify-between
```

#### Style

- Height: `24px`.
- Width: full width.
- Use [Title 2](font.md#title-2) for the title.

Title Tailwind CSS:

```text
text-[16px] ![letter-spacing:0px] text-[#1a1a1a] font-bold leading-6
```

### Content

#### Layout

- Height is content-sized up to a maximum of `50vh`.
- Show a scrollbar in the content area when the maximum height is exceeded.
- Do not scroll the entire modal.

Tailwind CSS:

```text
max-h-[50vh] overflow-y-auto px-0 py-4
```

### Footer

#### Layout

- The footer is optional and present by default.
- Use two buttons by default: cancel and confirm.
- Align buttons to the right.
- Keep multiple buttons on one line with `16px` between them.

#### Style

- Height: `32px`.
- Width: full width.

Tailwind CSS:

```text
h-8 w-full flex flex-nowrap items-center justify-end gap-4
```

Use the [primary button](button.md#primary-button) style for the confirm button.

Use the reusable component:

```tsx
import { StandardModal } from "@/components/common/StandardModal";
```
