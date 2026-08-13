"""A2UI Card Output Tool for generating interactive cards and forms.

This tool enables the Agent to output A2UI-formatted cards, forms,
and interactive components during conversation. The frontend renders
these as rich Ant Design components.

Usage in Agent prompts:
    "When you need to display structured information or request user feedback,
     use the output_card tool to generate interactive cards and forms."
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType

logger = logging.getLogger("a2ui_card_tool")


class OutputCardTool(Tool):
    """Tool for outputting A2UI cards, forms, and interactive components.

    Supports multiple card types:
    - info: Informational card with title and message
    - feedback: Feedback form with question and options
    - confirmation: Confirmation dialog with yes/no buttons
    - form: Custom form with text fields, selects, etc.
    - rating: Star rating component
    - chart: Statistical chart visualization (bar, line, pie, area)
    """

    name = "output_card"
    description = (
        "Output an interactive A2UI card or form to the user. "
        "Supports info cards, feedback forms, confirmation dialogs, "
        "custom forms, and rating components. Use this when you need to "
        "display structured information or request user input."
    )
    description_zh = (
        "向用户输出交互式 A2UI 卡片或表单。支持信息卡片、反馈表单、"
        "确认对话框、自定义表单和评分组件。当需要展示结构化信息或"
        "请求用户输入时使用此工具。"
    )

    inputs = {
        "card_type": {
            "type": "string",
            "description": (
                "Type of card to output: 'info' (informational), "
                "'feedback' (feedback form), 'confirmation' (yes/no dialog), "
                "'form' (custom form), 'rating' (star rating), "
                "'chart' (statistical chart visualization)"
            ),
            "description_zh": (
                "卡片类型：'info'（信息卡）、'feedback'（反馈表单）、"
                "'confirmation'（确认对话框）、'form'（自定义表单）、"
                "'rating'（评分组件）、'chart'（统计图表）"
            ),
            "nullable": True,
        },
        "title": {
            "type": "string",
            "description": "Card title text",
            "description_zh": "卡片标题文本",
            "nullable": True,
        },
        "message": {
            "type": "string",
            "description": "Card body message (for info cards)",
            "description_zh": "卡片正文消息（用于信息卡）",
            "nullable": True,
        },
        "options": {
            "type": "array",
            "description": (
                "List of option strings for feedback/confirmation cards. "
                "Example: ['Yes', 'No'] or ['Confirm', 'Cancel']"
            ),
            "description_zh": (
                "反馈/确认卡片的选项字符串列表。例如：['是', '否'] 或 ['确认', '取消']"
            ),
            "nullable": True,
        },
        "fields": {
            "type": "array",
            "description": (
                "Form field definitions for custom form type. "
                "Each field is a dict with: name, label, type (textfield/textarea/select/checkbox), "
                "placeholder (optional), options (for select type), required (bool)"
            ),
            "description_zh": (
                "自定义表单的字段定义列表。每个字段是字典，包含：name、label、"
                "type（textfield/textarea/select/checkbox）、placeholder（可选）、"
                "options（select 类型）、required（布尔值）"
            ),
            "nullable": True,
        },
        "allow_custom_input": {
            "type": "boolean",
            "description": "Whether to allow custom text input in feedback forms",
            "description_zh": "反馈表单是否允许自定义文本输入",
            "nullable": True,
        },
        "chart_type": {
            "type": "string",
            "description": (
                "Type of chart: 'bar' (bar chart), 'line' (line chart), "
                "'pie' (pie chart), 'area' (area chart). Required when card_type is 'chart'."
            ),
            "description_zh": (
                "图表类型：'bar'（柱状图）、'line'（折线图）、"
                "'pie'（饼图）、'area'（面积图）。当 card_type 为 'chart' 时必填。"
            ),
            "nullable": True,
        },
        "chart_data": {
            "type": "object",
            "description": (
                "Chart data object. Format: { labels: string[], datasets: [{ label: string, data: number[] }] }"
            ),
            "description_zh": (
                "图表数据对象。格式：{ labels: string[], datasets: [{ label: string, data: number[] }] }"
            ),
            "nullable": True,
        },
        "chart_options": {
            "type": "object",
            "description": (
                "Optional chart configuration. Format: { xAxis: string, yAxis: string, title: string }"
            ),
            "description_zh": (
                "可选的图表配置。格式：{ xAxis: string, yAxis: string, title: string }"
            ),
            "nullable": True,
        },
    }
    output_type = "object"

    def __init__(
        self,
        observer: MessageObserver = Field(
            description="Message observer", default=None, exclude=True
        ),
    ) -> None:
        super().__init__()
        self.observer = observer

    def forward(
        self,
        card_type: str = "info",
        title: str = "",
        message: str = "",
        options: Optional[List[str]] = None,
        fields: Optional[List[Dict[str, Any]]] = None,
        allow_custom_input: bool = True,
        chart_type: Optional[str] = None,
        chart_data: Optional[Dict[str, Any]] = None,
        chart_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Output an A2UI card to the frontend.

        Args:
            card_type: Type of card (info, feedback, confirmation, form, rating, chart)
            title: Card title
            message: Card body message
            options: Option strings for feedback/confirmation cards
            fields: Form field definitions for custom form type
            allow_custom_input: Allow custom text input in feedback forms
            chart_type: Type of chart (bar, line, pie, area) for chart card
            chart_data: Chart data with labels and datasets for chart card
            chart_options: Optional chart configuration for chart card

        Returns:
            Dict with success status and card_id
        """
        from ..a2ui.a2ui_builder import A2UIBuilder

        logger.info(
            "OutputCardTool.forward called: card_type=%s, title=%s, message=%s, observer=%s",
            card_type, title, message[:100] if message else "", self.observer is not None,
        )

        if not self.observer:
            logger.error("OutputCardTool: observer is not initialized!")
            return {
                "success": False,
                "error": "Observer not initialized. Cannot send card.",
            }

        builder = A2UIBuilder(surface_id=f"card_{card_type}_{id(self)}")

        try:
            # Create surface
            surface_msg = builder.create_surface(catalog="basic")
            self.observer.add_message(
                "", ProcessType.A2UI_SURFACE, json.dumps(surface_msg)
            )

            # Build components based on card type
            if card_type == "info":
                self._build_info_card(builder, title, message)

            elif card_type == "feedback":
                self._build_feedback_card(
                    builder, title, message, options or [], allow_custom_input
                )

            elif card_type == "confirmation":
                self._build_confirmation_card(builder, title, message, options or [])

            elif card_type == "form":
                self._build_form_card(builder, title, fields or [])

            elif card_type == "rating":
                self._build_rating_card(builder, title, message)

            elif card_type == "chart":
                self._build_chart_card(
                    builder, title, chart_type or "bar",
                    chart_data or {}, chart_options or {},
                )

            else:
                # Default to info card
                self._build_info_card(builder, title, message)

            # Send components
            components_msg = builder.build_update_components()
            self.observer.add_message(
                "", ProcessType.A2UI_COMPONENTS, json.dumps(components_msg)
            )

            logger.info(
                "A2UI card sent successfully: type=%s, surface_id=%s, components_count=%d",
                card_type, builder._sid, len(components_msg.get("components", [])),
            )

            return {
                "success": True,
                "card_type": card_type,
                "title": title,
                "message": "Card sent successfully",
            }

        except Exception as e:
            logger.error("Failed to output A2UI card: %s", str(e))
            return {
                "success": False,
                "error": str(e),
                "card_type": card_type,
            }

    def _build_info_card(
        self, builder: Any, title: str, message: str
    ) -> None:
        """Build an informational card."""
        builder.add_card(
            title=title or "Information",
            body=message or "",
        )

    def _build_feedback_card(
        self,
        builder: Any,
        title: str,
        question: str,
        options: List[str],
        allow_custom: bool,
    ) -> None:
        """Build a feedback form card."""
        builder.add_text(
            text=title or question or "Please provide your feedback",
            variant="h3",
        )

        if options:
            builder.add_quick_replies(options)

        if allow_custom:
            builder.add_text_area(
                label="Additional comments (optional)",
                placeholder="Enter your feedback here...",
                data_binding="/feedback/comment",
            )

        builder.add_button(
            text="Submit Feedback",
            action_name="submit_feedback",
            action_payload={"data": "$dataModel/feedback"},
            variant="primary",
        )

    def _build_confirmation_card(
        self,
        builder: Any,
        title: str,
        message: str,
        options: List[str],
    ) -> None:
        """Build a confirmation dialog card."""
        builder.add_card(
            title=title or "Confirmation",
            body=message or "Are you sure?",
            actions=[{"text": opt, "name": "confirm", "payload": {"choice": opt}} for opt in (options or ["Confirm", "Cancel"])],
        )

    def _build_form_card(
        self,
        builder: Any,
        title: str,
        fields: List[Dict[str, Any]],
    ) -> None:
        """Build a custom form card."""
        builder.add_text(text=title or "Form", variant="h3")

        form_components = []
        for field in fields:
            field_type = field.get("type", "textfield")
            field_name = field.get("name", "")
            field_label = field.get("label", "")
            field_placeholder = field.get("placeholder", "")
            field_required = field.get("required", False)
            field_binding = field.get("binding", f"dataModel/{field_name}")

            if field_type == "textarea":
                component = builder.add_text_area(
                    label=field_label,
                    placeholder=field_placeholder,
                    data_binding=field_binding,
                )
            elif field_type == "select":
                # Create a text field that renders as a select on frontend
                component = builder.add_text_field(
                    label=field_label,
                    placeholder=field_placeholder,
                    data_binding=field_binding,
                    required=field_required,
                )
                # Store options in props for frontend rendering
                component.props["options"] = field.get("options", [])
            elif field_type == "checkbox":
                # Use text field as checkbox placeholder
                component = builder.add_text_field(
                    label=field_label,
                    placeholder=field_placeholder,
                    data_binding=field_binding,
                    required=field_required,
                )
                component.props["checkbox"] = True
            else:  # textfield or default
                component = builder.add_text_field(
                    label=field_label,
                    placeholder=field_placeholder,
                    data_binding=field_binding,
                    required=field_required,
                )
            form_components.append(component)

        builder.add_form(
            fields=form_components,
            submit_action="submit_form",
            submit_payload={"form_data": "$dataModel"},
        )

    def _build_rating_card(
        self,
        builder: Any,
        title: str,
        message: str,
    ) -> None:
        """Build a rating card."""
        builder.add_text(text=title or "Rate Your Experience", variant="h3")

        if message:
            builder.add_text(text=message, variant="body")

        builder.add_rating(max_value=5)

        builder.add_button(
            text="Submit Rating",
            action_name="submit_rating",
            action_payload={"rating": "$dataModel/rating"},
            variant="primary",
        )

    def _build_chart_card(
        self,
        builder: Any,
        title: str,
        chart_type: str,
        chart_data: Dict[str, Any],
        chart_options: Dict[str, Any],
    ) -> None:
        """Build a statistical chart card.

        Args:
            builder: A2UI builder instance
            title: Chart title
            chart_type: Type of chart (bar, line, pie, area)
            chart_data: Chart data with labels and datasets
            chart_options: Optional chart configuration
        """
        builder.add_text(text=title or "Chart", variant="h3")

        chart_component = builder.add_chart(
            chart_type=chart_type,
            data=chart_data,
            options=chart_options,
        )
