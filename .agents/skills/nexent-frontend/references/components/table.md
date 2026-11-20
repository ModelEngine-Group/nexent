# Table

Use native Ant Design Table with the central NEXENT_THEME component tokens. The unused StandardTable selector wrapper was removed. Preserve native column definitions, rowSelection, pagination, fixed columns, scrolling and render callbacks rather than defining a parallel table API.

Business tables own their columns, data, permission conditions and service callbacks. Generic selection/operation presentation or resizing may be shared when there is concrete demand; do not rebuild the table engine to centralize colors. The agents table retains its existing AntD implementation and feature-local column resizing.
