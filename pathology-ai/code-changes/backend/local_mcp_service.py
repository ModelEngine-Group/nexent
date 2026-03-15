from fastmcp import FastMCP
import json
import re
from typing import Optional, List, Dict
from dataclasses import dataclass, field
from enum import Enum

# Create MCP server
local_mcp_service = FastMCP("nexent")

# ============ Medical Extension Classes ============

class ConfidenceLevel(Enum):
    """置信度等级"""
    HIGH = "HIGH"        # >85% 高置信度
    MEDIUM = "MEDIUM"    # 60-85% 中等置信度
    LOW = "LOW"          # <60% 低置信度
    UNCERTAIN = "UNCERTAIN"  # 不确定

class RiskLevel(Enum):
    """风险等级"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

@local_mcp_service.tool(name="test_tool_name",
                        description="test_tool_description")
async def demo_tool(para_1: str, para_2: int) -> str:
    print("tool is called successfully")
    print(para_1, para_2)
    return "success"


# ============ Medical Visualization Tools (Dynamic Generation) ============

@local_mcp_service.tool(
    name="generate_knowledge_graph",
    description="""生成医学知识图谱(Mermaid flowchart格式)。
    
参数说明:
- topic: 图谱主题
- nodes: 节点列表，用|分隔，格式为"节点1|节点2|节点3"
- relations: 关系列表，用|分隔，格式为"节点1-->节点2|节点2-->节点3"

使用方法: 先用知识库搜索获取相关概念，然后提取关键概念作为nodes，概念间的关系作为relations传入此工具。"""
)
async def generate_knowledge_graph(topic: str, nodes: str = "", relations: str = "") -> str:
    """Generate dynamic knowledge graph based on provided nodes and relations"""
    
    # Parse nodes and relations
    node_list = [n.strip() for n in nodes.split("|") if n.strip()] if nodes else []
    relation_list = [r.strip() for r in relations.split("|") if r.strip()] if relations else []
    
    # If no nodes provided, return instruction
    if not node_list:
        return f"""请先使用知识库搜索获取关于"{topic}"的相关信息，然后提取关键概念和关系，再调用此工具。

示例调用:
generate_knowledge_graph(
    topic="HIV感染机制",
    nodes="HIV病毒|CD4细胞|免疫系统|病毒复制|机会性感染",
    relations="HIV病毒-->CD4细胞|CD4细胞-->免疫系统|HIV病毒-->病毒复制|免疫系统-->机会性感染"
)"""
    
    # Create node map
    node_map = {node: f"N{i}" for i, node in enumerate(node_list)}
    
    # Parse relations and find root nodes (nodes that are sources but not targets)
    sources = set()
    targets = set()
    parsed_relations = []
    for rel in relation_list:
        if "-->" in rel:
            parts = rel.split("-->")
            if len(parts) == 2:
                src, tgt = parts[0].strip(), parts[1].strip()
                if src in node_map and tgt in node_map:
                    sources.add(src)
                    targets.add(tgt)
                    parsed_relations.append((src, tgt))
    
    # Group nodes by level (simple BFS-like grouping)
    root_nodes = [n for n in node_list if n in sources and n not in targets]
    if not root_nodes:
        root_nodes = [node_list[0]] if node_list else []
    
    # Build hierarchical layout using subgraphs
    lines = ["flowchart TB"]
    
    # Add all nodes with rounded rectangle style
    for i, node in enumerate(node_list):
        node_id = node_map[node]
        lines.append(f'    {node_id}(["{node}"])')
    
    # Add relations with labels
    for src, tgt in parsed_relations:
        lines.append(f"    {node_map[src]} --> {node_map[tgt]}")
    
    # Add gradient colors for better visual
    gradient_colors = [
        "#667eea", "#764ba2", "#f093fb", "#f5576c", 
        "#4facfe", "#00f2fe", "#43e97b", "#38f9d7",
        "#fa709a", "#fee140", "#a8edea", "#fed6e3"
    ]
    for i, node in enumerate(node_list):
        color = gradient_colors[i % len(gradient_colors)]
        lines.append(f"    style {node_map[node]} fill:{color},color:#fff,stroke:{color},stroke-width:2px")
    
    # Add link styles
    lines.append("    linkStyle default stroke:#666,stroke-width:2px")
    
    mermaid_code = f'''```mermaid
{chr(10).join(lines)}
```'''
    
    return mermaid_code


@local_mcp_service.tool(
    name="generate_diagnosis_flow",
    description="""生成诊断流程图(Mermaid flowchart格式)。

参数说明:
- disease: 疾病名称
- steps: 流程步骤列表，用|分隔，格式为"步骤1|步骤2|步骤3"
- decisions: 决策点列表，用|分隔，格式为"决策1:是选项,否选项|决策2:选项A,选项B"

使用方法: 根据知识库搜索结果，提取诊断流程的关键步骤和决策点。"""
)
async def generate_diagnosis_flow(disease: str, steps: str = "", decisions: str = "") -> str:
    """Generate compact horizontal diagnosis flowchart"""
    
    step_list = [s.strip() for s in steps.split("|") if s.strip()] if steps else []
    
    if not step_list:
        return f"""请搜索"{disease}"诊断流程，提取关键步骤。
示例: steps="初筛|确证|检测|治疗" """
    
    # Horizontal layout (left to right) - reduces height
    lines = ["flowchart LR"]
    
    # Full node names, horizontal flow
    for i, step in enumerate(step_list):
        node_id = f"S{i}"
        
        if i == 0:
            lines.append(f'    {node_id}(("{step}"))')
        elif i == len(step_list) - 1:
            lines.append(f'    {node_id}(("{step}"))')
        else:
            lines.append(f'    {node_id}["{step}"]')
    
    # Connect all nodes
    node_chain = " --> ".join([f"S{i}" for i in range(len(step_list))])
    lines.append(f"    {node_chain}")
    
    # Gradient colors
    colors = ["#6366f1", "#8b5cf6", "#a855f7", "#ec4899", "#f43f5e", "#f97316", "#22c55e"]
    for i in range(len(step_list)):
        color = colors[i % len(colors)]
        lines.append(f"    style S{i} fill:{color},color:#fff,stroke:#fff")
    
    mermaid_code = f'''```mermaid
{chr(10).join(lines)}
```'''
    
    return mermaid_code


@local_mcp_service.tool(
    name="generate_medical_chart",
    description="""生成统计图表(Mermaid格式)。

参数说明:
- chart_type: 图表类型 - pie(饼图), bar(柱状图), line(折线图)
- title: 图表标题
- labels: 标签列表，用|分隔，如"类别1|类别2|类别3"
- values: 数值列表，用|分隔，如"30|25|45"

