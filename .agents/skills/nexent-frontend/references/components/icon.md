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

Prefer the native Modal/Drawer close control and its `closable`/`closeIcon` APIs. In an existing custom header, use a native AntD `Button` with `type="text"`, an X icon, an accessible label and an `onClick` callback. Keep keyboard focus visible. An icon and label alone do not justify a shared close-button wrapper.

## Question icon

Use Ant Design's question icon temporarily.

Use the reusable component:

```tsx
import { QuestionCircleOutlined } from "@ant-design/icons";
```

## Placeholder icon

Use a placeholder icon only during local development when the final icon asset is unavailable.
Replace it when the asset becomes available. Do not commit placeholder icons.
