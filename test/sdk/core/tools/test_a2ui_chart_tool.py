"""Tests for A2UI Chart Tool - statistical chart visualization."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SDK_DIR = _REPO_ROOT / "sdk"
if str(_SDK_DIR) not in sys.path:
    sys.path.insert(0, str(_SDK_DIR))

from nexent.core.tools.a2ui_card_tool import OutputCardTool
from nexent.core.a2ui.a2ui_builder import A2UIBuilder, create_chart_card
from nexent.core.utils.observer import MessageObserver, ProcessType


@pytest.fixture
def mock_observer():
    """Create a mock message observer."""
    observer = MagicMock(spec=MessageObserver)
    observer.messages = []
    
    def add_msg(source, process_type, content):
        observer.messages.append({
            "source": source,
            "process_type": process_type,
            "content": content,
        })
    
    observer.add_message = MagicMock(side_effect=add_msg)
    return observer


class TestOutputCardToolChart:
    """Tests for the chart card type in OutputCardTool."""

    def test_bar_chart_output(self, mock_observer):
        """Output a bar chart card successfully."""
        tool = OutputCardTool(observer=mock_observer)
        
        result = tool.forward(
            card_type="chart",
            title="月度销售数据",
            chart_type="bar",
            chart_data={
                "labels": ["1月", "2月", "3月", "4月"],
                "datasets": [{"label": "销售额", "data": [120, 200, 150, 280]}],
            },
            chart_options={
                "xAxis": "月份",
                "yAxis": "销售额（万元）",
                "title": "2025年销售趋势",
            },
        )
        
        assert result["success"] is True
        assert result["card_type"] == "chart"
        
        # Verify messages were sent
        assert len(mock_observer.add_message.call_args_list) >= 2
        
        # Verify surface was created
        surface_call = mock_observer.add_message.call_args_list[0]
        assert surface_call[0][1] == ProcessType.A2UI_SURFACE
        surface_data = json.loads(surface_call[0][2])
        assert "surfaceId" in surface_data
        
        # Verify components were sent
        components_call = mock_observer.add_message.call_args_list[1]
        assert components_call[0][1] == ProcessType.A2UI_COMPONENTS
        components_data = json.loads(components_call[0][2])
        
        # Find Chart component
        chart_components = [
            c for c in components_data.get("components", [])
            if c.get("component") == "Chart"
        ]
        assert len(chart_components) == 1
        chart = chart_components[0]
        assert chart["props"]["chartType"] == "bar"
        assert chart["props"]["data"]["labels"] == ["1月", "2月", "3月", "4月"]
        assert len(chart["props"]["data"]["datasets"]) == 1
        assert chart["props"]["data"]["datasets"][0]["data"] == [120, 200, 150, 280]
    
    def test_line_chart_output(self, mock_observer):
        """Output a line chart card successfully."""
        tool = OutputCardTool(observer=mock_observer)
        
        result = tool.forward(
            card_type="chart",
            title="用户增长趋势",
            chart_type="line",
            chart_data={
                "labels": ["Q1", "Q2", "Q3", "Q4"],
                "datasets": [
                    {"label": "新增用户", "data": [1000, 2500, 3500, 5000]},
                    {"label": "活跃用户", "data": [5000, 8000, 12000, 15000]},
                ],
            },
        )
        
        assert result["success"] is True
        
        # Verify multiple datasets
        components_call = mock_observer.add_message.call_args_list[1]
        components_data = json.loads(components_call[0][2])
        chart = [
            c for c in components_data.get("components", [])
            if c.get("component") == "Chart"
        ][0]
        assert len(chart["props"]["data"]["datasets"]) == 2
    
    def test_pie_chart_output(self, mock_observer):
        """Output a pie chart card successfully."""
        tool = OutputCardTool(observer=mock_observer)
        
        result = tool.forward(
            card_type="chart",
            title="流量来源分布",
            chart_type="pie",
            chart_data={
                "labels": ["直接访问", "搜索引擎", "社交媒体", "其他"],
                "datasets": [{"label": "占比", "data": [30, 45, 20, 5]}],
            },
        )
        
        assert result["success"] is True
        
        components_call = mock_observer.add_message.call_args_list[1]
        components_data = json.loads(components_call[0][2])
        chart = [
            c for c in components_data.get("components", [])
            if c.get("component") == "Chart"
        ][0]
        assert chart["props"]["chartType"] == "pie"
    
    def test_area_chart_output(self, mock_observer):
        """Output an area chart card successfully."""
        tool = OutputCardTool(observer=mock_observer)
        
        result = tool.forward(
            card_type="chart",
            title="库存变化",
            chart_type="area",
            chart_data={
                "labels": ["周一", "周二", "周三", "周四", "周五"],
                "datasets": [{"label": "库存量", "data": [500, 450, 400, 380, 350]}],
            },
        )
        
        assert result["success"] is True
        
        components_call = mock_observer.add_message.call_args_list[1]
        components_data = json.loads(components_call[0][2])
        chart = [
            c for c in components_data.get("components", [])
            if c.get("component") == "Chart"
        ][0]
        assert chart["props"]["chartType"] == "area"
    
    def test_chart_without_observer(self):
        """Chart tool should fail gracefully without observer."""
        tool = OutputCardTool(observer=None)
        
        result = tool.forward(
            card_type="chart",
            title="测试",
            chart_type="bar",
            chart_data={"labels": ["A"], "datasets": [{"label": "B", "data": [1]}]},
        )
        
        assert result["success"] is False
        assert "Observer not initialized" in result["error"]


class TestA2UIBuilderChart:
    """Tests for the add_chart method in A2UIBuilder."""

    def test_add_chart_method(self):
        """add_chart should create a Chart component."""
        builder = A2UIBuilder(surface_id="test_chart")
        builder.create_surface()
        
        chart = builder.add_chart(
            chart_type="bar",
            data={
                "labels": ["A", "B", "C"],
                "datasets": [{"label": "Test", "data": [10, 20, 30]}],
            },
            options={"title": "Test Chart"},
        )
        
        assert chart.component == "Chart"
        assert chart.props["chartType"] == "bar"
        assert chart.props["data"]["labels"] == ["A", "B", "C"]
        assert chart.props["options"]["title"] == "Test Chart"
    
    def test_build_chart_payload(self):
        """build_update_components should include Chart component."""
        builder = A2UIBuilder(surface_id="test_chart")
        builder.create_surface(title="Test Chart")
        
        builder.add_text("Test Chart", variant="h3")
        builder.add_chart(
            chart_type="line",
            data={
                "labels": ["X", "Y"],
                "datasets": [{"label": "Z", "data": [1, 2]}],
            },
        )
        
        payload = builder.build_update_components()
        
        assert "surfaceId" in payload
        assert len(payload["components"]) >= 2
        
        # Find Chart component in tree
        def find_chart(comp):
            if comp.get("component") == "Chart":
                return comp
            for child in comp.get("children", []) or []:
                result = find_chart(child)
                if result:
                    return result
            return None
        
        chart_component = None
        for comp in payload["components"]:
            chart_component = find_chart(comp)
            if chart_component:
                break
        
        assert chart_component is not None
        assert chart_component["component"] == "Chart"
        assert chart_component["props"]["chartType"] == "line"


class TestCreateChartCardFactory:
    """Tests for the create_chart_card factory function."""

    def test_create_chart_card(self):
        """create_chart_card should create builder with chart component."""
        builder, surface = create_chart_card(
            title="工厂测试",
            chart_type="bar",
            data={
                "labels": ["P", "Q"],
                "datasets": [{"label": "R", "data": [100, 200]}],
            },
            surface_id="factory_test",
        )
        
        assert builder is not None
        assert surface is not None
        assert surface["surfaceId"] == "factory_test"
        
        payload = builder.build_update_components()
        chart_component = None
        
        def find_chart(comp):
            if comp.get("component") == "Chart":
                return comp
            for child in comp.get("children", []) or []:
                result = find_chart(child)
                if result:
                    return result
            return None
        
        for comp in payload["components"]:
            chart_component = find_chart(comp)
            if chart_component:
                break
        
        assert chart_component is not None
        assert chart_component["props"]["chartType"] == "bar"