使用方法: 根据数据分析结果，提取分类和数值传入此工具。"""
)
async def generate_medical_chart(chart_type: str, title: str, labels: str = "", values: str = "") -> str:
    """Generate dynamic statistics chart"""
    
    label_list = [l.strip() for l in labels.split("|") if l.strip()] if labels else []
    value_list = [v.strip() for v in values.split("|") if v.strip()] if values else []
    
    if not label_list or not value_list:
        return f"""请提供数据的标签和数值。

示例调用:
generate_medical_chart(
    chart_type="pie",
    title="知识分类分布",
    labels="病理机制|临床表现|诊断检测|治疗方案",
    values="35|25|20|20"
)"""
    
    if chart_type == "pie":
        pie_data = "\n".join([f'    "{label}" : {value}' for label, value in zip(label_list, value_list)])
        mermaid_code = f'''```mermaid
pie showData title {title}
{pie_data}
```'''
    elif chart_type == "bar":
        mermaid_code = f'''```mermaid
xychart-beta
    title "{title}"
    x-axis [{", ".join(label_list)}]
    y-axis "数量" 0 --> {int(max([int(v) for v in value_list]) * 1.2)}
    bar [{", ".join(value_list)}]
```'''
    elif chart_type == "line":
        mermaid_code = f'''```mermaid
xychart-beta
    title "{title}"
    x-axis [{", ".join(label_list)}]
    y-axis "数值" 0 --> {int(max([int(v) for v in value_list]) * 1.2)}
    line [{", ".join(value_list)}]
```'''
    else:
        mermaid_code = f"不支持的图表类型: {chart_type}。请使用 pie, bar, 或 line"
    
    return mermaid_code


# ============ Advanced Medical Visualization Tools ============

@local_mcp_service.tool(
    name="generate_radar_chart",
    description="""生成雷达图/蛛网图，用于多维度健康指标对比分析。

参数说明:
- title: 图表标题
- dimensions: 维度列表，用|分隔，如"指标1|指标2|指标3|指标4|指标5"
- values: 数值列表(0-100)，用|分隔，如"80|65|90|75|85"
- benchmark: 可选，基准值列表，用于对比

应用场景: 健康评估、症状严重程度评分、治疗效果多维对比"""
)
async def generate_radar_chart(title: str, dimensions: str = "", values: str = "", benchmark: str = "") -> str:
    """Generate radar/spider chart for multi-dimensional comparison"""
    
    dim_list = [d.strip() for d in dimensions.split("|") if d.strip()] if dimensions else []
    val_list = [v.strip() for v in values.split("|") if v.strip()] if values else []
    
    if not dim_list or not val_list or len(dim_list) < 3:
        return f"""雷达图需要至少3个维度。

示例调用:
generate_radar_chart(
    title="HIV患者健康评估",
    dimensions="免疫功能|病毒载量|肝功能|肾功能|心血管|神经系统",
    values="75|60|85|90|80|70"
)"""
    
    # 使用quadrantChart模拟雷达图效果，或用表格+描述替代
    # Mermaid暂不直接支持雷达图，用可视化描述+数据表格代替
    
    # 生成数据可视化表格
    table_rows = []
    for dim, val in zip(dim_list, val_list):
        val_int = int(val) if val.isdigit() else 50
        bar = "█" * (val_int // 10) + "░" * (10 - val_int // 10)
        status = "🟢" if val_int >= 80 else "🟡" if val_int >= 60 else "🔴"
        table_rows.append(f"| {dim} | {bar} | {val}% | {status} |")
    
    result = f"""### 📊 {title}

| 评估维度 | 指标条形图 | 数值 | 状态 |
|---------|-----------|------|------|
{chr(10).join(table_rows)}

**评估说明:** 🟢优秀(≥80) 🟡良好(60-79) 🔴需关注(<60)

```mermaid
pie showData title {title}
{chr(10).join([f'    "{dim}" : {val}' for dim, val in zip(dim_list, val_list)])}
```"""
    
    return result


@local_mcp_service.tool(
    name="generate_medical_guide",
    description="""生成清晰的就医指南，包含就医方式选择和就医流程。

参数说明:
- condition: 病情描述(如"HIV患者呼吸困难")
- urgency: 紧急程度(emergency/urgent/routine)
- patient_info: 患者关键信息(如"CD4计数150")

返回格式化的就医指南，包含多种就医方式和详细流程。"""
)
async def generate_medical_guide(condition: str, urgency: str = "urgent", patient_info: str = "") -> str:
    """Generate formatted medical guide"""
    
    urgency_map = {
        "emergency": ("🚨 紧急", "立即拨打120"),
        "urgent": ("⚠️ 紧急", "尽快就医"),
        "routine": ("📋 常规", "预约就诊"),
    }
    
    urgency_label, urgency_action = urgency_map.get(urgency, ("⚠️ 紧急", "尽快就医"))
    
    guide = f"""# 🏥 就医指南

## 📋 病情概述
- **症状**: {condition}
- **患者信息**: {patient_info if patient_info else "未提供"}
- **紧急程度**: {urgency_label}

---

## 🚗 就医方式选择

### 方式1: 拨打120 {"✅ 推荐" if urgency == "emergency" else ""}

| 步骤 | 操作 |
|------|------|
| 1️⃣ | 拨打120急救电话 |
| 2️⃣ | 告知: {condition}，{patient_info if patient_info else "病情紧急"} |
| 3️⃣ | 告知当前位置，等待救护车 |
| 4️⃣ | 由医护人员送往医院 |

### 方式2: 自行前往医院 {"✅ 推荐" if urgency == "urgent" else ""}

| 步骤 | 操作 |
|------|------|
| 1️⃣ | 选择最近的三甲医院 |
| 2️⃣ | 电话或微信预约挂号(急诊) |
| 3️⃣ | 由家属陪同前往 |
| 4️⃣ | 直接进入急诊科 |

### 方式3: 拨打医院急诊科

| 步骤 | 操作 |
|------|------|
| 1️⃣ | 拨打目标医院总机 |
| 2️⃣ | 转接急诊科说明病情 |
| 3️⃣ | 按指导前往医院 |

---

## 🏥 到院后流程

```mermaid
flowchart LR
    A[到达医院] --> B[挂号/急诊登记]
    B --> C[初诊评估]
    C --> D[体格检查]
    D --> E[辅助检查]
    E --> F[诊断确认]
    F --> G[治疗方案]
    G --> H[住院/出院]
```

### 详细步骤

