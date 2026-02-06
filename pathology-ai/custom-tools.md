# 🔧 自定义工具说明

本文档详细介绍病理学AI助手中新增的自定义MCP工具。

## 工具列表（共15个）

### 医疗诊断工具

| 工具名称 | 功能简述 |
|----------|----------|
| chain_of_diagnosis | 5步结构化诊断推理（CoD） |
| evaluate_diagnosis_confidence | 置信度与风险评估 |
| search_pathology_images | 搜索本地病理图片 |
| generate_medical_guide | 生成就医指南 |

### 诊断模拟游戏

| 工具名称 | 功能简述 |
|----------|----------|
| start_diagnosis_game | 启动诊断模拟游戏 |
| diagnosis_action | 执行诊断游戏动作（问诊/体检/检查/诊断） |

### 医学可视化工具

| 工具名称 | 功能简述 |
|----------|----------|
| generate_knowledge_graph | 生成医学知识图谱（Mermaid） |
| generate_diagnosis_flow | 生成诊断流程图 |
| generate_medical_chart | 生成统计图表（柱状图/折线图/饼图） |
| generate_radar_chart | 生成雷达图（多维度健康指标对比） |
| generate_timeline | 生成时间线图（疾病发展/治疗计划） |
| generate_gantt_chart | 生成甘特图（治疗疗程安排） |
| generate_quadrant_chart | 生成象限图（风险评估/优先级分析） |
| generate_state_diagram | 生成状态转换图（疾病状态变化） |
| generate_sankey_diagram | 生成桑基图（流量和转换关系） |

---

## 1. chain_of_diagnosis

### 功能
实现 Chain-of-Diagnosis (CoD) 诊断推理链，将复杂的诊断过程分解为5个结构化步骤。

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symptoms | str | 是 | 患者症状描述 |
| medical_history | str | 否 | 既往病史 |
| lab_results | str | 否 | 实验室检查结果 |
| imaging_findings | str | 否 | 影像学发现 |

### 输出格式

```markdown
## 🔬 Chain-of-Diagnosis 诊断推理

### Step 1: 症状分析
- 主要症状识别
- 症状特征分析

### Step 2: 病史关联
- 相关病史
- 风险因素

### Step 3: 鉴别诊断
- 可能诊断列表
- 排除诊断

### Step 4: 检查建议
- 推荐检查项目
- 优先级排序

### Step 5: 初步结论
- 最可能诊断
- 置信度评估
```

### 示例调用

```python
result = chain_of_diagnosis(
    symptoms="持续发热2周，体重下降，淋巴结肿大",
    medical_history="无特殊病史",
    lab_results="白细胞减少"
)
```

---

## 2. evaluate_diagnosis_confidence

### 功能
评估医疗诊断或回答的置信度，包括证据充分度、一致性、完整性等维度。

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| diagnosis | str | 是 | 诊断结果 |
| symptoms | str | 否 | 症状列表，用逗号分隔 |
| evidence | str | 否 | 支持证据，用逗号分隔 |
| lab_results | str | 否 | 实验室结果 |

### 输出格式

```markdown
## 📊 置信度评估报告

### 总体置信度: HIGH/MEDIUM/LOW/UNCERTAIN

### 评估维度
| 维度 | 得分 | 说明 |
|------|------|------|
| 证据充分度 | 85% | ... |
| 一致性 | 90% | ... |
| 完整性 | 80% | ... |
| 确定性 | 75% | ... |

### 风险等级: LOW/MEDIUM/HIGH/CRITICAL

### 建议
- ...
```

### 置信度级别

| 级别 | 分数范围 | 说明 |
|------|----------|------|
| HIGH | ≥80% | 证据充分，可信度高 |
| MEDIUM | 60-79% | 有一定依据，需进一步确认 |
| LOW | 40-59% | 证据不足，建议谨慎 |
| UNCERTAIN | <40% | 高度不确定，强烈建议就医 |

---

## 3. start_diagnosis_game

### 功能
启动交互式诊断模拟游戏，用户扮演医生进行问诊练习。

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| difficulty | int | 否 | 难度等级 (1=初级, 2=中级, 3=高级) |
| case_type | str | 否 | 病例类型 (hiv_basic, hiv_opportunistic, random) |

### 输出格式

```markdown
## 🏥 诊断模拟器 - 病例开始

### 👤 患者信息
**男性，32岁，程序员**

### 💬 主诉
> "医生，我最近一个月反复发热..."

### 📋 当前阶段：问诊 (第1步/共4步)

**请选择您要询问的内容：**

[btn:询问发热详情] [btn:询问其他症状] [btn:询问既往病史]
[btn:询问接触史] [btn:询问用药情况] [btn:进入体格检查]
```

