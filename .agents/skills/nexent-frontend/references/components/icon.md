# Icon

## Close button icon

- Use an X icon only.
- Width and height: `14px`.
- Do not show a border when clicked.
- Cursor: `pointer`.
- Center the icon vertically.

Tailwind CSS:

```text
flex h-[14px] w-[14px] items-center justify-center
cursor-pointer border-0 bg-transparent p-0
```

Use the reusable component:

```tsx
import { StandardCloseButton } from "@/components/common/StandardCloseButton";
```

The close button requires an accessible label and an `onClick` callback.

## Question icon

Use Ant Design's question icon temporarily.

Use the reusable component:

```tsx
import { StandardQuestionIcon } from "@/components/common/StandardQuestionIcon";
```

## Placeholder icon

Use a placeholder icon only during local development when the final icon asset is unavailable.
Replace it when the asset becomes available. Do not commit placeholder icons.