| 序号 | 环节 | 具体内容 |
|------|------|----------|
| 1 | **登记** | 挂号/急诊登记，说明{condition} |
| 2 | **初诊** | 医生问诊，测量生命体征 |
| 3 | **体检** | 听诊肺部等体格检查 |
| 4 | **检查** | 胸部X光/CT、血液检查、血气分析 |
| 5 | **诊断** | 等待结果(通常24-48小时) |
| 6 | **治疗** | 制定方案，开始治疗 |
| 7 | **监测** | 监测疗效和不良反应 |

---

## ⚠️ 注意事项

- 携带身份证、医保卡
- 携带既往病历和检查报告
- 如有HIV相关资料请一并携带
- 保持通讯畅通

> 💡 **提示**: {urgency_action}，不要延误治疗时机
"""
    
    return guide


@local_mcp_service.tool(
    name="generate_timeline",
    description="""生成时间线图，用于展示疾病发展历程或治疗计划。

参数说明:
- title: 时间线标题
- events: 事件列表，用|分隔，格式为"时间点:事件描述|时间点:事件描述"

应用场景: 病程发展、治疗时间线、随访计划"""
)
async def generate_timeline(title: str, events: str = "") -> str:
    """Generate timeline diagram"""
    
    event_list = [e.strip() for e in events.split("|") if e.strip()] if events else []
    
    if not event_list:
        return f"""请提供时间线事件。

示例调用:
generate_timeline(
    title="HIV感染自然病程",
    events="感染期:HIV病毒侵入|急性期:病毒快速复制|潜伏期:免疫平衡|AIDS期:免疫崩溃"
)"""
    
    lines = ["timeline", f"    title {title}"]
    
    for event in event_list:
        if ":" in event:
            time_point, description = event.split(":", 1)
            lines.append(f"    {time_point.strip()}")
            lines.append(f"        : {description.strip()}")
        else:
            lines.append(f"    {event}")
    
    mermaid_code = f'''```mermaid
{chr(10).join(lines)}
```'''
    
    return mermaid_code


@local_mcp_service.tool(
    name="generate_gantt_chart",
    description="""生成甘特图，用于治疗计划和疗程安排。

参数说明:
- title: 图表标题
- tasks: 任务列表，用|分隔，格式为"任务名:开始日期,持续天数|任务名:开始日期,持续天数"

应用场景: 治疗方案安排、康复计划、随访时间表"""
)
async def generate_gantt_chart(title: str, tasks: str = "") -> str:
    """Generate Gantt chart for treatment planning"""
    
    task_list = [t.strip() for t in tasks.split("|") if t.strip()] if tasks else []
    
    if not task_list:
        return f"""请提供治疗任务安排。

示例调用:
generate_gantt_chart(
    title="HIV抗病毒治疗计划",
    tasks="初始评估:2024-01-01,7d|药物启动:2024-01-08,30d|首次复查:2024-02-07,1d|稳定期治疗:2024-02-08,90d"
)"""
    
    lines = [
        "gantt",
        f"    title {title}",
        "    dateFormat YYYY-MM-DD",
        "    section 治疗阶段"
    ]
    
    for i, task in enumerate(task_list):
        if ":" in task:
            task_name, timing = task.split(":", 1)
            if "," in timing:
                start_date, duration = timing.split(",", 1)
                lines.append(f"    {task_name.strip()} : t{i}, {start_date.strip()}, {duration.strip()}")
            else:
                lines.append(f"    {task_name.strip()} : t{i}, {timing.strip()}")
        else:
            lines.append(f"    {task} : t{i}, 7d")
    
    mermaid_code = f'''```mermaid
{chr(10).join(lines)}
```'''
    
    return mermaid_code


@local_mcp_service.tool(
    name="generate_quadrant_chart",
    description="""生成象限图，用于风险评估和优先级分析。

参数说明:
- title: 图表标题
- x_axis: X轴标签(低到高)
- y_axis: Y轴标签(低到高)
- items: 项目列表，格式为"项目名:x坐标,y坐标|项目名:x坐标,y坐标" (坐标范围0-1)

应用场景: 疾病风险评估、治疗优先级、药物选择矩阵"""
)
async def generate_quadrant_chart(title: str, x_axis: str = "紧急程度", y_axis: str = "重要程度", items: str = "") -> str:
    """Generate quadrant chart for risk assessment"""
    
    item_list = [i.strip() for i in items.split("|") if i.strip()] if items else []
    
    if not item_list:
        return f"""请提供评估项目。

示例调用:
generate_quadrant_chart(
    title="HIV并发症处理优先级",
    x_axis="紧急程度",
    y_axis="严重程度",
    items="机会性感染:0.9,0.85|肝功能异常:0.6,0.7|皮疹反应:0.4,0.3|轻度贫血:0.2,0.4"
)"""
    
    lines = [
        "quadrantChart",
        f"    title {title}",
        f'    x-axis "低{x_axis}" --> "高{x_axis}"',
        f'    y-axis "低{y_axis}" --> "高{y_axis}"',
        '    quadrant-1 "紧急重要"',
        '    quadrant-2 "重要不紧急"',
        '    quadrant-3 "不重要不紧急"',
        '    quadrant-4 "紧急不重要"'
    ]
    
    for item in item_list:
        if ":" in item:
            name, coords = item.split(":", 1)
            if "," in coords:
                x, y = coords.split(",", 1)
                lines.append(f'    "{name.strip()}": [{x.strip()}, {y.strip()}]')
    
    mermaid_code = f'''```mermaid
{chr(10).join(lines)}
```'''
    
    return mermaid_code


@local_mcp_service.tool(
    name="generate_state_diagram",
    description="""生成状态转换图，用于展示疾病状态变化。

参数说明:
- title: 图表标题
- states: 状态列表，用|分隔
- transitions: 转换列表，格式为"状态1-->状态2:触发条件|状态2-->状态3:触发条件"

应用场景: 疾病分期、病情演变、治疗响应状态"""
)
async def generate_state_diagram(title: str, states: str = "", transitions: str = "") -> str:
    """Generate state diagram for disease progression"""
    
    state_list = [s.strip() for s in states.split("|") if s.strip()] if states else []
    trans_list = [t.strip() for t in transitions.split("|") if t.strip()] if transitions else []
    
    if not state_list or not trans_list:
        return f"""请提供状态和转换关系。

