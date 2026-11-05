# Pagination

Use controlled common Pagination: current, pageSize, total, onPageChange and optional onPageSizeChange. Callers own query/data state; the component never requests data. Compact, size selection and quick jumping are explicit props. StandardPaginator and its duplicated state/prop mapping have been removed. Do not silently reset caller-owned page state.

Optional `showTotal` renders the localized item count within the same navigation. With `showSizeChanger` and `showQuickJumper`, Pagination owns the complete footer: total at the left and size, page buttons and jump controls at the right. Desktop controls stay on one line; narrow screens wrap between groups. Without a total, the navigation sizes to its contents so it can sit beside other controls.

Quick jumping supports Enter, leaving the jump group, and the localized Go button; malformed and out-of-range values do not navigate. Changing page size clears the jump draft and requests page 1. Callers retain their existing page-size options and supply state callbacks rather than duplicating selectors or jump inputs.
