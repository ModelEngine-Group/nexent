"""
A2UI Component Builder - Provides a fluent API for constructing
A2UI (Agent-to-UI) component trees.

Usage:
    from nexent.core.a2ui.a2ui_builder import A2UIBuilder

    builder = A2UIBuilder(surface_id="search_results")
    builder.create_surface(catalog="basic", title="Search Results")
    builder.add_card(title="Item", body="Description")
    msg = builder.build_update_components()
    observer.add_message("", ProcessType.A2UI_COMPONENTS, json.dumps(msg))
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class A2UIComponent:
    """Represents a single A2UI component node in the component tree."""

    id: str
    component: str
    children: list[str] = field(default_factory=list)
    text: Optional[str] = None
    variant: Optional[str] = None
    icon: Optional[str] = None
    data_binding: Optional[str] = None
    action: Optional[dict] = None
    props: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        result: dict = {"id": self.id, "component": self.component}
        if self.children:
            result["children"] = self.children
        if self.text is not None:
            result["text"] = self.text
        if self.variant is not None:
            result["variant"] = self.variant
        if self.icon is not None:
            result["icon"] = self.icon
        if self.data_binding is not None:
            result["dataBinding"] = self.data_binding
        if self.action is not None:
            result["action"] = self.action
        if self.props:
            result["props"] = self.props
        return result


class A2UIBuilder:
    """Builder for constructing A2UI surfaces and their component trees.

    A2UI (Agent-to-UI) is a standard protocol that allows agents to generate
    structured UI component trees at runtime.  This builder provides a simple,
    chainable API for creating surfaces, adding layout / content / form
    components, and serialising the result for SSE transport.
    """

    def __init__(self, surface_id: Optional[str] = None):
        self._sid: str = surface_id or f"surface_{uuid.uuid4().hex[:8]}"
        self._components: dict[str, A2UIComponent] = {}
        self._root_ids: list[str] = []
        self._data_model: dict[str, Any] = {}
        self._created: bool = False

    # ------------------------------------------------------------------
    # Surface management
    # ------------------------------------------------------------------

    def create_surface(
        self, catalog: str = "basic", title: Optional[str] = None
    ) -> dict:
        """Create a new A2UI surface.

        Returns the surface descriptor that should be emitted as an
        ``A2UI_SURFACE`` message.
        """
        self._created = True
        return {
            "surfaceId": self._sid,
            "catalog": catalog,
            "title": title,
            "components": [],
            "dataModel": {},
            "rootIds": [],
        }

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    def add_row(
        self,
        children: Optional[list[Any]] = None,
        cid: Optional[str] = None,
        gap: str = "8px",
    ) -> A2UIComponent:
        """Add a horizontal layout container."""
        return self._add(
            "Row", cid=cid, children=children, props={"gap": gap}
        )

    def add_column(
        self,
        children: Optional[list[Any]] = None,
        cid: Optional[str] = None,
        gap: str = "8px",
    ) -> A2UIComponent:
        """Add a vertical layout container."""
        return self._add(
            "Column", cid=cid, children=children, props={"gap": gap}
        )

    # ------------------------------------------------------------------
    # Content helpers
    # ------------------------------------------------------------------

    def add_text(
        self,
        text: str,
        cid: Optional[str] = None,
        variant: str = "body",
        data_binding: Optional[str] = None,
    ) -> A2UIComponent:
        """Add a text component (title / subtitle / body / caption)."""
        return self._add(
            "Text",
            cid=cid,
            text=text,
            variant=variant,
            data_binding=data_binding,
        )

    def add_button(
        self,
        text: str,
        action_name: str,
        action_payload: Optional[dict] = None,
        cid: Optional[str] = None,
        variant: str = "primary",
    ) -> A2UIComponent:
        """Add an interactive button component."""
        return self._add(
            "Button",
            cid=cid,
            text=text,
            variant=variant,
            action={
                "event": {
                    "name": action_name,
                    "payload": action_payload or {},
                }
            },
        )

    def add_card(
        self,
        title: Optional[str] = None,
        body: Optional[str] = None,
        actions: Optional[list[dict]] = None,
        cid: Optional[str] = None,
    ) -> A2UIComponent:
        """Add a card component with optional title, body and action buttons."""
        card_id = cid or f"card_{uuid.uuid4().hex[:8]}"
        child_ids: list[str] = []

        if title:
            t = self.add_text(title, f"{card_id}_title", "subtitle")
            child_ids.append(t.id)

        if body:
            b = self.add_text(body, f"{card_id}_body", "body")
            child_ids.append(b.id)

        if actions:
            btn_ids: list[str] = []
            for i, a in enumerate(actions):
                btn = self.add_button(
                    a.get("text", "Action"),
                    a.get("name", "action"),
                    a.get("payload"),
                    f"{card_id}_btn_{i}",
                    a.get("variant", "secondary"),
                )
                btn_ids.append(btn.id)
            if btn_ids:
                row = self.add_row(btn_ids, f"{card_id}_actions")
                child_ids.append(row.id)

        return self._add("Card", cid=card_id, children=child_ids)

    # ------------------------------------------------------------------
    # Form helpers
    # ------------------------------------------------------------------

    def add_text_field(
        self,
        label: Optional[str] = None,
        placeholder: Optional[str] = None,
        cid: Optional[str] = None,
        data_binding: Optional[str] = None,
        required: bool = False,
    ) -> A2UIComponent:
        """Add a single-line text input field."""
        return self._add(
            "TextField",
            cid=cid or f"tf_{uuid.uuid4().hex[:8]}",
            props={
                "label": label,
                "placeholder": placeholder,
                "required": required,
            },
            data_binding=data_binding,
        )

    def add_text_area(
        self,
        label: Optional[str] = None,
        placeholder: Optional[str] = None,
        cid: Optional[str] = None,
        data_binding: Optional[str] = None,
        rows: int = 3,
    ) -> A2UIComponent:
        """Add a multi-line text area input."""
        return self._add(
            "TextArea",
            cid=cid or f"ta_{uuid.uuid4().hex[:8]}",
            props={
                "label": label,
                "placeholder": placeholder,
                "rows": rows,
            },
            data_binding=data_binding,
        )

    def add_form(
        self,
        fields: list[A2UIComponent],
        submit_action: str,
        submit_payload: Optional[dict] = None,
        title: Optional[str] = None,
        cid: Optional[str] = None,
    ) -> A2UIComponent:
        """Add a form container with input fields and a submit button."""
        fid = cid or f"form_{uuid.uuid4().hex[:8]}"
        child_ids: list[str] = []

        if title:
            t = self.add_text(title, f"{fid}_title", "subtitle")
            child_ids.append(t.id)

        for f in fields:
            child_ids.append(f.id)

        btn = self.add_button(
            "Submit",
            submit_action,
            submit_payload,
            f"{fid}_submit",
            "primary",
        )
        child_ids.append(btn.id)

        return self._add(
            "Form",
            cid=fid,
            children=child_ids,
            props={"submitPayload": submit_payload or {}},
        )

    def add_quick_replies(
        self,
        options: list[Any],
        cid: Optional[str] = None,
    ) -> A2UIComponent:
        """Add a row of quick-reply buttons.

        Each option can be a plain string (convenience) or a dict with
        ``text``, ``name``, ``payload``, ``id``, ``variant`` keys.
        """
        btn_ids: list[str] = []
        for i, opt in enumerate(options):
            if isinstance(opt, str):
                b = self.add_button(
                    opt, "quick_reply", {"value": opt}, f"qr_{i}", "secondary"
                )
            else:
                b = self.add_button(
                    opt.get("text", str(opt)),
                    opt.get("name", "quick_reply"),
                    opt.get("payload"),
                    opt.get("id", f"qr_{i}"),
                    opt.get("variant", "secondary"),
                )
            btn_ids.append(b.id)
        return self.add_row(
            btn_ids, cid or f"qr_{uuid.uuid4().hex[:8]}"
        )

    def add_rating(
        self,
        max_value: int = 5,
        cid: Optional[str] = None,
        data_binding: Optional[str] = None,
    ) -> A2UIComponent:
        """Add a star-rating input component."""
        return self._add(
            "Rating",
            cid=cid or f"rating_{uuid.uuid4().hex[:8]}",
            props={"maxValue": max_value},
            data_binding=data_binding or "rating.value",
        )

    # ------------------------------------------------------------------
    # Build helpers (produce SSE-ready payload dicts)
    # ------------------------------------------------------------------

    def build_create_surface(
        self, catalog: str = "basic", title: Optional[str] = None
    ) -> dict:
        """Build the payload for an ``A2UI_SURFACE`` message."""
        return self.create_surface(catalog=catalog, title=title)

    def build_update_components(self) -> dict:
        """Build the payload for an ``A2UI_COMPONENTS`` message.

        Components are returned as a nested tree: each component's
        ``children`` field contains full child component dicts (resolved
        recursively from ID references).  The ``components`` array contains
        only root-level components.

        If the surface has not been created yet it will be created
        automatically with default settings.
        """
        if not self._created:
            self.create_surface()

        def resolve_component(comp_id: str, visited: set[str] | None = None) -> dict:
            """Resolve a component ID to a full dict with nested children."""
            if visited is None:
                visited = set()
            if comp_id in visited:
                return {"id": comp_id, "component": "Text", "text": "(circular)"}
            visited = visited | {comp_id}
            comp = self._components.get(comp_id)
            if comp is None:
                return {"id": comp_id, "component": "Text", "text": "(missing)"}
            result = comp.to_dict()
            # Resolve children IDs to full component dicts
            if comp.children:
                result["children"] = [
                    resolve_component(cid, visited) for cid in comp.children
                ]
            return result

        root_components = [resolve_component(rid) for rid in self._root_ids]
        return {
            "surfaceId": self._sid,
            "components": root_components,
            "rootIds": self._root_ids,
            "dataModel": self._data_model,
        }

    def build_update_data_model(self, data_model: dict[str, Any]) -> dict:
        """Build the payload for an ``A2UI_DATA_MODEL`` message."""
        self._data_model.update(data_model)
        return {
            "surfaceId": self._sid,
            "dataModel": self._data_model,
        }

    def build_delete_surface(self) -> dict:
        """Build the payload for an ``A2UI_DELETE_SURFACE`` message."""
        return {"surfaceId": self._sid}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add(
        self,
        component: str,
        cid: Optional[str] = None,
        children: Optional[list[Any]] = None,
        text: Optional[str] = None,
        variant: Optional[str] = None,
        icon: Optional[str] = None,
        data_binding: Optional[str] = None,
        action: Optional[dict] = None,
        props: Optional[dict] = None,
    ) -> A2UIComponent:
        """Internal factory that creates, registers and returns a component."""
        comp_id = cid or f"{component.lower()}_{uuid.uuid4().hex[:8]}"
        child_ids: list[str] = []
        if children:
            for ch in children:
                child_ids.append(
                    ch.id if isinstance(ch, A2UIComponent) else ch
                )
        comp = A2UIComponent(
            id=comp_id,
            component=component,
            children=child_ids,
            text=text,
            variant=variant,
            icon=icon,
            data_binding=data_binding,
            action=action,
            props=props or {},
        )
        self._components[comp_id] = comp
        if not self._is_child(comp_id):
            self._root_ids.append(comp_id)
        return comp

    def _is_child(self, cid: str) -> bool:
        """Check whether *cid* appears as a child of any existing component."""
        return any(cid in c.children for c in self._components.values())


# ------------------------------------------------------------------
# Convenience factory functions
# ------------------------------------------------------------------


def create_info_card(
    title: str,
    content: str,
    action_name: Optional[str] = None,
    action_payload: Optional[dict] = None,
    surface_id: Optional[str] = None,
) -> tuple[A2UIBuilder, dict]:
    """Create a builder pre-loaded with a simple info card.

    Returns ``(builder, surface_payload)`` so the caller can emit the
    surface first and then add more components before sending the
    component update.
    """
    builder = A2UIBuilder(surface_id=surface_id)
    surface = builder.create_surface(catalog="basic", title=title)

    actions = []
    if action_name:
        actions.append(
            {
                "text": "Action",
                "name": action_name,
                "payload": action_payload or {},
                "variant": "primary",
            }
        )

    builder.add_card(title=title, body=content, actions=actions)
    return builder, surface


def create_feedback_form(
    title: str,
    fields: Optional[list[dict]] = None,
    submit_action: str = "submit_feedback",
    submit_payload: Optional[dict] = None,
    include_rating: bool = True,
    surface_id: Optional[str] = None,
) -> tuple[A2UIBuilder, dict]:
    """Create a builder pre-loaded with a feedback form.

    Returns ``(builder, surface_payload)``.  The default form includes
    a comment text-area and an optional rating component.
    """
    builder = A2UIBuilder(surface_id=surface_id)
    surface = builder.create_surface(catalog="hitl", title=title)

    input_fields: list[A2UIComponent] = []

    if fields:
        for i, f in enumerate(fields):
            ft = f.get("type", "text")
            if ft == "text":
                input_fields.append(
                    builder.add_text_field(
                        label=f.get("label"),
                        placeholder=f.get("placeholder"),
                        data_binding=f.get("binding"),
                        required=f.get("required", False),
                    )
                )
            elif ft == "textarea":
                input_fields.append(
                    builder.add_text_area(
                        label=f.get("label"),
                        placeholder=f.get("placeholder"),
                        data_binding=f.get("binding"),
                        rows=f.get("rows", 3),
                    )
                )

    if not input_fields:
        input_fields.append(
            builder.add_text_area(
                label="Comment",
                placeholder="Enter your feedback here...",
                data_binding="feedback.comment",
                rows=3,
            )
        )

    if include_rating:
        input_fields.append(
            builder.add_rating(
                max_value=5, data_binding="feedback.rating"
            )
        )

    builder.add_form(
        fields=input_fields,
        submit_action=submit_action,
        submit_payload=submit_payload,
        title=title,
    )
    return builder, surface