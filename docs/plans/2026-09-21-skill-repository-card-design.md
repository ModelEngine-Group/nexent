# Skill Repository Card Design

## Goal

Align the Skill repository and My Skills tabs with the Agent repository card system, while retaining the Skill page's current server-side query behavior.

## Chosen approach

`ResourceCardGrid` owns only the pagination UI: the Skill repository passes its current server page, total count, and page-change callback to the grid with `paginateItems={false}`. This preserves the existing query contract, makes Ant Design pagination appear even for a partial one-page result, and avoids a second slice of server-paged data.

Repository cards use `ResourceCard` as the clickable surface. Their detail button is removed; a small text-style Copy action occupies the bottom right while the download metric sits immediately to the left of the More menu. The description area's reserved tag space remains consistent with Agent cards.

My Skills continues to use the same grid and card height. It removes the Hub and Custom indicators and the bottom listing-status action. The edit action moves to the lower right; the shared status appears under More. Read-only skills retain their View action.

## Scope

- Modify the Skill tab containers and card views so their query page sizes track the same responsive grid dimensions as Agent cards; adjust the shared tag filter button to use Ant Design's default size; add focused layout tests.
- Reuse the in-progress shared `ResourceCard` / `ResourceCardGrid` behavior; do not modify backend APIs, translations, Agent/MCP cards, or non-Skill tabs.

## Validation

Run the focused Node layout tests and the frontend type/lint command supported by this checkout. Manually verify both tabs at desktop and narrow widths, including a partial first page, card click, Copy, More, Edit/View, and status display.
