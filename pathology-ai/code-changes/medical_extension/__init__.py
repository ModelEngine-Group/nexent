"""
Nexent 医疗领域扩展模块
Medical Domain Extension for Nexent Platform

本模块提供医疗领域的智能体模板、诊断推理链框架和专业工具集。

Features:
- 医疗智能体模板系统
- Chain-of-Diagnosis (CoD) 诊断推理链框架
- 置信度评估系统
- 医疗提示词库

Author: Pathology AI Team
Version: 1.0.0
License: MIT
"""

from .agent_templates import MedicalAgentTemplates, AgentTemplate, MedicalDomain
from .chain_of_diagnosis import (
    ChainOfDiagnosis, 
    DiagnosisResult, 
    DiagnosisStep,
    ConfidenceLevel,
)
from .confidence_evaluator import (
    ConfidenceEvaluator, 
    ConfidenceReport,
    RiskLevel,
)
from .medical_prompts import MedicalPromptLibrary, PromptCategory

__all__ = [
    # 智能体模板
    'MedicalAgentTemplates',
    'AgentTemplate',
    'MedicalDomain',
    # 诊断推理链
    'ChainOfDiagnosis',
    'DiagnosisResult',
    'DiagnosisStep',
    'ConfidenceLevel',
    # 置信度评估
    'ConfidenceEvaluator',
    'ConfidenceReport',
    'RiskLevel',
    # 提示词库
    'MedicalPromptLibrary',
    'PromptCategory',
]

__version__ = '1.0.0'
__author__ = 'Pathology AI Team'
