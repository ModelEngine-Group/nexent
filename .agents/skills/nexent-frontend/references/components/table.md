# Table

## Implementation

- Render data tables with Ant Design `Table`.
- Use the reusable `StandardTable` wrapper for shared table styling. It forwards Ant Design `Table` props to preserve compatibility with existing table features.
- Leave unspecified behavior to Ant Design defaults; do not invent extra visual states or interactions.

## Styling

| Property                                 | Value               | Tailwind CSS                             |
| ---------------------------------------- | ------------------- | ---------------------------------------- |
| Text color                               | `#191919`           | `text-[#191919]`                         |
| Font size                                | `14px`              | `text-[14px]`                            |
| Letter spacing                           | `0px`               | `![letter-spacing:0px]`                  |
| Table background                         | `#fff`              | `bg-white`                               |
| Header background                        | `#f3f3f3`           | `bg-[#f3f3f3]`                           |
| Row height                               | `40px`              | `h-10`                                   |
| Row divider                              | `1px solid #f0f0f0` | `border-b border-solid border-[#f0f0f0]` |
| Header column divider (except last)      | `1px solid #c9c9c9`, `14px` high, centered | `before:h-[14px] before:bg-[#c9c9c9] before:top-1/2 before:[transform:translateY(-50%)]` |
| Compact filter-header horizontal padding | `8px`               | `px-2`                                   |

Render the header separator with Ant Design's header-cell `::before` pseudo-element, centered vertically and limited to text height. Set its `transform` explicitly; do not combine Ant Design's default transform with Tailwind `-translate-y-1/2`, which adds a second independent translation. Apply it only between header columns, not between body cells; do not add an outer table border. Do not set a `font-family`.

## Reusable component

```tsx
import { StandardTable } from "@/components/common/StandardTable";
```

`StandardTable<RecordType>` forwards the Ant Design `TableProps<RecordType>` API. Keep its generic props and forwarding behavior backward-compatible when updating shared table styles.