示例调用:
generate_state_diagram(
    title="HIV感染分期",
    states="健康|急性感染|临床潜伏期|AIDS期",
    transitions="健康-->急性感染:HIV暴露|急性感染-->临床潜伏期:免疫应答|临床潜伏期-->AIDS期:CD4<200"
)"""
    
    lines = ["stateDiagram-v2"]
    
    # Add state descriptions
    state_map = {s: f"s{i}" for i, s in enumerate(state_list)}
    for state, sid in state_map.items():
        lines.append(f'    {sid} : {state}')
    
    # Add transitions
    for trans in trans_list:
        if "-->" in trans:
            parts = trans.split("-->")
            if len(parts) == 2:
                src = parts[0].strip()
                tgt_label = parts[1]
                if ":" in tgt_label:
                    tgt, label = tgt_label.split(":", 1)
                    tgt = tgt.strip()
                    if src in state_map and tgt in state_map:
                        lines.append(f'    {state_map[src]} --> {state_map[tgt]} : {label.strip()}')
                else:
                    tgt = tgt_label.strip()
                    if src in state_map and tgt in state_map:
                        lines.append(f'    {state_map[src]} --> {state_map[tgt]}')
    
    # Mark start and end
    if state_list:
        lines.insert(1, f'    [*] --> {state_map[state_list[0]]}')
        lines.append(f'    {state_map[state_list[-1]]} --> [*]')
    
    mermaid_code = f'''```mermaid
{chr(10).join(lines)}
```'''
    
    return mermaid_code


@local_mcp_service.tool(
    name="generate_sankey_diagram",
    description="""生成桑基图，用于展示流量和转换关系。

参数说明:
- title: 图表标题
- flows: 流向列表，格式为"源,目标,数量|源,目标,数量"

应用场景: 诊断分流、患者转归、治疗路径"""
)
async def generate_sankey_diagram(title: str, flows: str = "") -> str:
    """Generate Sankey diagram for flow visualization"""
    
    flow_list = [f.strip() for f in flows.split("|") if f.strip()] if flows else []
    
    if not flow_list:
        return f"""请提供流向数据。

示例调用:
generate_sankey_diagram(
    title="HIV筛查诊断流程",
    flows="初筛人群,阳性,150|初筛人群,阴性,850|阳性,确证阳性,140|阳性,假阳性,10|确证阳性,入组治疗,130|确证阳性,暂缓治疗,10"
)"""
    
    lines = ["sankey-beta", ""]
    
    for flow in flow_list:
        parts = flow.split(",")
        if len(parts) >= 3:
            src, tgt, val = parts[0].strip(), parts[1].strip(), parts[2].strip()
            lines.append(f'{src},{tgt},{val}')
    
    mermaid_code = f'''```mermaid
{chr(10).join(lines)}
```

**{title}** - 流向分析图'''
    
    return mermaid_code


# ============ 诊断模拟器 - 医学教育游戏化 ============

import random

# 预设病例库
CASE_LIBRARY = {
    "hiv_basic": {
        "patient": "李先生，32岁，已婚",
        "chief_complaint": "反复发热、乏力1个月",
        "history": {
            "发热情况": "低热为主，体温37.5-38.2℃，午后明显",
            "其他症状": "明显乏力，体重下降约5kg",
            "既往史": "既往体健，无慢性病史",
            "接触史": "3个月前有不洁性行为史",
            "用药情况": "自行服用退烧药，效果不佳"
        },
        "physical_exam": {
            "一般情况": "神志清楚，精神欠佳，消瘦",
            "淋巴结": "颈部、腋窝淋巴结肿大，无压痛",
            "口腔": "可见口腔白斑",
            "皮肤": "无皮疹"
        },
        "lab_tests": {
            "血常规": "WBC 3.2×10^9/L↓，淋巴细胞比例降低",
            "HIV抗体初筛": "阳性",
            "HIV确证试验": "阳性",
            "CD4计数": "186个/μL↓↓",
            "病毒载量": "125,000 copies/mL"
        },
        "diagnosis": "HIV感染/AIDS期",
        "difficulty": 1,
        "key_points": ["接触史询问", "淋巴结检查", "HIV筛查", "CD4计数"]
    },
    "hiv_opportunistic": {
        "patient": "王女士，45岁",
        "chief_complaint": "咳嗽、气促2周，加重3天",
        "history": {
            "呼吸症状": "干咳为主，活动后气促明显",
            "发热情况": "持续低热，夜间盗汗",
            "既往史": "HIV感染史5年，未规律服药",
            "用药情况": "间断服用抗病毒药物"
        },
        "physical_exam": {
            "一般情况": "呼吸急促，口唇轻度发绀",
            "肺部": "双肺呼吸音粗，可闻及少量湿啰音",
            "口腔": "舌面白色斑块，可刮除"
        },
        "lab_tests": {
            "血气分析": "PaO2 58mmHg↓",
            "CD4计数": "45个/μL↓↓↓",
            "胸部CT": "双肺弥漫性磨玻璃影",
            "痰检": "六胺银染色见肺孢子菌"
        },
        "diagnosis": "AIDS合并肺孢子菌肺炎(PCP)",
        "difficulty": 2,
        "key_points": ["服药依从性", "机会性感染识别", "CD4与感染风险"]
    }
}

@local_mcp_service.tool(
    name="start_diagnosis_game",
    description="""启动诊断模拟游戏。用户扮演医生，AI扮演患者，进行问诊练习。

参数说明:
- difficulty: 难度等级 (1=初级, 2=中级, 3=高级)
- case_type: 病例类型，可选 "hiv_basic"(HIV基础), "hiv_opportunistic"(机会性感染), "random"(随机)

游戏流程: 问诊→体检→检查→诊断，最终给出评分"""
)
async def start_diagnosis_game(difficulty: int = 1, case_type: str = "random") -> str:
    """Start an interactive diagnosis simulation game"""
    
    # 选择病例
    if case_type == "random" or case_type not in CASE_LIBRARY:
        case_key = random.choice(list(CASE_LIBRARY.keys()))
    else:
        case_key = case_type
    
    case = CASE_LIBRARY[case_key]
    
    result = f"""
## 🏥 诊断模拟器 - 病例开始

### 👤 患者信息
**{case['patient']}**

### 💬 主诉
> "{case['chief_complaint']}"

---

### 📋 当前阶段：问诊 (第1步/共4步)

**请选择您要询问的内容：**

[btn:询问发热详情] [btn:询问其他症状] [btn:询问既往病史]
[btn:询问接触史] [btn:询问用药情况] [btn:进入体格检查]

💡 **提示**：全面的问诊是正确诊断的基础，请尽量收集完整病史信息。

---
*难度：{"⭐" * case['difficulty']} | 病例ID：{case_key}*
"""
    
    return result


@local_mcp_service.tool(
    name="diagnosis_action",
    description="""在诊断模拟中执行动作（问诊/检查/诊断）。

参数说明:
- case_id: 病例ID
- action_type: 动作类型 (ask=问诊, exam=体检, test=检查, diagnose=诊断)
- action_detail: 具体动作内容

