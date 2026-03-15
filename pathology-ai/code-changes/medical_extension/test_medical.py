"""
医疗模块测试脚本
Test script for Medical Module
"""

import sys
import os

# 添加路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from medical import (
    ChainOfDiagnosis,
    MedicalAgentTemplates,
    ConfidenceEvaluator,
    MedicalPromptLibrary,
)


def test_chain_of_diagnosis():
    """测试诊断推理链"""
    print("=" * 50)
    print("测试: Chain-of-Diagnosis (CoD)")
    print("=" * 50)
    
    cod = ChainOfDiagnosis()
    
    # 测试案例: HIV患者肺部感染
    result = cod.analyze(
        symptoms="干咳、呼吸困难、发热",
        lab_results="CD4计数: 150, LDH升高",
        medical_history="HIV阳性5年，未规律服药",
    )
    
    print(f"\n主要诊断: {result.primary_diagnosis}")
    print(f"置信度: {result.confidence_level.value} ({result.confidence_score*100:.1f}%)")
    print(f"鉴别诊断: {', '.join(result.differential_diagnoses)}")
    print(f"推理步骤数: {len(result.reasoning_chain)}")
    
    print("\n[OK] CoD测试通过")
    return True


def test_agent_templates():
    """测试智能体模板"""
    print("\n" + "=" * 50)
    print("测试: Medical Agent Templates")
    print("=" * 50)
    
    templates = MedicalAgentTemplates()
    
    # 列出所有模板
    all_templates = templates.list_templates()
    print(f"\n可用模板数量: {len(all_templates)}")
    
    for t in all_templates:
        print(f"  - {t.name} ({t.template_id})")
    
    # 获取病理模板
    pathology = templates.get_template("pathology_diagnosis")
    if pathology:
        print(f"\n病理模板工具: {', '.join(pathology.suggested_tools)}")
    
    print("\n[OK] 模板测试通过")
    return True


def test_confidence_evaluator():
    """测试置信度评估"""
    print("\n" + "=" * 50)
    print("测试: Confidence Evaluator")
    print("=" * 50)
    
    evaluator = ConfidenceEvaluator()
    
    report = evaluator.evaluate(
        diagnosis="肺孢子虫肺炎 (PCP)",
        symptoms=["干咳", "呼吸困难", "发热"],
        lab_results={"CD4": 150, "LDH": "升高"},
        evidence=["HIV阳性", "CD4<200", "典型症状"],
    )
    
    print(f"\n总体置信度: {report.confidence_level} ({report.overall_score*100:.1f}%)")
    print(f"证据充分度: {report.evidence_score*100:.0f}%")
    print(f"一致性: {report.consistency_score*100:.0f}%")
    print(f"风险等级: {report.risk_level.value}")
    
    print("\n[OK] 置信度评估测试通过")
    return True


def test_prompt_library():
    """测试提示词库"""
    print("\n" + "=" * 50)
    print("测试: Medical Prompt Library")
    print("=" * 50)
    
    library = MedicalPromptLibrary()
    
    # 列出所有提示词
    all_prompts = library.list_prompts()
    print(f"\n可用提示词数量: {len(all_prompts)}")
    
    for p in all_prompts:
        print(f"  - {p['name']} ({p['id']})")
    
    # 获取推荐提示词
    recommended = library.get_recommended_prompt()
    print(f"\n推荐提示词长度: {len(recommended)} 字符")
    
    print("\n[OK] 提示词库测试通过")
    return True


def main():
    """运行所有测试"""
    print("\n" + "#" * 60)
    print("# Nexent 医疗模块测试")
    print("#" * 60)
    
    tests = [
        test_chain_of_diagnosis,
        test_agent_templates,
        test_confidence_evaluator,
        test_prompt_library,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"\n[FAIL] {test.__name__}: {e}")
            failed += 1
    
    print("\n" + "#" * 60)
    print(f"# 测试结果: {passed} 通过, {failed} 失败")
    print("#" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
