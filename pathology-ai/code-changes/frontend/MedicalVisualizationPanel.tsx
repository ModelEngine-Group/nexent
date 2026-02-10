"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { MedicalKnowledgeGraph } from "./MedicalKnowledgeGraph";
import { DiagnosisFlowChart } from "./DiagnosisFlowChart";
import { MedicalDashboard } from "./MedicalDashboard";

// Tab类型
type TabType = "dashboard" | "knowledge-graph" | "diagnosis-flow";

// 组件属性
interface MedicalVisualizationPanelProps {
  defaultTab?: TabType;
  showTabs?: TabType[];
  className?: string;
}

// Tab配置
const tabConfig: Record<TabType, { label: string; icon: string; description: string }> = {
  dashboard: {
    label: "统计仪表盘",
    icon: "📊",
    description: "知识库统计数据概览",
  },
  "knowledge-graph": {
    label: "知识图谱",
    icon: "🧠",
    description: "医学概念关联网络",
  },
  "diagnosis-flow": {
    label: "诊断流程",
    icon: "🔄",
    description: "疾病诊断决策流程",
  },
};

export const MedicalVisualizationPanel: React.FC<MedicalVisualizationPanelProps> = ({
  defaultTab = "dashboard",
  showTabs = ["dashboard", "knowledge-graph", "diagnosis-flow"],
  className = "",
}) => {
  const { t } = useTranslation("common");
  const [activeTab, setActiveTab] = useState<TabType>(defaultTab);

  return (
    <div className={`bg-white rounded-lg shadow-lg overflow-hidden ${className}`}>
      {/* Header */}
      <div className="bg-gradient-to-r from-blue-600 to-purple-600 px-6 py-4">
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <span>🏥</span>
          医学知识可视化中心
        </h1>
        <p className="text-blue-100 text-sm mt-1">
          基于病理学知识库的智能可视化分析
        </p>
      </div>

      {/* Tab Navigation */}
      <div className="border-b bg-gray-50">
        <div className="flex overflow-x-auto">
          {showTabs.map((tab) => {
            const config = tabConfig[tab];
            const isActive = activeTab === tab;
            return (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`flex items-center gap-2 px-6 py-3 text-sm font-medium whitespace-nowrap transition-all border-b-2 ${
                  isActive
                    ? "border-blue-600 text-blue-600 bg-white"
                    : "border-transparent text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                }`}
              >
                <span className="text-lg">{config.icon}</span>
                <span>{config.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Tab Description */}
      <div className="px-6 py-2 bg-blue-50 border-b text-sm text-blue-700">
        {tabConfig[activeTab].icon} {tabConfig[activeTab].description}
      </div>

      {/* Content */}
      <div className="p-6">
        {activeTab === "dashboard" && <MedicalDashboard height="650px" />}
        {activeTab === "knowledge-graph" && <MedicalKnowledgeGraph height="550px" />}
        {activeTab === "diagnosis-flow" && <DiagnosisFlowChart height="600px" />}
      </div>

      {/* Footer */}
      <div className="px-6 py-3 bg-gray-50 border-t text-xs text-gray-500 flex justify-between items-center">
        <span>数据来源: 病理学知识库</span>
        <span>最后更新: {new Date().toLocaleDateString()}</span>
      </div>
    </div>
  );
};

export default MedicalVisualizationPanel;
