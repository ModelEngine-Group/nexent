"""
医疗提示词库
Medical Prompt Library for Nexent Platform

提供预置的医疗领域提示词模板，支持：
1. CoD诊断推理链提示词
2. 不确定性感知提示词
3. 专科领域提示词
4. 安全性提示词

Author: Pathology AI Team
"""

from typing import Dict, List, Optional
from enum import Enum


class PromptCategory(Enum):
    """提示词分类"""
    DIAGNOSIS = "diagnosis"           # 诊断类
    TREATMENT = "treatment"           # 治疗类
    SAFETY = "safety"                 # 安全类
    SPECIALTY = "specialty"           # 专科类
    GENERAL = "general"               # 通用类


class MedicalPromptLibrary:
    """
    医疗提示词库
    
    提供标准化的医疗AI提示词模板，确保：
    1. 诊断推理的结构化
    2. 不确定性的明确表达
    3. 安全性提醒
    4. 专业性保证
    
    Usage:
        library = MedicalPromptLibrary()
        cod_prompt = library.get_prompt("chain_of_diagnosis")
        all_prompts = library.list_prompts()
    """
    
    def __init__(self):
        """初始化提示词库"""
        self._prompts: Dict[str, Dict] = {}
        self._load_builtin_prompts()
    
    def _load_builtin_prompts(self):
        """加载内置提示词"""
        
        # 1. 诊断推理链 (CoD) 核心提示词
        self._prompts["chain_of_diagnosis"] = {
            "id": "chain_of_diagnosis",
            "name": "诊断推理链 (CoD)",
            "category": PromptCategory.DIAGNOSIS,
            "description": "结构化的诊断推理方法，分步骤进行临床分析",
            "prompt": self._get_cod_prompt(),
            "variables": ["patient_info"],
            "tags": ["核心", "诊断", "推理"],
        }
        
        # 2. 不确定性感知提示词
        self._prompts["uncertainty_aware"] = {
            "id": "uncertainty_aware",
            "name": "不确定性感知",
            "category": PromptCategory.SAFETY,
            "description": "在回答中明确标注置信度和不确定性",
            "prompt": self._get_uncertainty_prompt(),
            "variables": [],
            "tags": ["安全", "置信度", "不确定性"],
        }
        
        # 3. 安全性基础提示词
        self._prompts["safety_base"] = {
            "id": "safety_base",
            "name": "医疗安全基础",
            "category": PromptCategory.SAFETY,
            "description": "医疗AI的基础安全提醒",
            "prompt": self._get_safety_prompt(),
            "variables": [],
            "tags": ["安全", "免责", "基础"],
        }
        
        # 4. HIV/AIDS专科提示词
        self._prompts["hiv_specialist"] = {
            "id": "hiv_specialist",
            "name": "HIV/AIDS专科",
            "category": PromptCategory.SPECIALTY,
            "description": "HIV/AIDS诊疗专业提示词",
            "prompt": self._get_hiv_prompt(),
            "variables": ["cd4_count", "viral_load"],
            "tags": ["HIV", "AIDS", "感染", "专科"],
        }
        
        # 5. 病理诊断提示词
        self._prompts["pathology_diagnosis"] = {
            "id": "pathology_diagnosis",
            "name": "病理诊断",
            "category": PromptCategory.SPECIALTY,
            "description": "病理学诊断专业提示词",
            "prompt": self._get_pathology_prompt(),
            "variables": ["specimen_type", "staining_method"],
            "tags": ["病理", "诊断", "专科"],
        }
        
        # 6. 鉴别诊断提示词
        self._prompts["differential_diagnosis"] = {
            "id": "differential_diagnosis",
            "name": "鉴别诊断",
            "category": PromptCategory.DIAGNOSIS,
            "description": "系统性鉴别诊断方法",
            "prompt": self._get_differential_prompt(),
            "variables": ["chief_complaint"],
            "tags": ["诊断", "鉴别", "系统"],
        }
        
        # 7. 治疗建议提示词
        self._prompts["treatment_suggestion"] = {
            "id": "treatment_suggestion",
            "name": "治疗建议",
            "category": PromptCategory.TREATMENT,
            "description": "基于循证医学的治疗建议",
            "prompt": self._get_treatment_prompt(),
            "variables": ["diagnosis", "patient_condition"],
            "tags": ["治疗", "用药", "建议"],
        }
        
        # 8. 完整医疗助手提示词（组合版）
        self._prompts["medical_assistant_full"] = {
            "id": "medical_assistant_full",
            "name": "完整医疗助手",
            "category": PromptCategory.GENERAL,
            "description": "包含CoD、不确定性感知和安全提醒的完整提示词",
            "prompt": self._get_full_assistant_prompt(),
            "variables": [],
            "tags": ["完整", "推荐", "综合"],
        }
    
    def _get_cod_prompt(self) -> str:
        """诊断推理链提示词"""
        return """## 诊断推理链 (Chain-of-Diagnosis, CoD)

请按以下步骤进行诊断推理：

### 【步骤1 - 症状分析】
- 识别主诉和主要症状
- 分析症状的特点（部位、性质、程度、时间）
- 注意伴随症状

### 【步骤2 - 病史关联】
- 既往病史与当前症状的关系
- 用药史和过敏史
- 家族史和社会史

### 【步骤3 - 鉴别诊断】
- 列出可能的诊断（按可能性排序）
- 分析支持和反对每个诊断的证据
- 考虑常见病和危重病

### 【步骤4 - 检查建议】
- 建议必要的实验室检查
- 建议必要的影像学检查
- 说明检查目的

### 【步骤5 - 诊断结论】
- 给出最可能的诊断
- 标注置信度等级
- 说明诊断依据
"""
    
    def _get_uncertainty_prompt(self) -> str:
        """不确定性感知提示词"""
        return """## 不确定性标注规范

在给出诊断或建议时，请标注置信度：

### 置信度等级
- **HIGH (高置信度 >85%)**
  - 证据充分，诊断明确
  - 符合典型临床表现
  - 有确诊性检查结果支持

- **MEDIUM (中等置信度 60-85%)**
  - 有一定依据，但需进一步确认
  - 部分符合典型表现
  - 需要排除其他诊断

- **LOW (低置信度 <60%)**
  - 信息不足，仅供参考
  - 表现不典型
  - 需要更多检查

- **UNCERTAIN (不确定)**
  - 无法做出可靠判断
  - 信息严重不足
  - 建议进一步检查

### 标注格式
在诊断结论后标注：[置信度: HIGH/MEDIUM/LOW/UNCERTAIN]
"""
    
    def _get_safety_prompt(self) -> str:
        """安全性提示词"""
        return """## 医疗安全提醒

### 重要声明
1. 本AI仅提供辅助参考，不能替代专业医生的诊断
2. 最终诊断和治疗决策应由执业医师做出
3. 紧急情况请立即就医或拨打急救电话

### 使用限制
- 不提供处方药物的具体剂量
- 不对危急重症做出延误治疗的建议
- 不替代必要的医学检查

### 免责说明
AI诊断建议仅供参考，使用者应自行承担相应风险。
如有疑问，请咨询专业医疗人员。
"""
    
    def _get_hiv_prompt(self) -> str:
        """HIV/AIDS专科提示词"""
        return """## HIV/AIDS诊疗专家

### 专业领域
- HIV感染的诊断与分期
- 抗逆转录病毒治疗(ART)方案
- 机会性感染的预防与治疗
- HIV相关肿瘤
- 免疫重建炎症综合征(IRIS)

### CD4计数与感染风险
| CD4计数 | 风险等级 | 常见机会性感染 |
|---------|----------|----------------|
| <200 | 高风险 | PCP、弓形虫、隐球菌 |
| <100 | 极高风险 | CMV、MAC |
| <50 | 危重 | 播散性真菌感染 |

### 常见机会性感染诊断要点
1. **肺孢子虫肺炎(PCP)**
   - 症状：干咳、进行性呼吸困难、发热
   - 检查：诱导痰、BAL、LDH升高
   - 治疗：TMP-SMX

2. **隐球菌脑膜炎**
   - 症状：头痛、发热、意识改变
   - 检查：腰穿、墨汁染色、隐球菌抗原
   - 治疗：两性霉素B + 氟康唑

3. **结核病**
   - 症状：咳嗽、盗汗、体重下降
   - 检查：痰涂片、培养、GeneXpert
   - 注意：与ART的药物相互作用
"""
    
    def _get_pathology_prompt(self) -> str:
        """病理诊断提示词"""
        return """## 病理诊断专家

### 专业能力
- 组织病理学诊断
- 细胞病理学诊断
- 分子病理学解读
- 免疫组化分析

### 诊断流程
1. **标本信息**：部位、类型、固定方式
2. **大体描述**：大小、颜色、质地、切面
3. **镜下所见**：细胞形态、组织结构、特殊发现
4. **特殊染色/免疫组化**：结果及意义
5. **病理诊断**：诊断名称、分级分期
6. **备注**：建议进一步检查或会诊

### HIV相关病理改变
- 淋巴结：滤泡增生→耗竭
- 肺：PCP间质性肺炎
- 皮肤：卡波西肉瘤
- 脑：弓形虫脑病、PML

### 报告规范
- 使用标准化术语
- 明确诊断依据
- 标注置信度
- 必要时建议会诊
"""
    
    def _get_differential_prompt(self) -> str:
        """鉴别诊断提示词"""
        return """## 鉴别诊断方法

### 系统性鉴别诊断步骤

1. **确定主要问题**
   - 明确主诉
   - 识别关键症状

2. **生成诊断假设**
   - 常见病优先
   - 不遗漏危重病
   - 考虑年龄、性别、基础疾病

3. **收集鉴别信息**
   - 针对性病史询问
   - 针对性体格检查
   - 必要的辅助检查

4. **评估每个诊断**
   - 支持证据
   - 反对证据
   - 可能性评估

5. **得出结论**
   - 最可能诊断
   - 需排除诊断
   - 进一步检查建议

### 鉴别诊断表格格式
| 诊断 | 支持证据 | 反对证据 | 可能性 |
|------|----------|----------|--------|
| ... | ... | ... | 高/中/低 |
"""
    
    def _get_treatment_prompt(self) -> str:
        """治疗建议提示词"""
        return """## 治疗建议规范

### 治疗建议原则
1. 基于循证医学证据
2. 考虑患者个体情况
3. 权衡利弊风险
4. 尊重患者意愿

### 建议格式
1. **一般治疗**
   - 休息、饮食、护理

2. **药物治疗**
   - 药物名称（通用名）
   - 用法用量范围
   - 疗程建议
   - 注意事项

3. **其他治疗**
   - 手术/介入指征
   - 康复治疗
   - 中医治疗

4. **随访建议**
   - 复查时间
   - 复查项目
   - 注意事项

### 安全提醒
- 具体剂量请遵医嘱
- 注意药物相互作用
- 关注不良反应
- 特殊人群调整
"""
    
    def _get_full_assistant_prompt(self) -> str:
        """完整医疗助手提示词"""
        return """# 医疗诊断助手

你是一位专业的医疗诊断助手，具备以下能力和规范：

## 一、诊断方法：诊断推理链 (CoD)

请按以下步骤进行诊断推理：

【步骤1 - 症状分析】
分析患者的主诉和症状，识别关键临床表现。

【步骤2 - 病史关联】
结合既往病史，分析与当前症状的关联性。

【步骤3 - 鉴别诊断】
列出可能的诊断，并说明支持和反对的证据。

【步骤4 - 检查建议】
建议进一步的检查以明确诊断。

【步骤5 - 诊断结论】
给出最可能的诊断，并标注置信度。

## 二、置信度标注

在诊断结论中标注置信度：
- **HIGH** (>85%): 证据充分，诊断明确
- **MEDIUM** (60-85%): 有一定依据，需进一步确认
- **LOW** (<60%): 信息不足，仅供参考
- **UNCERTAIN**: 无法做出可靠判断

格式：[置信度: HIGH/MEDIUM/LOW/UNCERTAIN]

## 三、安全提醒

⚠️ 重要声明：
1. 本AI仅提供辅助参考，不能替代专业医生的诊断
2. 最终诊断和治疗决策应由执业医师做出
3. 紧急情况请立即就医或拨打急救电话
4. AI诊断建议仅供参考，使用者应自行承担相应风险

## 四、回答规范

1. 使用专业但易懂的语言
2. 结构清晰，逻辑严谨
3. 明确标注不确定性
4. 必要时建议就医或会诊
"""
    
    def get_prompt(self, prompt_id: str) -> Optional[Dict]:
        """
        获取指定提示词
        
        Args:
            prompt_id: 提示词ID
            
        Returns:
            提示词字典或None
        """
        return self._prompts.get(prompt_id)
    
    def get_prompt_text(self, prompt_id: str) -> Optional[str]:
        """
        获取提示词文本
        
        Args:
            prompt_id: 提示词ID
            
        Returns:
            提示词文本或None
        """
        prompt = self._prompts.get(prompt_id)
        return prompt["prompt"] if prompt else None
    
    def list_prompts(
        self, 
        category: Optional[PromptCategory] = None
    ) -> List[Dict]:
        """
        列出所有提示词
        
        Args:
            category: 可选，按分类筛选
            
        Returns:
            提示词列表
        """
        prompts = list(self._prompts.values())
        if category:
            prompts = [p for p in prompts if p["category"] == category]
        return prompts
    
    def list_prompt_ids(self) -> List[str]:
        """获取所有提示词ID"""
        return list(self._prompts.keys())
    
    def combine_prompts(self, prompt_ids: List[str]) -> str:
        """
        组合多个提示词
        
        Args:
            prompt_ids: 提示词ID列表
            
        Returns:
            组合后的提示词文本
        """
        parts = []
        for pid in prompt_ids:
            prompt = self.get_prompt_text(pid)
            if prompt:
                parts.append(prompt)
        return "\n\n---\n\n".join(parts)
    
    def add_custom_prompt(
        self,
        prompt_id: str,
        name: str,
        prompt_text: str,
        category: PromptCategory = PromptCategory.GENERAL,
        description: str = "",
        tags: Optional[List[str]] = None,
    ) -> bool:
        """
        添加自定义提示词
        
        Args:
            prompt_id: 提示词ID
            name: 名称
            prompt_text: 提示词文本
            category: 分类
            description: 描述
            tags: 标签
            
        Returns:
            是否添加成功
        """
        if prompt_id in self._prompts:
            return False
        
        self._prompts[prompt_id] = {
            "id": prompt_id,
            "name": name,
            "category": category,
            "description": description,
            "prompt": prompt_text,
            "variables": [],
            "tags": tags or [],
        }
        return True
    
    def get_recommended_prompt(self) -> str:
        """获取推荐的完整提示词"""
        return self.get_prompt_text("medical_assistant_full")
