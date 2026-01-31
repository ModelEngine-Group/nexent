"""
医疗模块 API 接口
Medical Module API for Nexent Platform

提供RESTful API接口，支持：
1. 智能体模板管理
2. 诊断推理链调用
3. 置信度评估
4. 提示词管理

Author: Pathology AI Team
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

from .agent_templates import MedicalAgentTemplates, MedicalDomain
from .chain_of_diagnosis import ChainOfDiagnosis, DiagnosisResult
from .confidence_evaluator import ConfidenceEvaluator
from .medical_prompts import MedicalPromptLibrary, PromptCategory


# 创建路由
router = APIRouter(prefix="/medical", tags=["Medical"])

# 初始化组件
templates_manager = MedicalAgentTemplates()
cod_engine = ChainOfDiagnosis()
confidence_evaluator = ConfidenceEvaluator()
prompt_library = MedicalPromptLibrary()


# ==================== 请求/响应模型 ====================

class DiagnosisRequest(BaseModel):
    """诊断请求"""
    symptoms: str = Field(..., description="症状描述")
    lab_results: Optional[str] = Field(None, description="实验室检查结果")
    medical_history: Optional[str] = Field(None, description="既往病史")
    imaging_findings: Optional[str] = Field(None, description="影像学发现")


class DiagnosisResponse(BaseModel):
    """诊断响应"""
    success: bool
    data: Dict[str, Any]
    formatted_report: str


class ConfidenceRequest(BaseModel):
    """置信度评估请求"""
    diagnosis: str = Field(..., description="诊断结果")
    symptoms: Optional[List[str]] = Field(None, description="症状列表")
    lab_results: Optional[Dict] = Field(None, description="实验室结果")
    evidence: Optional[List[str]] = Field(None, description="支持证据")


class ConfidenceResponse(BaseModel):
    """置信度评估响应"""
    success: bool
    data: Dict[str, Any]
    formatted_report: str


class TemplateResponse(BaseModel):
    """模板响应"""
    success: bool
    data: Dict[str, Any]


class PromptsResponse(BaseModel):
    """提示词响应"""
    success: bool
    data: List[Dict[str, Any]]


# ==================== 智能体模板 API ====================

@router.get("/templates", response_model=TemplateResponse)
async def list_templates(
    domain: Optional[str] = Query(None, description="按领域筛选")
):
    """
    获取医疗智能体模板列表
    
    Args:
        domain: 可选，按领域筛选 (pathology/radiology/clinical/pharmacy/laboratory/general)
    
    Returns:
        模板列表
    """
    try:
        domain_enum = MedicalDomain(domain) if domain else None
        templates = templates_manager.list_templates(domain_enum)
        return TemplateResponse(
            success=True,
            data={
                "templates": [t.to_dict() for t in templates],
                "count": len(templates),
            }
        )
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid domain: {domain}")


@router.get("/templates/{template_id}", response_model=TemplateResponse)
async def get_template(template_id: str):
    """
    获取指定模板详情
    
    Args:
        template_id: 模板ID
    
    Returns:
        模板详情
    """
    template = templates_manager.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")
    
    return TemplateResponse(
        success=True,
        data=template.to_dict()
    )


@router.get("/templates/ids/list")
async def list_template_ids():
    """获取所有模板ID列表"""
    return {
        "success": True,
        "template_ids": templates_manager.list_template_ids()
    }


# ==================== 诊断推理链 API ====================

@router.post("/diagnosis/analyze", response_model=DiagnosisResponse)
async def analyze_diagnosis(request: DiagnosisRequest):
    """
    使用诊断推理链(CoD)进行诊断分析
    
    Args:
        request: 诊断请求，包含症状、检查结果等
    
    Returns:
        诊断结果，包含推理链和置信度
    """
    try:
        result = cod_engine.analyze(
            symptoms=request.symptoms,
            lab_results=request.lab_results,
            medical_history=request.medical_history,
            imaging_findings=request.imaging_findings,
        )
        
        return DiagnosisResponse(
            success=True,
            data=result.to_dict(),
            formatted_report=result.to_formatted_string()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/diagnosis/cod-prompt")
async def get_cod_prompt():
    """
    获取CoD诊断推理链提示词模板
    
    Returns:
        CoD提示词，可用于配置LLM
    """
    return {
        "success": True,
        "prompt": cod_engine.generate_cod_prompt(),
        "description": "诊断推理链(Chain-of-Diagnosis)提示词模板"
    }


# ==================== 置信度评估 API ====================

@router.post("/confidence/evaluate", response_model=ConfidenceResponse)
async def evaluate_confidence(request: ConfidenceRequest):
    """
    评估诊断置信度
    
    Args:
        request: 评估请求，包含诊断和相关信息
    
    Returns:
        置信度评估报告
    """
    try:
        report = confidence_evaluator.evaluate(
            diagnosis=request.diagnosis,
            symptoms=request.symptoms,
            lab_results=request.lab_results,
            evidence=request.evidence,
        )
        
        return ConfidenceResponse(
            success=True,
            data=report.to_dict(),
            formatted_report=confidence_evaluator.format_report(report)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 提示词库 API ====================

@router.get("/prompts", response_model=PromptsResponse)
async def list_prompts(
    category: Optional[str] = Query(None, description="按分类筛选")
):
    """
    获取医疗提示词列表
    
    Args:
        category: 可选，按分类筛选 (diagnosis/treatment/safety/specialty/general)
    
    Returns:
        提示词列表
    """
    try:
        category_enum = PromptCategory(category) if category else None
        prompts = prompt_library.list_prompts(category_enum)
        
        # 简化输出，不包含完整prompt文本
        simplified = [
            {
                "id": p["id"],
                "name": p["name"],
                "category": p["category"].value,
                "description": p["description"],
                "tags": p["tags"],
            }
            for p in prompts
        ]
        
        return PromptsResponse(
            success=True,
            data=simplified
        )
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid category: {category}")


@router.get("/prompts/{prompt_id}")
async def get_prompt(prompt_id: str):
    """
    获取指定提示词详情
    
    Args:
        prompt_id: 提示词ID
    
    Returns:
        提示词详情，包含完整文本
    """
    prompt = prompt_library.get_prompt(prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail=f"Prompt not found: {prompt_id}")
    
    return {
        "success": True,
        "data": {
            "id": prompt["id"],
            "name": prompt["name"],
            "category": prompt["category"].value,
            "description": prompt["description"],
            "prompt": prompt["prompt"],
            "variables": prompt["variables"],
            "tags": prompt["tags"],
        }
    }


@router.get("/prompts/recommended/full")
async def get_recommended_prompt():
    """
    获取推荐的完整医疗助手提示词
    
    Returns:
        推荐提示词，包含CoD、不确定性感知和安全提醒
    """
    return {
        "success": True,
        "prompt": prompt_library.get_recommended_prompt(),
        "description": "推荐的完整医疗助手提示词，包含诊断推理链、置信度标注和安全提醒"
    }


@router.post("/prompts/combine")
async def combine_prompts(prompt_ids: List[str]):
    """
    组合多个提示词
    
    Args:
        prompt_ids: 要组合的提示词ID列表
    
    Returns:
        组合后的提示词文本
    """
    combined = prompt_library.combine_prompts(prompt_ids)
    if not combined:
        raise HTTPException(status_code=400, detail="No valid prompts found")
    
    return {
        "success": True,
        "combined_prompt": combined,
        "source_prompts": prompt_ids
    }


# ==================== 健康检查 ====================

@router.get("/health")
async def health_check():
    """医疗模块健康检查"""
    return {
        "status": "healthy",
        "module": "medical",
        "version": "1.0.0",
        "components": {
            "templates": len(templates_manager.list_template_ids()),
            "prompts": len(prompt_library.list_prompt_ids()),
            "cod_engine": "ready",
            "confidence_evaluator": "ready",
        }
    }