示例: diagnosis_action(case_id="hiv_basic", action_type="ask", action_detail="发热情况")"""
)
async def diagnosis_action(case_id: str, action_type: str, action_detail: str) -> str:
    """Process a diagnosis action in the simulation"""
    
    if case_id not in CASE_LIBRARY:
        return "❌ 病例不存在，请先使用 start_diagnosis_game 开始新游戏"
    
    case = CASE_LIBRARY[case_id]
    
    if action_type == "ask":
        # 问诊阶段
        if action_detail in case["history"]:
            response = case["history"][action_detail]
            return f"""
### 👤 患者回答

**关于{action_detail}：**
> "{response}"

---

**继续问诊或进入下一阶段：**

[btn:询问发热情况] [btn:询问其他症状] [btn:询问既往史]
[btn:询问接触史] [btn:询问用药情况] [btn:进入体格检查]
"""
        else:
            return f"""
### 👤 患者回答

> "医生，这个...我不太清楚怎么回答。您能换个方式问吗？"

**可询问的内容：** {', '.join(case['history'].keys())}

[btn:询问发热情况] [btn:询问其他症状] [btn:询问既往史]
[btn:询问接触史] [btn:询问用药情况] [btn:进入体格检查]
"""
    
    elif action_type == "exam":
        # 体格检查阶段
        if action_detail in case["physical_exam"]:
            finding = case["physical_exam"][action_detail]
            return f"""
### 🩺 体格检查结果

**{action_detail}检查：**
> {finding}

---

**继续检查或进入下一阶段：**

[btn:检查一般情况] [btn:检查淋巴结] [btn:检查口腔] [btn:检查皮肤]
[btn:开具辅助检查]
"""
        else:
            return f"""
### 🩺 体格检查

该部位检查未见明显异常。

**可检查的项目：** {', '.join(case['physical_exam'].keys())}

[btn:检查一般情况] [btn:检查淋巴结] [btn:检查口腔] [btn:检查皮肤]
[btn:开具辅助检查]
"""
    
    elif action_type == "test":
        # 辅助检查阶段
        if action_detail in case["lab_tests"]:
            result = case["lab_tests"][action_detail]
            return f"""
### 🔬 检查结果

**{action_detail}：**
> {result}

---

**继续检查或给出诊断：**

[btn:血常规] [btn:HIV抗体初筛] [btn:HIV确证试验] [btn:CD4计数] [btn:病毒载量]
[btn:给出诊断结论]
"""
        else:
            return f"""
### 🔬 辅助检查

该项目暂无结果。

**可开具的检查：** {', '.join(case['lab_tests'].keys())}

[btn:血常规] [btn:HIV抗体初筛] [btn:CD4计数] [btn:病毒载量]
[btn:给出诊断结论]
"""
    
    elif action_type == "diagnose":
        # 诊断阶段 - 评分
        correct = case["diagnosis"].lower() in action_detail.lower() or "hiv" in action_detail.lower()
        
        if correct:
            score = 85
            feedback = "🎉 诊断正确！"
        else:
            score = 60
            feedback = f"诊断有偏差。正确诊断应为：**{case['diagnosis']}**"
        
        return f"""
## 🏆 诊断模拟完成！

### 您的诊断
> {action_detail}

### 标准答案
> **{case['diagnosis']}**

---

### 📊 评分结果

| 评估项目 | 得分 | 说明 |
|---------|------|------|
| 问诊完整度 | 20/25 | 基本覆盖主要病史 |
| 体检针对性 | 22/25 | 检查项目较合理 |
| 辅助检查 | 23/30 | 检查选择恰当 |
| 诊断准确性 | {20 if correct else 10}/20 | {feedback} |

**总分：{score}/100** {"⭐⭐⭐ 优秀！" if score >= 80 else "⭐⭐ 良好" if score >= 60 else "⭐ 需加强"}

---

### 📚 知识要点回顾
- **关键线索**：{', '.join(case['key_points'])}
- **诊断依据**：HIV确证试验阳性 + CD4<200 = AIDS期

[btn:开始新病例] [btn:查看HIV知识图谱] [btn:返回主页]
"""
    
    return "未知动作类型，请使用 ask/exam/test/diagnose"


# ============ Pathology Image Search Tool ============

# 病理图片分类映射
PATHOLOGY_CATEGORIES = {
    "HIV": ["Immunopathology", "Infection"],
    "AIDS": ["Immunopathology", "Infection"],
    "免疫": ["Immunopathology"],
    "感染": ["Infection"],
    "心血管": ["Cardiovascular_Pathology", "Atherosclerosis"],
    "动脉粥样硬化": ["Atherosclerosis"],
    "肺": ["Pulmonary_Pathology"],
    "呼吸": ["Pulmonary_Pathology"],
    "肿瘤": ["Neoplasia"],
    "癌": ["Neoplasia"],
    "神经": ["CNS_Pathology"],
    "脑": ["CNS_Pathology"],
    "胃肠": ["Gastrointestinal_Pathology"],
    "消化": ["Gastrointestinal_Pathology"],
    "血液": ["Hematopathology"],
    "内分泌": ["Endocrine_Pathology"],
    "炎症": ["Inflammation"],
    "细胞损伤": ["Cell_Injury"],
    "电镜": ["Electron_Microscopy"],
    "组织学": ["Histology"],
}

# 每个分类的示例图片及描述
CATEGORY_IMAGES = {
    "Immunopathology": [
        ("0000eb2357e8.jpg", "淋巴细胞浸润，显示免疫反应"),
        ("02a4161191a8.jpg", "免疫复合物沉积"),
        ("05640ed631c2.jpg", "T细胞介导的免疫损伤"),
        ("0f22d896b594.jpg", "B细胞增殖区域"),
        ("11a4c1f09706.jpg", "巨噬细胞吞噬活动"),
    ],
    "Infection": [
        ("075f763add8c.jpg", "病原体感染灶"),
        ("0c81a1988e19.jpg", "炎症细胞浸润"),
        ("1295dab30912.jpg", "感染性肉芽肿"),
        ("17d26c8e5c88.jpg", "组织坏死区域"),
        ("22a479f58f04.jpg", "微生物聚集"),
    ],
    "Cardiovascular_Pathology": [
        ("0606593bb423.jpg", "心肌纤维化"),
        ("070dc3e73d66.jpg", "血管内膜增厚"),
        ("075032476806.jpg", "心脏瓣膜病变"),
    ],
    "Atherosclerosis": [
        ("0ba1b0082d67.jpg", "动脉粥样斑块形成"),
        ("10474b1d8799.jpg", "脂质沉积"),
        ("1575b0d16a3b.jpg", "血管内膜损伤"),
    ],
    "Pulmonary_Pathology": [
        ("f9f1242c5380.jpg", "肺泡结构改变"),
        ("f89a55b691ae.jpg", "支气管炎症"),
        ("f7cf9f1ed751.jpg", "肺间质纤维化"),
    ],
    "Neoplasia": [
        ("00106d3af3f9.jpg", "肿瘤细胞异型性"),
        ("0074eed7dc88.jpg", "恶性增殖"),
        ("00f1f7a78ea3.jpg", "肿瘤浸润边界"),
    ],
    "CNS_Pathology": [
        ("021b3f20db2f.jpg", "神经元变性"),
        ("02bf3c50f823.jpg", "胶质细胞增生"),
        ("083d23ccdd4d.jpg", "脑组织水肿"),
    ],
    "Gastrointestinal_Pathology": [
        ("00d6f994fc87.jpg", "肠黏膜炎症"),
        ("0288d47f9f5b.jpg", "胃溃疡病变"),
        ("02a0e46f7c3d.jpg", "肠绒毛萎缩"),
    ],
    "Hematopathology": [
        ("016b9b2e2cd4.jpg", "骨髓增生"),
        ("01e00df21ac8.jpg", "淋巴瘤细胞"),
        ("043ce9118f01.jpg", "白血病浸润"),
    ],
    "Endocrine_Pathology": [
        ("0b21f350e3e9.jpg", "甲状腺滤泡"),
        ("0ddee8a2b4f9.jpg", "肾上腺皮质增生"),
        ("13cfc5ac2e3b.jpg", "垂体腺瘤"),
    ],
    "Inflammation": [
        ("00e82b2ec4d0.jpg", "急性炎症反应"),
        ("04ad03b22a75.jpg", "慢性炎症浸润"),
        ("05eef6d51eaa.jpg", "肉芽组织形成"),
    ],
    "Cell_Injury": [
        ("063a113740cc.jpg", "细胞水肿"),
        ("08672f745e11.jpg", "细胞凋亡"),
        ("0d0db3ff6e2f.jpg", "坏死组织"),
    ],
    "Electron_Microscopy": [
        ("09be997db580.jpg", "细胞超微结构"),
        ("0df73df90afe.jpg", "线粒体形态"),
        ("1c9d27289d01.jpg", "内质网变化"),
    ],
    "Histology": [
        ("01b94b8025af.jpg", "正常组织结构"),
        ("029bc2eb4a0b.jpg", "细胞形态学"),
        ("02c81a6b8380.jpg", "组织切片染色"),
    ],
}

@local_mcp_service.tool(
    name="search_pathology_images",
    description="""搜索病理学图片。根据关键词返回相关的病理学图片URL。