### 游戏流程

```
问诊 → 体格检查 → 辅助检查 → 给出诊断
```

---

## 4. diagnosis_action

### 功能
在诊断模拟游戏中执行具体动作。

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| case_id | str | 是 | 病例ID |
| action_type | str | 是 | 动作类型 (ask/exam/test/diagnose) |
| action_detail | str | 是 | 具体动作内容 |

### 动作类型

| 类型 | 说明 | 示例 |
|------|------|------|
| ask | 问诊 | 询问发热情况 |
| exam | 体格检查 | 检查淋巴结 |
| test | 辅助检查 | HIV抗体初筛 |
| diagnose | 给出诊断 | 给出诊断结论 |

---

## 5. search_pathology_images

### 功能
搜索本地病理图片服务器中的图片。

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| keyword | str | 是 | 搜索关键词 |
| count | int | 否 | 返回数量（默认6，最大9） |

### 支持的关键词类别

- HIV/AIDS/免疫 - 免疫病理学图片
- 感染 - 感染性疾病图片
- 心血管 - 心血管病理图片
- 肺/呼吸 - 肺部病理图片
- 肿瘤/癌 - 肿瘤病理图片
- 神经/脑 - 神经系统病理图片
- 胃肠/消化 - 消化系统病理图片

### 输出格式

```markdown
## 🔍 病理图片搜索结果

找到 5 张相关图片：

| 序号 | 分类 | 文件名 | URL |
|------|------|--------|-----|
| 1 | Immunopathology | hiv_lymph_node.jpg | http://... |
```

---

## 6. generate_medical_guide

### 功能
生成结构化的就医指南，包括科室推荐、检查项目、注意事项等。

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| condition | str | 是 | 病情描述 |
| urgency | str | 否 | 紧急程度 (emergency/urgent/routine)，默认urgent |
| patient_info | str | 否 | 患者关键信息 |

### 输出格式

```markdown
## 🏥 就医指南

### 推荐科室
| 优先级 | 科室 | 说明 |
|--------|------|------|
| 1 | 感染科 | ... |

### 建议检查
| 检查项目 | 目的 | 费用参考 |
|----------|------|----------|
| HIV抗体 | 初筛 | ¥50-100 |

### 就诊流程
[Mermaid流程图]

### 注意事项
- ...
```

---

---

## 7-15. 医学可视化工具

以下工具均输出 **Mermaid 格式**，可在前端直接渲染。

### 7. generate_knowledge_graph
生成医学知识图谱，展示疾病、症状、治疗的关系。

| 参数 | 说明 |
|------|------|
| topic | 主题（如"HIV感染"） |
| nodes | 节点列表，用\|分隔 |
| relations | 关系列表，用\|分隔 |

### 8. generate_diagnosis_flow
生成诊断流程图，展示诊断步骤和决策点。

| 参数 | 说明 |
|------|------|
| disease | 疾病名称 |
| steps | 步骤列表，用\|分隔 |
| decisions | 决策点列表 |

### 9. generate_medical_chart
生成统计图表（柱状图/折线图/饼图）。

| 参数 | 说明 |
|------|------|
| chart_type | 图表类型 (bar/line/pie) |
| title | 标题 |
| data | 数据，格式"标签:值\|标签:值" |

### 10. generate_radar_chart
生成雷达图，用于多维度健康指标对比。

| 参数 | 说明 |
|------|------|
| title | 标题 |
| metrics | 指标列表 |
| values | 数值列表 |

### 11. generate_timeline
生成时间线图，展示疾病发展或治疗计划。

| 参数 | 说明 |
|------|------|
| title | 标题 |
| events | 事件列表，格式"时间:描述\|时间:描述" |

### 12. generate_gantt_chart
生成甘特图，用于治疗疗程安排。

| 参数 | 说明 |
|------|------|
| title | 标题 |
| tasks | 任务列表 |

### 13. generate_quadrant_chart
生成象限图，用于风险评估和优先级分析。

| 参数 | 说明 |
|------|------|
| title | 标题 |
| x_axis | X轴标签 |
| y_axis | Y轴标签 |
| items | 项目列表 |

### 14. generate_state_diagram
生成状态转换图，展示疾病状态变化。

| 参数 | 说明 |
|------|------|
| title | 标题 |
| states | 状态列表 |
| transitions | 转换列表 |

### 15. generate_sankey_diagram
生成桑基图，展示流量和转换关系。

| 参数 | 说明 |
|------|------|
| title | 标题 |
| flows | 流量列表 |

---

## 工具文件位置

所有自定义工具定义在：

```
backend/tool_collection/mcp/local_mcp_service.py
```

使用 FastMCP 框架注册，通过 `@local_mcp_service.tool()` 装饰器定义。
