"use client";

import React from "react";
import { CheckCircle, AlertCircle, AlertTriangle, HelpCircle, Info, Shield, Activity } from "lucide-react";

// 置信度等级类型
export type ConfidenceLevel = "HIGH" | "MEDIUM" | "LOW" | "UNCERTAIN";

// 风险等级类型
export type RiskLevel = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";

// 评估维度
export interface EvaluationDimension {
  name: string;
  score: number;
  maxScore: number;
  description?: string;
}

// 组件属性
export interface DiagnosisConfidenceCardProps {
  diagnosis: string;
  confidenceLevel: ConfidenceLevel;
  confidenceScore: number;
  riskLevel?: RiskLevel;
  dimensions?: EvaluationDimension[];
  recommendations?: string[];
  warnings?: string[];
  className?: string;
  compact?: boolean;
}

// 置信度配置
const confidenceConfig: Record<ConfidenceLevel, {
  label: string;
  color: string;
  bgColor: string;
  borderColor: string;
  icon: React.ReactNode;
  description: string;
}> = {
  HIGH: {
    label: "高置信度",
    color: "text-green-700",
    bgColor: "bg-green-50",
    borderColor: "border-green-200",
    icon: <CheckCircle className="w-5 h-5 text-green-600" />,
    description: "证据充分，诊断明确",
  },
  MEDIUM: {
    label: "中等置信度",
    color: "text-yellow-700",
    bgColor: "bg-yellow-50",
    borderColor: "border-yellow-200",
    icon: <AlertCircle className="w-5 h-5 text-yellow-600" />,
    description: "有一定依据，需进一步确认",
  },
  LOW: {
    label: "低置信度",
    color: "text-orange-700",
    bgColor: "bg-orange-50",
    borderColor: "border-orange-200",
    icon: <AlertTriangle className="w-5 h-5 text-orange-600" />,
    description: "信息不足，仅供参考",
  },
  UNCERTAIN: {
    label: "不确定",
    color: "text-gray-700",
    bgColor: "bg-gray-50",
    borderColor: "border-gray-200",
    icon: <HelpCircle className="w-5 h-5 text-gray-600" />,
    description: "无法做出可靠判断",
  },
};

// 风险等级配置
const riskConfig: Record<RiskLevel, {
  label: string;
  color: string;
  bgColor: string;
}> = {
  CRITICAL: {
    label: "危急",
    color: "text-red-700",
    bgColor: "bg-red-100",
  },
  HIGH: {
    label: "高风险",
    color: "text-orange-700",
    bgColor: "bg-orange-100",
  },
  MEDIUM: {
    label: "中等风险",
    color: "text-yellow-700",
    bgColor: "bg-yellow-100",
  },
  LOW: {
    label: "低风险",
    color: "text-green-700",
    bgColor: "bg-green-100",
  },
};

// 进度条组件
const ProgressBar: React.FC<{ value: number; max: number; color: string }> = ({ value, max, color }) => {
  const percentage = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
      <div
        className={`h-full ${color} transition-all duration-500`}
        style={{ width: `${percentage}%` }}
      />
    </div>
  );
};

// 获取进度条颜色
const getProgressColor = (score: number, max: number): string => {
  const percentage = (score / max) * 100;
  if (percentage >= 80) return "bg-green-500";
  if (percentage >= 60) return "bg-yellow-500";
  if (percentage >= 40) return "bg-orange-500";
  return "bg-red-500";
};

export const DiagnosisConfidenceCard: React.FC<DiagnosisConfidenceCardProps> = ({
  diagnosis,
  confidenceLevel,
  confidenceScore,
  riskLevel,
  dimensions = [],
  recommendations = [],
  warnings = [],
  className = "",
  compact = false,
}) => {
  const config = confidenceConfig[confidenceLevel];
  const risk = riskLevel ? riskConfig[riskLevel] : null;

  // 紧凑模式
  if (compact) {
    return (
      <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full ${config.bgColor} ${config.borderColor} border ${className}`}>
        {config.icon}
        <span className={`text-sm font-medium ${config.color}`}>
          {config.label} ({confidenceScore}%)
        </span>
      </div>
    );
  }

  return (
    <div className={`rounded-lg border ${config.borderColor} ${config.bgColor} overflow-hidden ${className}`}>
      {/* 头部 */}
      <div className="px-4 py-3 border-b border-inherit bg-white/50">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {config.icon}
            <div>
              <h3 className={`font-semibold ${config.color}`}>{config.label}</h3>
              <p className="text-xs text-gray-500">{config.description}</p>
            </div>
          </div>
          <div className="text-right">
            <div className={`text-2xl font-bold ${config.color}`}>{confidenceScore}%</div>
            {risk && (
              <span className={`text-xs px-2 py-0.5 rounded-full ${risk.bgColor} ${risk.color}`}>
                {risk.label}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* 诊断结论 */}
      <div className="px-4 py-3 border-b border-inherit">
        <div className="flex items-start gap-2">
          <Activity className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" />
          <div>
            <div className="text-xs text-gray-500 mb-1">诊断结论</div>
            <div className="font-medium text-gray-900">{diagnosis}</div>
          </div>
        </div>
      </div>

      {/* 评估维度 */}
      {dimensions.length > 0 && (
        <div className="px-4 py-3 border-b border-inherit">
          <div className="text-xs text-gray-500 mb-3 flex items-center gap-1">
            <Shield className="w-3 h-3" />
            评估维度
          </div>
          <div className="space-y-3">
            {dimensions.map((dim, index) => (
              <div key={index}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-gray-700">{dim.name}</span>
                  <span className="text-gray-500">{dim.score}/{dim.maxScore}</span>
                </div>
                <ProgressBar
                  value={dim.score}
                  max={dim.maxScore}
                  color={getProgressColor(dim.score, dim.maxScore)}
                />
                {dim.description && (
                  <p className="text-xs text-gray-400 mt-1">{dim.description}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 警告 */}
      {warnings.length > 0 && (
        <div className="px-4 py-3 border-b border-inherit bg-red-50/50">
          <div className="text-xs text-red-600 mb-2 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" />
            警告
          </div>
          <ul className="space-y-1">
            {warnings.map((warning, index) => (
              <li key={index} className="text-sm text-red-700 flex items-start gap-2">
                <span className="text-red-400">•</span>
                {warning}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 建议 */}
      {recommendations.length > 0 && (
        <div className="px-4 py-3">
          <div className="text-xs text-gray-500 mb-2 flex items-center gap-1">
            <Info className="w-3 h-3" />
            建议
          </div>
          <ul className="space-y-1">
            {recommendations.map((rec, index) => (
              <li key={index} className="text-sm text-gray-700 flex items-start gap-2">
                <span className="text-blue-400">→</span>
                {rec}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 底部免责声明 */}
      <div className="px-4 py-2 bg-gray-100/50 text-xs text-gray-400 text-center">
        ⚠️ AI辅助分析结果，仅供参考，请以专业医生诊断为准
      </div>
    </div>
  );
};

export default DiagnosisConfidenceCard;