支持的关键词类别:
- HIV/AIDS/免疫: 免疫病理学图片
- 感染: 感染性疾病图片  
- 心血管/动脉粥样硬化: 心血管病理图片
- 肺/呼吸: 肺部病理图片
- 肿瘤/癌: 肿瘤病理图片
- 神经/脑: 神经系统病理图片
- 胃肠/消化: 消化系统病理图片
- 血液: 血液病理图片
- 炎症: 炎症病理图片
- 电镜: 电子显微镜图片
- 组织学: 组织学图片

返回Markdown格式的图片，可直接在回复中使用。"""
)
async def search_pathology_images(keyword: str, count: int = 6) -> str:
    """Search and return pathology images based on keyword"""
    
    # 限制返回数量（3的倍数，便于网格布局）
    count = min(count, 9)
    if count % 3 != 0:
        count = (count // 3 + 1) * 3
    
    # 查找匹配的分类
    matched_categories = []
    keyword_lower = keyword.lower()
    
    for key, categories in PATHOLOGY_CATEGORIES.items():
        if key.lower() in keyword_lower or keyword_lower in key.lower():
            matched_categories.extend(categories)
    
    # 去重
    matched_categories = list(set(matched_categories))
    
    if not matched_categories:
        # 默认返回免疫病理学图片
        matched_categories = ["Immunopathology", "Infection"]
    
    # 收集图片信息 (display_url, backend_url, description, category)
    image_data = []
    # 前端显示用localhost，后端分析用host.docker.internal
    display_base_url = "http://localhost:9012/by_category"
    backend_base_url = "http://host.docker.internal:9012/by_category"
    
    for category in matched_categories:
        if category in CATEGORY_IMAGES:
            for img_tuple in CATEGORY_IMAGES[category]:
                img_file, description = img_tuple
                display_url = f"{display_base_url}/{category}/{img_file}"
                backend_url = f"{backend_base_url}/{category}/{img_file}"
                image_data.append((display_url, backend_url, description, category))
                if len(image_data) >= count:
                    break
        if len(image_data) >= count:
            break
    
    if not image_data:
        return f"未找到与'{keyword}'相关的病理图片"
    
    # 分类名称中文映射
    category_cn = {
        "Immunopathology": "免疫病理学",
        "Infection": "感染病理学",
        "Cardiovascular_Pathology": "心血管病理学",
        "Atherosclerosis": "动脉粥样硬化",
        "Pulmonary_Pathology": "肺部病理学",
        "Neoplasia": "肿瘤病理学",
        "CNS_Pathology": "神经病理学",
        "Gastrointestinal_Pathology": "消化系统病理学",
        "Hematopathology": "血液病理学",
        "Endocrine_Pathology": "内分泌病理学",
        "Inflammation": "炎症病理学",
        "Cell_Injury": "细胞损伤",
        "Electron_Microscopy": "电子显微镜",
        "Histology": "组织学",
    }
    
    # 生成简洁的Markdown格式
    result = f"## 🔬 {keyword}相关病理图片\n\n"
    result += f"已找到 {len(image_data)} 张相关病理学图片：\n\n"
    
    # 使用简洁的Markdown图片格式
    for i, (display_url, backend_url, desc, cat) in enumerate(image_data, 1):
        cat_cn = category_cn.get(cat, cat)
        result += f"**{i}. {cat_cn}** - {desc}\n\n"
        result += f"![{desc}]({display_url})\n\n"
    
    # 提供后端分析用的URL列表（隐藏格式）
    backend_urls = [item[1] for item in image_data]
    result += f"\n---\n\n"
    result += f"📊 **图片来源**: {', '.join([category_cn.get(c, c) for c in matched_categories])}\n\n"
    result += f"🔍 **AI分析URL**: `{backend_urls}`\n"
    
    return result


# ============ Chain-of-Diagnosis (CoD) Tool ============

# HIV相关知识库
HIV_KNOWLEDGE = {
    "opportunistic_infections": [
        "肺孢子虫肺炎 (PCP)", "巨细胞病毒感染 (CMV)", "隐球菌脑膜炎",
        "卡波西肉瘤", "结核病", "弓形虫脑病"
    ],
    "cd4_thresholds": {"severe": 200, "moderate": 350, "mild": 500},
    "pcp_symptoms": ["干咳", "呼吸困难", "发热", "低氧血症"],
    "crypto_symptoms": ["头痛", "发热", "意识改变", "颈强直"],
}

@local_mcp_service.tool(
    name="chain_of_diagnosis",
    description="""执行诊断推理链(Chain-of-Diagnosis, CoD)分析。

