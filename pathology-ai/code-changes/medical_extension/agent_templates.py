"""
医疗智能体模板系统
Medical Agent Templates for Nexent Platform

提供预置的医疗领域智能体模板，支持一键创建专业医疗智能体。

Templates:
- 病理诊断助手
- 影像分析助手
- 临床决策支持
- 药物咨询助手

Author: Pathology AI Team
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
import json


class MedicalDomain(Enum):
    """医疗领域分类"""
    PATHOLOGY = "pathology"           # 病理学
    RADIOLOGY = "radiology"           # 放射学/影像
    CLINICAL = "clinical"             # 临床医学
    PHARMACY = "pharmacy"             # 药学
    LABORATORY = "laboratory"         # 检验医学
    GENERAL = "general"               # 通用医学


@dataclass
class AgentTemplate:
    """智能体模板"""
    template_id: str                  # 模板ID
    name: str                         # 模板名称
    description: str                  # 描述
    domain: MedicalDomain             # 医疗领域
    system_prompt: str                # 系统提示词
    suggested_tools: List[str]        # 建议的MCP工具
    knowledge_bases: List[str]        # 建议的知识库
    model_requirements: Dict[str, Any] = field(default_factory=dict)  # 模型要求
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "domain": self.domain.value,
            "system_prompt": self.system_prompt,
            "suggested_tools": self.suggested_tools,
            "knowledge_bases": self.knowledge_bases,
            "model_requirements": self.model_requirements,
            "metadata": self.metadata,
        }
    
    def to_json(self) -> str:
        """转换为JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class MedicalAgentTemplates:
    """
    医疗智能体模板管理器
    
    提供预置的医疗领域智能体模板，支持：
    1. 获取模板列表
    2. 按领域筛选
    3. 创建自定义模板
    4. 导出/导入模板
    
    Usage:
        templates = MedicalAgentTemplates()
        pathology_template = templates.get_template("pathology_diagnosis")
        all_templates = templates.list_templates()
    """
    
    def __init__(self):
        """初始化模板管理器"""
        self._templates: Dict[str, AgentTemplate] = {}
        self._load_builtin_templates()
    
    def _load_builtin_templates(self):
        """加载内置模板"""
        
        # 1. 病理诊断助手模板
        self._templates["pathology_diagnosis"] = AgentTemplate(
            template_id="pathology_diagnosis",
            name="病理诊断助手",
            description="专业的病理学诊断辅助智能体，支持组织病理分析、细胞学诊断和分子病理解读",
            domain=MedicalDomain.PATHOLOGY,
            system_prompt=self._get_pathology_prompt(),
            suggested_tools=[
                "pathology_diagnosis_assistant",
                "pathology_image_analyzer",
                "differential_diagnosis_generator",
                "knowledge_graph_query",
            ],
            knowledge_bases=["病理学知识库", "肿瘤病理数据库"],
            model_requirements={
                "min_context_length": 4096,
                "recommended_models": ["glm-4.5", "gpt-4o", "claude-4-sonnet"],
                "supports_vision": True,
            },
            metadata={
                "version": "1.0.0",
                "author": "Pathology AI Team",
                "tags": ["病理", "诊断", "HIV/AIDS", "肿瘤"],
            }
        )
        
        # 2. 影像分析助手模板
        self._templates["radiology_assistant"] = AgentTemplate(
            template_id="radiology_assistant",
            name="医学影像分析助手",
            description="专业的医学影像分析智能体，支持X光、CT、MRI等影像的智能解读",
            domain=MedicalDomain.RADIOLOGY,
            system_prompt=self._get_radiology_prompt(),
            suggested_tools=[
                "pathology_image_analyzer",
                "differential_diagnosis_generator",
            ],
            knowledge_bases=["影像学知识库"],
            model_requirements={
                "min_context_length": 4096,
                "recommended_models": ["gpt-4o", "gemini-3-pro"],
                "supports_vision": True,  # 必须支持视觉
            },
            metadata={
                "version": "1.0.0",
                "tags": ["影像", "CT", "MRI", "X光"],
            }
        )
        
        # 3. 临床决策支持模板
        self._templates["clinical_decision"] = AgentTemplate(
            template_id="clinical_decision",
            name="临床决策支持助手",
            description="临床决策支持智能体，提供诊断建议、治疗方案和用药指导",
            domain=MedicalDomain.CLINICAL,
            system_prompt=self._get_clinical_prompt(),
            suggested_tools=[
                "pathology_diagnosis_assistant",
                "differential_diagnosis_generator",
                "knowledge_graph_query",
            ],
            knowledge_bases=["临床指南库", "药物数据库"],
            model_requirements={
                "min_context_length": 8192,
                "recommended_models": ["glm-4.5", "gpt-4o", "claude-4-opus"],
            },
            metadata={
                "version": "1.0.0",
                "tags": ["临床", "决策", "治疗", "用药"],
            }
        )
        
        # 4. HIV/AIDS专科助手模板
        self._templates["hiv_specialist"] = AgentTemplate(
            template_id="hiv_specialist",
            name="HIV/AIDS专科助手",
            description="HIV/AIDS专科诊疗智能体，专注于HIV感染的诊断、治疗和机会性感染管理",
            domain=MedicalDomain.CLINICAL,
            system_prompt=self._get_hiv_specialist_prompt(),
            suggested_tools=[
                "pathology_diagnosis_assistant",
                "differential_diagnosis_generator",
                "knowledge_graph_query",
            ],
            knowledge_bases=["HIV/AIDS知识库", "机会性感染数据库"],
            model_requirements={
                "min_context_length": 4096,
                "recommended_models": ["glm-4.5", "gpt-4o"],
            },
            metadata={
                "version": "1.0.0",
                "tags": ["HIV", "AIDS", "感染", "免疫"],
            }
        )
    
    def _get_pathology_prompt(self) -> str:
        """获取病理诊断助手提示词"""
        return """你是一位专业的病理学诊断助手，具备以下能力：

## 专业背景
- 精通组织病理学、细胞病理学和分子病理学
- 熟悉WHO肿瘤分类标准
- 了解HIV/AIDS相关病理改变

## 诊断方法
请使用诊断推理链(Chain-of-Diagnosis, CoD)方法：

【步骤1 - 症状分析】分析临床表现和病理所见
【步骤2 - 病史关联】结合既往病史进行分析
【步骤3 - 鉴别诊断】列出可能的病理诊断
【步骤4 - 检查建议】建议进一步的病理检查
【步骤5 - 诊断结论】给出最终诊断和置信度

## 置信度标注
- HIGH (>85%): 诊断依据充分
- MEDIUM (60-85%): 需要进一步确认
- LOW (<60%): 信息不足，仅供参考

## 重要提醒
- 病理诊断需结合临床信息综合判断
- AI诊断仅供参考，最终诊断以病理医师报告为准
- 遇到疑难病例建议多学科会诊(MDT)
"""
    
    def _get_radiology_prompt(self) -> str:
        """获取影像分析助手提示词"""
        return """你是一位专业的医学影像分析助手，具备以下能力：

## 专业背景
- 精通X光、CT、MRI、超声等影像解读
- 熟悉各系统疾病的影像学表现
- 了解影像学检查的适应症和禁忌症

## 分析方法
1. 系统性观察：按解剖结构逐一分析
2. 病变描述：位置、大小、形态、密度/信号、边界、强化特点
3. 鉴别诊断：列出可能的诊断及依据
4. 建议：进一步检查或临床处理建议

## 报告格式
【影像所见】客观描述影像表现
【诊断意见】给出诊断及置信度
【建议】进一步检查或随访建议

## 重要提醒
- 影像诊断需结合临床信息
- AI分析仅供参考，最终诊断以影像科医师报告为准
"""
    
    def _get_clinical_prompt(self) -> str:
        """获取临床决策支持提示词"""
        return """你是一位临床决策支持助手，为医生提供诊疗建议。

## 专业能力
- 疾病诊断与鉴别诊断
- 治疗方案制定
- 用药指导与药物相互作用
- 临床指南解读

## 决策支持流程
1. 病史采集：了解主诉、现病史、既往史
2. 体格检查：分析体征
3. 辅助检查：解读检验和影像结果
4. 诊断分析：使用CoD方法进行诊断推理
5. 治疗建议：基于循证医学提供方案

## 置信度评估
- HIGH: 诊断明确，治疗方案标准化
- MEDIUM: 诊断基本明确，方案需个体化
- LOW: 诊断不确定，建议进一步检查

## 重要提醒
- 所有建议仅供临床参考
- 最终决策由主治医师做出
- 注意患者个体差异和禁忌症
"""
    
    def _get_hiv_specialist_prompt(self) -> str:
        """获取HIV/AIDS专科助手提示词"""
        return """你是一位HIV/AIDS专科诊疗助手，专注于HIV感染的全程管理。

## 专业领域
- HIV感染的诊断与分期
- 抗逆转录病毒治疗(ART)
- 机会性感染的预防与治疗
- HIV相关肿瘤
- 免疫重建炎症综合征(IRIS)

## 诊断推理(CoD)
【步骤1】分析症状和体征
【步骤2】评估免疫状态(CD4计数、病毒载量)
【步骤3】鉴别诊断(机会性感染vs其他)
【步骤4】建议检查(病原学、影像学)
【步骤5】诊断结论与置信度

## CD4计数与机会性感染风险
- CD4 < 200: PCP、弓形虫、隐球菌高风险
- CD4 < 100: CMV、MAC高风险
- CD4 < 50: 播散性真菌感染高风险

## 常见机会性感染
- 肺孢子虫肺炎(PCP): 干咳、呼吸困难、发热
- 隐球菌脑膜炎: 头痛、发热、意识改变
- 结核病: 咳嗽、盗汗、体重下降
- CMV视网膜炎: 视力下降、飞蚊症

## 重要提醒
- HIV诊疗需要专科医师指导
- 注意药物相互作用
- 关注患者心理健康
- AI建议仅供参考
"""
    
    def get_template(self, template_id: str) -> Optional[AgentTemplate]:
        """
        获取指定模板
        
        Args:
            template_id: 模板ID
            
        Returns:
            AgentTemplate or None
        """
        return self._templates.get(template_id)
    
    def list_templates(
        self, 
        domain: Optional[MedicalDomain] = None
    ) -> List[AgentTemplate]:
        """
        列出所有模板
        
        Args:
            domain: 可选，按领域筛选
            
        Returns:
            模板列表
        """
        templates = list(self._templates.values())
        if domain:
            templates = [t for t in templates if t.domain == domain]
        return templates
    
    def list_template_ids(self) -> List[str]:
        """获取所有模板ID"""
        return list(self._templates.keys())
    
    def add_template(self, template: AgentTemplate) -> bool:
        """
        添加自定义模板
        
        Args:
            template: 模板对象
            
        Returns:
            是否添加成功
        """
        if template.template_id in self._templates:
            return False
        self._templates[template.template_id] = template
        return True
    
    def remove_template(self, template_id: str) -> bool:
        """
        移除模板
        
        Args:
            template_id: 模板ID
            
        Returns:
            是否移除成功
        """
        if template_id in self._templates:
            del self._templates[template_id]
            return True
        return False
    
    def export_templates(self, filepath: str) -> bool:
        """
        导出模板到文件
        
        Args:
            filepath: 文件路径
            
        Returns:
            是否导出成功
        """
        try:
            data = {
                "version": "1.0.0",
                "templates": [t.to_dict() for t in self._templates.values()]
            }
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False
    
    def import_templates(self, filepath: str) -> int:
        """
        从文件导入模板
        
        Args:
            filepath: 文件路径
            
        Returns:
            导入的模板数量
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            count = 0
            for t_data in data.get("templates", []):
                template = AgentTemplate(
                    template_id=t_data["template_id"],
                    name=t_data["name"],
                    description=t_data["description"],
                    domain=MedicalDomain(t_data["domain"]),
                    system_prompt=t_data["system_prompt"],
                    suggested_tools=t_data["suggested_tools"],
                    knowledge_bases=t_data["knowledge_bases"],
                    model_requirements=t_data.get("model_requirements", {}),
                    metadata=t_data.get("metadata", {}),
                )
                if self.add_template(template):
                    count += 1
            return count
        except Exception:
            return 0
    
    def get_template_summary(self) -> str:
        """获取模板摘要"""
        lines = ["=" * 50, "医疗智能体模板库", "=" * 50, ""]
        
        for domain in MedicalDomain:
            templates = self.list_templates(domain)
            if templates:
                lines.append(f"【{domain.value.upper()}】")
                for t in templates:
                    lines.append(f"  - {t.name} ({t.template_id})")
                    lines.append(f"    {t.description[:50]}...")
                lines.append("")
        
        lines.append(f"共 {len(self._templates)} 个模板")
        return "\n".join(lines)
