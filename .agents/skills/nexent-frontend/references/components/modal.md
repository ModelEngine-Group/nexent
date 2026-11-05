# Modals

common Modal owns the content shell, retained draft lifecycle, accessible title/close control and outside/Escape policy. common Dialog owns the portal/content integration used by several consumers. Callers own open state and workflow callbacks.

Use Modal `footer` for custom actions (`null` suppresses it). Optional `actions` groups cancel/confirm labels and callbacks; callbacks own closure and may keep the modal open for validation. Do not restore StandardModal or add another footer-only wrapper. Default action labels are caller-localized. ExpandEditModal composes Modal for cross-domain long-text editing.