这是一个创新的结构化诊断方法，分5个步骤进行临床推理：
1. 症状分析 - 识别和分析主要症状
2. 病史关联 - 关联既往病史
3. 鉴别诊断 - 列出可能的诊断
4. 检查建议 - 建议进一步检查
5. 诊断结论 - 给出最终诊断和置信度

参数:
- symptoms: 患者症状描述
- medical_history: 既往病史(可选)
- lab_results: 实验室检查结果(可选)
- imaging_findings: 影像学发现(可选)

返回结构化的诊断推理报告，包含置信度评估。"""
)
async def chain_of_diagnosis(
    symptoms: str,
    medical_history: str = "",
    lab_results: str = "",
    imaging_findings: str = ""
) -> str:
    """Execute Chain-of-Diagnosis analysis"""
    
    reasoning_steps = []
    evidence_collected = []
    
    # Step 1: 症状分析
    symptom_analysis = []
    symptom_patterns = {
        "呼吸系统": ["咳嗽", "干咳", "呼吸困难", "气短", "胸痛"],
        "发热相关": ["发热", "发烧", "高热", "低热"],
        "神经系统": ["头痛", "意识改变", "抽搐", "视力改变"],
        "消化系统": ["腹泻", "恶心", "呕吐", "腹痛"],
        "皮肤表现": ["皮疹", "紫色斑块", "溃疡"],
    }
    
    for system, patterns in symptom_patterns.items():
        found = [p for p in patterns if p in symptoms]
        if found:
            evidence_collected.extend(found)
            symptom_analysis.append(f"{system}: {', '.join(found)}")
    
    step1_content = "; ".join(symptom_analysis) if symptom_analysis else "症状信息不足"
    step1_confidence = 0.8 if evidence_collected else 0.3
    reasoning_steps.append(("症状分析", step1_content, step1_confidence))
    
    # Step 2: 病史关联
    history_analysis = ""
    is_hiv = False
    if medical_history:
        if any(kw in medical_history.lower() for kw in ["hiv", "aids", "艾滋", "免疫缺陷"]):
            is_hiv = True
            history_analysis = "患者有HIV/AIDS病史，需考虑机会性感染"
            evidence_collected.append("HIV/AIDS病史")
        if any(kw in medical_history for kw in ["免疫抑制", "化疗", "器官移植"]):
            history_analysis += "；存在免疫抑制因素"
            evidence_collected.append("免疫抑制状态")
    
    if not history_analysis:
        history_analysis = "无特殊病史或病史信息不完整"
    
    step2_confidence = 0.7 if is_hiv else 0.4
    reasoning_steps.append(("病史关联", history_analysis, step2_confidence))
    
    # Step 3: 鉴别诊断
    differentials = []
    cd4_count = None
    
    if lab_results:
        cd4_match = re.search(r'cd4[^\d]*(\d+)', lab_results.lower())
        if cd4_match:
            cd4_count = int(cd4_match.group(1))
            evidence_collected.append(f"CD4计数: {cd4_count}")
    
    if is_hiv:
        if cd4_count and cd4_count < 200:
            if any(s in symptoms for s in ["干咳", "呼吸困难", "发热"]):
                differentials.append("肺孢子虫肺炎 (PCP) - 高度怀疑")
                differentials.append("细菌性肺炎")
                differentials.append("肺结核")
            elif any(s in symptoms for s in ["头痛", "意识"]):
                differentials.append("隐球菌脑膜炎")
                differentials.append("弓形虫脑病")
        else:
            differentials.append("需要更多信息进行鉴别")
    else:
        if any(s in symptoms for s in ["咳嗽", "发热"]):
            differentials.extend(["社区获得性肺炎", "病毒性上呼吸道感染", "支气管炎"])
    
    step3_content = "鉴别诊断: " + ", ".join(differentials) if differentials else "需要更多信息"
    step3_confidence = 0.75 if differentials else 0.3
    reasoning_steps.append(("鉴别诊断", step3_content, step3_confidence))
    
    # Step 4: 检查建议
    suggestions = []
    if "PCP" in step3_content or "肺孢子虫" in step3_content:
        suggestions = ["诱导痰检查（银染色）", "血气分析", "乳酸脱氢酶(LDH)", "胸部CT"]
    elif "脑膜炎" in step3_content:
        suggestions = ["腰椎穿刺", "脑脊液墨汁染色", "隐球菌抗原检测", "头颅MRI"]
    else:
        suggestions = ["血常规", "C反应蛋白", "胸部X线"]
    
    step4_content = "建议检查: " + ", ".join(suggestions[:4])
    reasoning_steps.append(("检查建议", step4_content, 0.8))
    
    # Step 5: 诊断结论
    primary_diagnosis = "诊断待定"
    if "高度怀疑" in step3_content:
        match = re.search(r'([^,]+)\s*-\s*高度怀疑', step3_content)
        if match:
            primary_diagnosis = match.group(1).strip()
    
    step5_content = f"最可能的诊断: {primary_diagnosis}"
    step5_confidence = 0.85 if "高度怀疑" in step3_content else 0.5
    reasoning_steps.append(("诊断结论", step5_content, step5_confidence))
    
    # 计算总体置信度
    weights = [0.15, 0.15, 0.25, 0.15, 0.30]
    overall_confidence = sum(s[2] * w for s, w in zip(reasoning_steps, weights))
    overall_confidence = min(overall_confidence + len(evidence_collected) * 0.02, 1.0)
    
    # 确定置信度等级
    if overall_confidence >= 0.85:
        conf_level = "HIGH"
        conf_emoji = "🟢"
    elif overall_confidence >= 0.60:
        conf_level = "MEDIUM"
        conf_emoji = "🟡"
    elif overall_confidence >= 0.30:
        conf_level = "LOW"
        conf_emoji = "🔴"
    else:
        conf_level = "UNCERTAIN"
        conf_emoji = "⚪"
    
    # 生成报告
    report = "# 🏥 诊断推理链(CoD)分析报告\n\n"
    report += "---\n\n"
    
    for i, (step_name, content, conf) in enumerate(reasoning_steps, 1):
        report += f"## 【步骤{i}】{step_name}\n\n"
        report += f"{content}\n\n"
        report += f"*步骤置信度: {conf*100:.0f}%*\n\n"
    
    report += "---\n\n"
    report += f"## 📊 诊断结果\n\n"
    report += f"**主要诊断**: {primary_diagnosis}\n\n"
    report += f"**鉴别诊断**: {', '.join([d.split(' - ')[0] for d in differentials if d != primary_diagnosis][:3])}\n\n"
    report += f"**置信度**: {conf_emoji} **{conf_level}** ({overall_confidence*100:.1f}%)\n\n"
    
    # 建议
    report += "## 💡 建议\n\n"
    if "PCP" in primary_diagnosis:
        report += "- 首选治疗: 复方磺胺甲噁唑 (TMP-SMX)\n"
        report += "- 严重病例考虑糖皮质激素辅助治疗\n"
        report += "- 监测血氧饱和度\n"
    
    if conf_level in ["LOW", "UNCERTAIN"]:
        report += "- 建议进一步检查以明确诊断\n"
        report += "- 必要时请专科会诊\n"
    
    report += "\n## ⚠️ 重要提示\n\n"
    report += "> 本诊断由AI辅助生成，仅供参考。最终诊断请以临床医生判断为准。\n"
    
    return report


# ============ Confidence Evaluation Tool ============

@local_mcp_service.tool(
    name="evaluate_diagnosis_confidence",
    description="""评估诊断的置信度和风险等级。

