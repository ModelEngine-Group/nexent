"""
Chain-of-Diagnosis (CoD) 诊断推理链框架
Medical Diagnosis Reasoning Chain Framework

创新点：
1. 结构化诊断推理流程
2. 多步骤逻辑推导
3. 置信度量化评估
4. 可解释性诊断输出

Author: Pathology AI Team
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
import json
import re


class ConfidenceLevel(Enum):
    """置信度等级"""
    HIGH = "HIGH"        # >85% 高置信度
    MEDIUM = "MEDIUM"    # 60-85% 中等置信度
    LOW = "LOW"          # <60% 低置信度
    UNCERTAIN = "UNCERTAIN"  # 不确定


@dataclass
class DiagnosisStep:
    """诊断推理步骤"""
    step_name: str           # 步骤名称
    content: str             # 步骤内容
    evidence: List[str] = field(default_factory=list)  # 支持证据
    confidence: float = 0.0  # 步骤置信度


@dataclass
class DiagnosisResult:
    """诊断结果"""
    primary_diagnosis: str                    # 主要诊断
    differential_diagnoses: List[str]         # 鉴别诊断列表
    confidence_level: ConfidenceLevel         # 置信度等级
    confidence_score: float                   # 置信度分数 (0-1)
    reasoning_chain: List[DiagnosisStep]      # 推理链
    recommendations: List[str]                # 建议
    warnings: List[str] = field(default_factory=list)  # 警告信息
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "primary_diagnosis": self.primary_diagnosis,
            "differential_diagnoses": self.differential_diagnoses,
            "confidence_level": self.confidence_level.value,
            "confidence_score": self.confidence_score,
            "reasoning_chain": [
                {
                    "step": s.step_name,
                    "content": s.content,
                    "evidence": s.evidence,
                    "confidence": s.confidence
                } for s in self.reasoning_chain
            ],
            "recommendations": self.recommendations,
            "warnings": self.warnings,
            "metadata": self.metadata
        }
    
    def to_formatted_string(self) -> str:
        """生成格式化的诊断报告"""
        lines = []
        lines.append("=" * 50)
        lines.append("【诊断推理报告】")
        lines.append("=" * 50)
        
        # 推理链
        lines.append("\n📋 诊断推理链:")
        for i, step in enumerate(self.reasoning_chain, 1):
            lines.append(f"\n[步骤{i}] {step.step_name}")
            lines.append(f"  {step.content}")
            if step.evidence:
                lines.append(f"  证据: {', '.join(step.evidence)}")
        
        # 诊断结论
        lines.append(f"\n🎯 主要诊断: {self.primary_diagnosis}")
        
        if self.differential_diagnoses:
            lines.append(f"\n🔍 鉴别诊断:")
            for dd in self.differential_diagnoses:
                lines.append(f"  - {dd}")
        
        # 置信度
        confidence_emoji = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴", "UNCERTAIN": "⚪"}
        lines.append(f"\n📊 置信度: {confidence_emoji.get(self.confidence_level.value, '⚪')} "
                    f"{self.confidence_level.value} ({self.confidence_score*100:.1f}%)")
        
        # 建议
        if self.recommendations:
            lines.append(f"\n💡 建议:")
            for rec in self.recommendations:
                lines.append(f"  • {rec}")
        
        # 警告
        if self.warnings:
            lines.append(f"\n⚠️ 注意:")
            for warn in self.warnings:
                lines.append(f"  • {warn}")
        
        lines.append("\n" + "=" * 50)
        return "\n".join(lines)


class ChainOfDiagnosis:
    """
    诊断推理链 (Chain-of-Diagnosis) 框架
    
    核心创新：
    1. 症状分析 → 2. 病史关联 → 3. 鉴别诊断 → 4. 检查建议 → 5. 诊断结论
    
    Usage:
        cod = ChainOfDiagnosis()
        result = cod.analyze(symptoms, lab_results, history)
        print(result.to_formatted_string())
    """
    
    # CoD 推理步骤定义
    COD_STEPS = [
        "症状分析",      # Step 1: 分析主诉和症状
        "病史关联",      # Step 2: 关联既往病史
        "鉴别诊断",      # Step 3: 列出可能的诊断
        "检查建议",      # Step 4: 建议进一步检查
        "诊断结论",      # Step 5: 给出最终诊断
    ]
    
    # 置信度阈值
    CONFIDENCE_THRESHOLDS = {
        "high": 0.85,
        "medium": 0.60,
    }
    
    def __init__(self, knowledge_base: Optional[Dict] = None):
        """
        初始化诊断推理链
        
        Args:
            knowledge_base: 可选的知识库字典
        """
        self.knowledge_base = knowledge_base or {}
        self._load_default_knowledge()
    
    def _load_default_knowledge(self):
        """加载默认医学知识库"""
        # HIV/AIDS 相关知识
        self.knowledge_base.update({
            "hiv_opportunistic_infections": [
                "肺孢子虫肺炎 (PCP)",
                "巨细胞病毒感染 (CMV)",
                "隐球菌脑膜炎",
                "卡波西肉瘤",
                "结核病",
                "弓形虫脑病",
            ],
            "cd4_thresholds": {
                "severe_immunodeficiency": 200,
                "moderate_immunodeficiency": 350,
                "mild_immunodeficiency": 500,
            },
            "pcp_symptoms": ["干咳", "呼吸困难", "发热", "低氧血症"],
            "pcp_treatment": ["复方磺胺甲噁唑 (TMP-SMX)", "喷他脒", "阿托伐醌"],
        })
    
    def analyze(
        self,
        symptoms: str,
        lab_results: Optional[str] = None,
        medical_history: Optional[str] = None,
        imaging_findings: Optional[str] = None,
    ) -> DiagnosisResult:
        """
        执行诊断推理链分析
        
        Args:
            symptoms: 症状描述
            lab_results: 实验室检查结果
            medical_history: 既往病史
            imaging_findings: 影像学发现
            
        Returns:
            DiagnosisResult: 诊断结果对象
        """
        reasoning_chain = []
        evidence_collected = []
        
        # Step 1: 症状分析
        step1 = self._analyze_symptoms(symptoms)
        reasoning_chain.append(step1)
        evidence_collected.extend(step1.evidence)
        
        # Step 2: 病史关联
        step2 = self._correlate_history(medical_history, symptoms)
        reasoning_chain.append(step2)
        evidence_collected.extend(step2.evidence)
        
        # Step 3: 鉴别诊断
        step3 = self._differential_diagnosis(
            symptoms, lab_results, medical_history, imaging_findings
        )
        reasoning_chain.append(step3)
        
        # Step 4: 检查建议
        step4 = self._suggest_examinations(step3.content, lab_results)
        reasoning_chain.append(step4)
        
        # Step 5: 诊断结论
        step5, primary_diagnosis, differentials = self._conclude_diagnosis(
            reasoning_chain, lab_results
        )
        reasoning_chain.append(step5)
        
        # 计算置信度
        confidence_score = self._calculate_confidence(
            reasoning_chain, evidence_collected, lab_results
        )
        confidence_level = self._get_confidence_level(confidence_score)
        
        # 生成建议
        recommendations = self._generate_recommendations(
            primary_diagnosis, confidence_level, lab_results
        )
        
        # 生成警告
        warnings = self._generate_warnings(confidence_level, primary_diagnosis)
        
        return DiagnosisResult(
            primary_diagnosis=primary_diagnosis,
            differential_diagnoses=differentials,
            confidence_level=confidence_level,
            confidence_score=confidence_score,
            reasoning_chain=reasoning_chain,
            recommendations=recommendations,
            warnings=warnings,
            metadata={
                "input_symptoms": symptoms,
                "has_lab_results": lab_results is not None,
                "has_history": medical_history is not None,
            }
        )
    
    def _analyze_symptoms(self, symptoms: str) -> DiagnosisStep:
        """分析症状"""
        evidence = []
        analysis = []
        
        # 检测关键症状
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
                evidence.extend(found)
                analysis.append(f"{system}症状: {', '.join(found)}")
        
        content = "; ".join(analysis) if analysis else "症状信息不足，需要进一步询问"
        
        return DiagnosisStep(
            step_name="症状分析",
            content=content,
            evidence=evidence,
            confidence=0.8 if evidence else 0.3
        )
    
    def _correlate_history(
        self, history: Optional[str], symptoms: str
    ) -> DiagnosisStep:
        """关联病史"""
        evidence = []
        content = ""
        
        if history:
            # 检测HIV/AIDS相关
            if any(kw in history.lower() for kw in ["hiv", "aids", "艾滋", "免疫缺陷"]):
                evidence.append("HIV/AIDS病史")
                content = "患者有HIV/AIDS病史，需考虑机会性感染"
            
            # 检测免疫抑制
            if any(kw in history for kw in ["免疫抑制", "化疗", "器官移植", "激素"]):
                evidence.append("免疫抑制状态")
                content += "；存在免疫抑制因素"
        
        if not content:
            content = "无特殊病史或病史信息不完整"
        
        return DiagnosisStep(
            step_name="病史关联",
            content=content,
            evidence=evidence,
            confidence=0.7 if evidence else 0.4
        )
    
    def _differential_diagnosis(
        self,
        symptoms: str,
        lab_results: Optional[str],
        history: Optional[str],
        imaging: Optional[str],
    ) -> DiagnosisStep:
        """生成鉴别诊断"""
        differentials = []
        evidence = []
        
        # HIV相关机会性感染判断
        is_hiv_related = history and any(
            kw in history.lower() for kw in ["hiv", "aids", "艾滋"]
        )
        
        # 检测CD4计数
        cd4_count = None
        if lab_results:
            cd4_match = re.search(r'cd4[^\d]*(\d+)', lab_results.lower())
            if cd4_match:
                cd4_count = int(cd4_match.group(1))
                evidence.append(f"CD4计数: {cd4_count}")
        
        # 基于症状和病史生成鉴别诊断
        if is_hiv_related:
            if cd4_count and cd4_count < 200:
                # 严重免疫缺陷
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
            # 非HIV患者
            if any(s in symptoms for s in ["咳嗽", "发热"]):
                differentials.append("社区获得性肺炎")
                differentials.append("病毒性上呼吸道感染")
                differentials.append("支气管炎")
        
        content = "鉴别诊断: " + ", ".join(differentials) if differentials else "需要更多信息"
        
        return DiagnosisStep(
            step_name="鉴别诊断",
            content=content,
            evidence=evidence,
            confidence=0.75 if differentials else 0.3
        )
    
    def _suggest_examinations(
        self, differential: str, existing_labs: Optional[str]
    ) -> DiagnosisStep:
        """建议进一步检查"""
        suggestions = []
        
        if "PCP" in differential or "肺孢子虫" in differential:
            suggestions.extend([
                "诱导痰检查（银染色/免疫荧光）",
                "血气分析",
                "乳酸脱氢酶 (LDH)",
                "胸部CT",
                "支气管肺泡灌洗 (BAL)",
            ])
        elif "脑膜炎" in differential:
            suggestions.extend([
                "腰椎穿刺",
                "脑脊液墨汁染色",
                "隐球菌抗原检测",
                "头颅MRI",
            ])
        else:
            suggestions.extend([
                "血常规",
                "C反应蛋白",
                "胸部X线",
            ])
        
        # 排除已有检查
        if existing_labs:
            suggestions = [s for s in suggestions if s.split("(")[0] not in existing_labs]
        
        content = "建议检查: " + ", ".join(suggestions[:5])  # 最多5项
        
        return DiagnosisStep(
            step_name="检查建议",
            content=content,
            evidence=[],
            confidence=0.8
        )
    
    def _conclude_diagnosis(
        self,
        reasoning_chain: List[DiagnosisStep],
        lab_results: Optional[str],
    ) -> tuple:
        """得出诊断结论"""
        # 从鉴别诊断步骤提取
        differential_step = reasoning_chain[2]  # Step 3
        
        # 解析鉴别诊断
        differentials = []
        primary = "诊断待定"
        
        if "高度怀疑" in differential_step.content:
            # 提取高度怀疑的诊断作为主诊断
            match = re.search(r'([^,]+)\s*-\s*高度怀疑', differential_step.content)
            if match:
                primary = match.group(1).strip()
        
        # 提取所有鉴别诊断
        diff_match = re.search(r'鉴别诊断:\s*(.+)', differential_step.content)
        if diff_match:
            diff_list = diff_match.group(1).split(", ")
            differentials = [d.split(" - ")[0].strip() for d in diff_list if d != primary]
        
        content = f"综合分析，最可能的诊断为: {primary}"
        
        step = DiagnosisStep(
            step_name="诊断结论",
            content=content,
            evidence=[s.step_name for s in reasoning_chain if s.confidence > 0.6],
            confidence=0.85 if "高度怀疑" in differential_step.content else 0.5
        )
        
        return step, primary, differentials
    
    def _calculate_confidence(
        self,
        reasoning_chain: List[DiagnosisStep],
        evidence: List[str],
        lab_results: Optional[str],
    ) -> float:
        """计算总体置信度"""
        # 基础置信度：各步骤置信度加权平均
        weights = [0.15, 0.15, 0.25, 0.15, 0.30]  # 诊断结论权重最高
        base_confidence = sum(
            step.confidence * weight 
            for step, weight in zip(reasoning_chain, weights)
        )
        
        # 证据加成
        evidence_bonus = min(len(evidence) * 0.02, 0.1)
        
        # 实验室结果加成
        lab_bonus = 0.05 if lab_results else 0
        
        total = base_confidence + evidence_bonus + lab_bonus
        return min(max(total, 0.0), 1.0)  # 限制在0-1之间
    
    def _get_confidence_level(self, score: float) -> ConfidenceLevel:
        """根据分数获取置信度等级"""
        if score >= self.CONFIDENCE_THRESHOLDS["high"]:
            return ConfidenceLevel.HIGH
        elif score >= self.CONFIDENCE_THRESHOLDS["medium"]:
            return ConfidenceLevel.MEDIUM
        elif score > 0.3:
            return ConfidenceLevel.LOW
        else:
            return ConfidenceLevel.UNCERTAIN
    
    def _generate_recommendations(
        self,
        diagnosis: str,
        confidence: ConfidenceLevel,
        lab_results: Optional[str],
    ) -> List[str]:
        """生成治疗建议"""
        recommendations = []
        
        if "PCP" in diagnosis or "肺孢子虫" in diagnosis:
            recommendations.extend([
                "首选治疗: 复方磺胺甲噁唑 (TMP-SMX)",
                "替代方案: 喷他脒或阿托伐醌",
                "严重病例考虑糖皮质激素辅助治疗",
                "监测血氧饱和度",
            ])
        
        if confidence in [ConfidenceLevel.LOW, ConfidenceLevel.UNCERTAIN]:
            recommendations.append("建议进一步检查以明确诊断")
            recommendations.append("必要时请专科会诊")
        
        if not recommendations:
            recommendations.append("根据具体情况制定治疗方案")
        
        return recommendations
    
    def _generate_warnings(
        self,
        confidence: ConfidenceLevel,
        diagnosis: str,
    ) -> List[str]:
        """生成警告信息"""
        warnings = []
        
        if confidence == ConfidenceLevel.LOW:
            warnings.append("置信度较低，诊断结果仅供参考")
        elif confidence == ConfidenceLevel.UNCERTAIN:
            warnings.append("信息不足，无法做出可靠诊断")
        
        warnings.append("本诊断由AI辅助生成，最终诊断请以临床医生判断为准")
        
        return warnings
    
    def generate_cod_prompt(self) -> str:
        """
        生成CoD提示词模板
        可用于配置LLM的系统提示词
        """
        return """你是一位专业的医学诊断助手，请使用诊断推理链(Chain-of-Diagnosis, CoD)方法进行分析。

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
给出最可能的诊断，并标注置信度：
- HIGH (高置信度 >85%): 证据充分，诊断明确
- MEDIUM (中等置信度 60-85%): 有一定依据，但需进一步确认
- LOW (低置信度 <60%): 信息不足，仅供参考

请始终提醒：AI诊断仅供参考，最终诊断请以临床医生判断为准。
"""
