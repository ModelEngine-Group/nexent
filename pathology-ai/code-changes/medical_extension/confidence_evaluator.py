"""
置信度评估系统
Confidence Evaluation System for Medical AI

提供医疗AI回答的置信度评估功能，支持：
1. 基于证据的置信度计算
2. 不确定性量化
3. 风险等级评估

Author: Pathology AI Team
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from enum import Enum
import re


class RiskLevel(Enum):
    """风险等级"""
    CRITICAL = "critical"    # 危急
    HIGH = "high"            # 高风险
    MEDIUM = "medium"        # 中等风险
    LOW = "low"              # 低风险


@dataclass
class ConfidenceReport:
    """置信度评估报告"""
    overall_score: float           # 总体置信度 (0-1)
    confidence_level: str          # 置信度等级 (HIGH/MEDIUM/LOW)
    evidence_score: float          # 证据充分度
    consistency_score: float       # 一致性得分
    completeness_score: float      # 完整性得分
    risk_level: RiskLevel          # 风险等级
    factors: Dict[str, float]      # 各因素得分
    recommendations: List[str]     # 建议
    warnings: List[str]            # 警告
    
    def to_dict(self) -> Dict:
        return {
            "overall_score": self.overall_score,
            "confidence_level": self.confidence_level,
            "evidence_score": self.evidence_score,
            "consistency_score": self.consistency_score,
            "completeness_score": self.completeness_score,
            "risk_level": self.risk_level.value,
            "factors": self.factors,
            "recommendations": self.recommendations,
            "warnings": self.warnings,
        }


class ConfidenceEvaluator:
    """
    置信度评估器
    
    评估维度：
    1. 证据充分度：支持诊断的证据数量和质量
    2. 一致性：症状、检查结果与诊断的一致性
    3. 完整性：信息的完整程度
    4. 确定性：诊断的确定程度
    
    Usage:
        evaluator = ConfidenceEvaluator()
        report = evaluator.evaluate(
            diagnosis="肺孢子虫肺炎",
            symptoms=["干咳", "呼吸困难", "发热"],
            lab_results={"CD4": 150, "LDH": "升高"},
            evidence=["HIV阳性", "CD4<200"]
        )
        print(f"置信度: {report.confidence_level} ({report.overall_score:.2f})")
    """
    
    # 置信度阈值
    THRESHOLDS = {
        "high": 0.85,
        "medium": 0.60,
        "low": 0.30,
    }
    
    # 关键证据权重
    EVIDENCE_WEIGHTS = {
        "病理确诊": 1.0,
        "实验室确诊": 0.9,
        "影像学典型表现": 0.8,
        "临床症状典型": 0.7,
        "病史支持": 0.6,
        "经验性诊断": 0.4,
    }
    
    # 高风险诊断关键词
    HIGH_RISK_KEYWORDS = [
        "恶性", "癌", "肿瘤", "转移", "急性", "重症",
        "休克", "衰竭", "危重", "紧急",
    ]
    
    def __init__(self):
        """初始化评估器"""
        self._custom_rules = []
    
    def evaluate(
        self,
        diagnosis: str,
        symptoms: Optional[List[str]] = None,
        lab_results: Optional[Dict] = None,
        imaging_findings: Optional[List[str]] = None,
        evidence: Optional[List[str]] = None,
        medical_history: Optional[str] = None,
    ) -> ConfidenceReport:
        """
        评估诊断置信度
        
        Args:
            diagnosis: 诊断结果
            symptoms: 症状列表
            lab_results: 实验室结果
            imaging_findings: 影像学发现
            evidence: 支持证据
            medical_history: 病史
            
        Returns:
            ConfidenceReport: 置信度评估报告
        """
        factors = {}
        
        # 1. 评估证据充分度
        evidence_score = self._evaluate_evidence(evidence or [])
        factors["evidence"] = evidence_score
        
        # 2. 评估一致性
        consistency_score = self._evaluate_consistency(
            diagnosis, symptoms or [], lab_results or {}
        )
        factors["consistency"] = consistency_score
        
        # 3. 评估完整性
        completeness_score = self._evaluate_completeness(
            symptoms, lab_results, imaging_findings, medical_history
        )
        factors["completeness"] = completeness_score
        
        # 4. 评估确定性
        certainty_score = self._evaluate_certainty(diagnosis)
        factors["certainty"] = certainty_score
        
        # 计算总体置信度
        overall_score = self._calculate_overall_score(factors)
        
        # 确定置信度等级
        confidence_level = self._get_confidence_level(overall_score)
        
        # 评估风险等级
        risk_level = self._evaluate_risk(diagnosis, overall_score)
        
        # 生成建议
        recommendations = self._generate_recommendations(
            confidence_level, factors, diagnosis
        )
        
        # 生成警告
        warnings = self._generate_warnings(
            confidence_level, risk_level, diagnosis
        )
        
        return ConfidenceReport(
            overall_score=overall_score,
            confidence_level=confidence_level,
            evidence_score=evidence_score,
            consistency_score=consistency_score,
            completeness_score=completeness_score,
            risk_level=risk_level,
            factors=factors,
            recommendations=recommendations,
            warnings=warnings,
        )
    
    def _evaluate_evidence(self, evidence: List[str]) -> float:
        """评估证据充分度"""
        if not evidence:
            return 0.3
        
        score = 0.0
        max_weight = 0.0
        
        for e in evidence:
            for key, weight in self.EVIDENCE_WEIGHTS.items():
                if key in e or any(k in e for k in key.split()):
                    score += weight
                    max_weight = max(max_weight, weight)
                    break
            else:
                # 未匹配到预定义证据类型，给基础分
                score += 0.3
        
        # 归一化
        normalized = min(score / max(len(evidence), 1) * 0.5 + max_weight * 0.5, 1.0)
        return normalized
    
    def _evaluate_consistency(
        self,
        diagnosis: str,
        symptoms: List[str],
        lab_results: Dict,
    ) -> float:
        """评估一致性"""
        score = 0.5  # 基础分
        
        # 定义诊断-症状关联
        diagnosis_symptom_map = {
            "肺孢子虫肺炎": ["干咳", "呼吸困难", "发热", "低氧"],
            "PCP": ["干咳", "呼吸困难", "发热", "低氧"],
            "隐球菌脑膜炎": ["头痛", "发热", "意识改变", "颈强直"],
            "结核": ["咳嗽", "盗汗", "体重下降", "发热"],
            "肺炎": ["咳嗽", "发热", "胸痛", "呼吸困难"],
        }
        
        # 检查症状一致性
        for diag_key, expected_symptoms in diagnosis_symptom_map.items():
            if diag_key in diagnosis:
                matched = sum(1 for s in symptoms if any(es in s for es in expected_symptoms))
                if matched > 0:
                    score += min(matched / len(expected_symptoms) * 0.3, 0.3)
                break
        
        # 检查实验室结果一致性
        if lab_results:
            # CD4计数与HIV相关诊断
            cd4 = lab_results.get("CD4") or lab_results.get("cd4")
            if cd4 and isinstance(cd4, (int, float)):
                if "PCP" in diagnosis or "肺孢子虫" in diagnosis:
                    if cd4 < 200:
                        score += 0.2
                    elif cd4 < 350:
                        score += 0.1
        
        return min(score, 1.0)
    
    def _evaluate_completeness(
        self,
        symptoms: Optional[List[str]],
        lab_results: Optional[Dict],
        imaging: Optional[List[str]],
        history: Optional[str],
    ) -> float:
        """评估信息完整性"""
        score = 0.0
        
        # 各项信息的权重
        if symptoms and len(symptoms) > 0:
            score += 0.3
        if lab_results and len(lab_results) > 0:
            score += 0.3
        if imaging and len(imaging) > 0:
            score += 0.2
        if history and len(history) > 10:
            score += 0.2
        
        return score
    
    def _evaluate_certainty(self, diagnosis: str) -> float:
        """评估诊断确定性"""
        # 不确定性关键词
        uncertain_keywords = [
            "可能", "疑似", "待排除", "不除外", "考虑",
            "建议进一步", "需要确认", "待定",
        ]
        
        # 确定性关键词
        certain_keywords = [
            "确诊", "明确", "典型", "符合", "诊断明确",
        ]
        
        score = 0.5  # 基础分
        
        for kw in uncertain_keywords:
            if kw in diagnosis:
                score -= 0.1
        
        for kw in certain_keywords:
            if kw in diagnosis:
                score += 0.15
        
        return max(min(score, 1.0), 0.1)
    
    def _calculate_overall_score(self, factors: Dict[str, float]) -> float:
        """计算总体置信度"""
        weights = {
            "evidence": 0.35,
            "consistency": 0.25,
            "completeness": 0.20,
            "certainty": 0.20,
        }
        
        score = sum(
            factors.get(k, 0) * w 
            for k, w in weights.items()
        )
        
        return round(score, 3)
    
    def _get_confidence_level(self, score: float) -> str:
        """获取置信度等级"""
        if score >= self.THRESHOLDS["high"]:
            return "HIGH"
        elif score >= self.THRESHOLDS["medium"]:
            return "MEDIUM"
        elif score >= self.THRESHOLDS["low"]:
            return "LOW"
        else:
            return "UNCERTAIN"
    
    def _evaluate_risk(self, diagnosis: str, confidence: float) -> RiskLevel:
        """评估风险等级"""
        # 检查高风险关键词
        has_high_risk = any(kw in diagnosis for kw in self.HIGH_RISK_KEYWORDS)
        
        if has_high_risk and confidence < 0.6:
            return RiskLevel.CRITICAL
        elif has_high_risk:
            return RiskLevel.HIGH
        elif confidence < 0.5:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW
    
    def _generate_recommendations(
        self,
        confidence_level: str,
        factors: Dict[str, float],
        diagnosis: str,
    ) -> List[str]:
        """生成建议"""
        recommendations = []
        
        if factors.get("evidence", 0) < 0.5:
            recommendations.append("建议补充更多诊断依据")
        
        if factors.get("completeness", 0) < 0.5:
            recommendations.append("建议完善病史和检查资料")
        
        if confidence_level in ["LOW", "UNCERTAIN"]:
            recommendations.append("建议进一步检查以明确诊断")
            recommendations.append("必要时请专科会诊")
        
        if not recommendations:
            recommendations.append("诊断依据充分，可按诊断进行治疗")
        
        return recommendations
    
    def _generate_warnings(
        self,
        confidence_level: str,
        risk_level: RiskLevel,
        diagnosis: str,
    ) -> List[str]:
        """生成警告"""
        warnings = []
        
        if risk_level == RiskLevel.CRITICAL:
            warnings.append("⚠️ 危急情况：诊断不确定但可能为严重疾病，请立即处理")
        
        if confidence_level == "UNCERTAIN":
            warnings.append("⚠️ 置信度极低，诊断结果仅供参考")
        elif confidence_level == "LOW":
            warnings.append("⚠️ 置信度较低，建议谨慎采纳")
        
        warnings.append("本评估由AI生成，最终诊断请以临床医生判断为准")
        
        return warnings
    
    def add_custom_rule(
        self,
        condition: callable,
        score_modifier: float,
        description: str,
    ):
        """
        添加自定义评估规则
        
        Args:
            condition: 条件函数，接收诊断信息，返回bool
            score_modifier: 分数修正值 (-1 到 1)
            description: 规则描述
        """
        self._custom_rules.append({
            "condition": condition,
            "modifier": score_modifier,
            "description": description,
        })
    
    def format_report(self, report: ConfidenceReport) -> str:
        """格式化置信度报告"""
        lines = []
        lines.append("=" * 40)
        lines.append("【置信度评估报告】")
        lines.append("=" * 40)
        
        # 置信度等级
        level_emoji = {
            "HIGH": "🟢", "MEDIUM": "🟡", 
            "LOW": "🔴", "UNCERTAIN": "⚪"
        }
        lines.append(f"\n总体置信度: {level_emoji.get(report.confidence_level, '⚪')} "
                    f"{report.confidence_level} ({report.overall_score*100:.1f}%)")
        
        # 各维度得分
        lines.append(f"\n📊 评估维度:")
        lines.append(f"  • 证据充分度: {report.evidence_score*100:.0f}%")
        lines.append(f"  • 一致性: {report.consistency_score*100:.0f}%")
        lines.append(f"  • 完整性: {report.completeness_score*100:.0f}%")
        
        # 风险等级
        risk_emoji = {
            "critical": "🔴", "high": "🟠",
            "medium": "🟡", "low": "🟢"
        }
        lines.append(f"\n⚠️ 风险等级: {risk_emoji.get(report.risk_level.value, '⚪')} "
                    f"{report.risk_level.value.upper()}")
        
        # 建议
        if report.recommendations:
            lines.append(f"\n💡 建议:")
            for rec in report.recommendations:
                lines.append(f"  • {rec}")
        
        # 警告
        if report.warnings:
            lines.append(f"\n⚠️ 警告:")
            for warn in report.warnings:
                lines.append(f"  • {warn}")
        
        lines.append("\n" + "=" * 40)
        return "\n".join(lines)