基于证据充分度、一致性、完整性等维度进行量化评估，返回：
- 总体置信度分数和等级
- 各维度得分
- 风险等级评估
- 改进建议

参数:
- diagnosis: 诊断结果
- symptoms: 症状列表，用逗号分隔
- evidence: 支持证据，用逗号分隔
- lab_results: 实验室结果(可选)"""
)
async def evaluate_diagnosis_confidence(
    diagnosis: str,
    symptoms: str = "",
    evidence: str = "",
    lab_results: str = ""
) -> str:
    """Evaluate diagnosis confidence"""
    
    symptom_list = [s.strip() for s in symptoms.split(",") if s.strip()]
    evidence_list = [e.strip() for e in evidence.split(",") if e.strip()]
    
    # 1. 证据充分度
    evidence_weights = {
        "病理确诊": 1.0, "实验室确诊": 0.9, "影像学典型": 0.8,
        "临床症状典型": 0.7, "病史支持": 0.6
    }
    evidence_score = 0.3
    for e in evidence_list:
        for key, weight in evidence_weights.items():
            if key in e:
                evidence_score = max(evidence_score, weight)
                break
        else:
            evidence_score += 0.1
    evidence_score = min(evidence_score, 1.0)
    
    # 2. 一致性评估
    diagnosis_symptom_map = {
        "肺孢子虫肺炎": ["干咳", "呼吸困难", "发热"],
        "PCP": ["干咳", "呼吸困难", "发热"],
        "隐球菌脑膜炎": ["头痛", "发热", "意识改变"],
        "肺炎": ["咳嗽", "发热", "胸痛"],
    }
    consistency_score = 0.5
    for diag_key, expected in diagnosis_symptom_map.items():
        if diag_key in diagnosis:
            matched = sum(1 for s in symptom_list if any(es in s for es in expected))
            consistency_score += min(matched / len(expected) * 0.4, 0.4)
            break
    
    # 3. 完整性评估
    completeness_score = 0.0
    if symptom_list:
        completeness_score += 0.3
    if evidence_list:
        completeness_score += 0.3
    if lab_results:
        completeness_score += 0.4
    
    # 4. 确定性评估
    certainty_score = 0.5
    uncertain_kw = ["可能", "疑似", "待排除", "考虑"]
    certain_kw = ["确诊", "明确", "典型"]
    for kw in uncertain_kw:
        if kw in diagnosis:
            certainty_score -= 0.1
    for kw in certain_kw:
        if kw in diagnosis:
            certainty_score += 0.15
    certainty_score = max(min(certainty_score, 1.0), 0.1)
    
    # 计算总体置信度
    weights = {"evidence": 0.35, "consistency": 0.25, "completeness": 0.20, "certainty": 0.20}
    overall_score = (
        evidence_score * weights["evidence"] +
        consistency_score * weights["consistency"] +
        completeness_score * weights["completeness"] +
        certainty_score * weights["certainty"]
    )
    
    # 置信度等级
    if overall_score >= 0.85:
        level = "HIGH"
        level_emoji = "🟢"
    elif overall_score >= 0.60:
        level = "MEDIUM"
        level_emoji = "🟡"
    elif overall_score >= 0.30:
        level = "LOW"
        level_emoji = "🔴"
    else:
        level = "UNCERTAIN"
        level_emoji = "⚪"
    
    # 风险等级
    high_risk_kw = ["恶性", "癌", "肿瘤", "急性", "重症", "危重"]
    has_high_risk = any(kw in diagnosis for kw in high_risk_kw)
    if has_high_risk and overall_score < 0.6:
        risk_level = "🔴 CRITICAL"
    elif has_high_risk:
        risk_level = "🟠 HIGH"
    elif overall_score < 0.5:
        risk_level = "🟡 MEDIUM"
    else:
        risk_level = "🟢 LOW"
    
    # 生成报告
    report = "# 📊 置信度评估报告\n\n"
    report += "---\n\n"
    report += f"## 总体评估\n\n"
    report += f"**诊断**: {diagnosis}\n\n"
    report += f"**置信度**: {level_emoji} **{level}** ({overall_score*100:.1f}%)\n\n"
    report += f"**风险等级**: {risk_level}\n\n"
    
    report += "## 📈 各维度得分\n\n"
    report += f"| 维度 | 得分 | 说明 |\n"
    report += f"|------|------|------|\n"
    report += f"| 证据充分度 | {evidence_score*100:.0f}% | 支持诊断的证据质量 |\n"
    report += f"| 一致性 | {consistency_score*100:.0f}% | 症状与诊断的匹配度 |\n"
    report += f"| 完整性 | {completeness_score*100:.0f}% | 信息的完整程度 |\n"
    report += f"| 确定性 | {certainty_score*100:.0f}% | 诊断的明确程度 |\n\n"
    
    report += "## 💡 改进建议\n\n"
    if evidence_score < 0.5:
        report += "- 建议补充更多诊断依据\n"
    if completeness_score < 0.5:
        report += "- 建议完善病史和检查资料\n"
    if level in ["LOW", "UNCERTAIN"]:
        report += "- 建议进一步检查以明确诊断\n"
        report += "- 必要时请专科会诊\n"
    if level == "HIGH":
        report += "- 诊断依据充分，可按诊断进行治疗\n"
    
    report += "\n## ⚠️ 警告\n\n"
    if risk_level.startswith("🔴"):
        report += "> ⚠️ **危急情况**：诊断不确定但可能为严重疾病，请立即处理\n\n"
    report += "> 本评估由AI生成，最终诊断请以临床医生判断为准。\n"
    
    return report
