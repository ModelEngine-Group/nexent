"use client";

import React from "react";
import { Database, Globe, BookOpen, FileText, Sparkles } from "lucide-react";

// 来源类型
export type SourceType = "internal" | "external" | "knowledge" | "reference" | "ai";

// 组件属性
interface SourceTagProps {
  type: SourceType;
  weight?: number;
  className?: string;
  size?: "sm" | "md" | "lg";
  showIcon?: boolean;
  showWeight?: boolean;
}

// 来源配置
const sourceConfig: Record<SourceType, {
  label: string;
  labelEn: string;
  color: string;
  bgColor: string;
  borderColor: string;
  icon: React.ReactNode;
  description: string;
}> = {
  internal: {
    label: "内部",
    labelEn: "Internal",
    color: "text-blue-700",
    bgColor: "bg-blue-50",
    borderColor: "border-blue-200",
    icon: <Database className="w-3 h-3" />,
    description: "来自本地知识库",
  },
  external: {
    label: "外部",
    labelEn: "External",
    color: "text-purple-700",
    bgColor: "bg-purple-50",
    borderColor: "border-purple-200",
    icon: <Globe className="w-3 h-3" />,
    description: "来自网络搜索",
  },
  knowledge: {
    label: "知识库",
    labelEn: "Knowledge",
    color: "text-green-700",
    bgColor: "bg-green-50",
    borderColor: "border-green-200",
    icon: <BookOpen className="w-3 h-3" />,
    description: "来自专业知识库",
  },
  reference: {
    label: "参考",
    labelEn: "Reference",
    color: "text-orange-700",
    bgColor: "bg-orange-50",
    borderColor: "border-orange-200",
    icon: <FileText className="w-3 h-3" />,
    description: "参考文献来源",
  },
  ai: {
    label: "AI分析",
    labelEn: "AI",
    color: "text-indigo-700",
    bgColor: "bg-indigo-50",
    borderColor: "border-indigo-200",
    icon: <Sparkles className="w-3 h-3" />,
    description: "AI生成内容",
  },
};

// 尺寸配置
const sizeConfig = {
  sm: {
    padding: "px-1.5 py-0.5",
    text: "text-xs",
    iconSize: "w-3 h-3",
    gap: "gap-1",
  },
  md: {
    padding: "px-2 py-1",
    text: "text-sm",
    iconSize: "w-3.5 h-3.5",
    gap: "gap-1.5",
  },
  lg: {
    padding: "px-3 py-1.5",
    text: "text-base",
    iconSize: "w-4 h-4",
    gap: "gap-2",
  },
};

export const SourceTag: React.FC<SourceTagProps> = ({
  type,
  weight,
  className = "",
  size = "sm",
  showIcon = true,
  showWeight = false,
}) => {
  const config = sourceConfig[type];
  const sizeStyle = sizeConfig[size];

  return (
    <span
      className={`inline-flex items-center ${sizeStyle.gap} ${sizeStyle.padding} ${sizeStyle.text} font-medium rounded-full border ${config.bgColor} ${config.borderColor} ${config.color} ${className}`}
      title={config.description}
    >
      {showIcon && config.icon}
      <span>{config.label}</span>
      {showWeight && weight !== undefined && (
        <span className="opacity-70">({weight}%)</span>
      )}
    </span>
  );
};

// 内部标签快捷组件
export const InternalTag: React.FC<Omit<SourceTagProps, "type">> = (props) => (
  <SourceTag type="internal" {...props} />
);

// 外部标签快捷组件
export const ExternalTag: React.FC<Omit<SourceTagProps, "type">> = (props) => (
  <SourceTag type="external" {...props} />
);

// 综合结论标签
export const ConclusionTag: React.FC<{ className?: string }> = ({ className = "" }) => (
  <span
    className={`inline-flex items-center gap-1 px-2 py-1 text-sm font-semibold rounded-full bg-gradient-to-r from-blue-500 to-purple-500 text-white ${className}`}
  >
    <Sparkles className="w-3.5 h-3.5" />
    综合结论
  </span>
);

// 解析消息中的来源标签
export const parseSourceTags = (text: string): React.ReactNode[] => {
  const parts: React.ReactNode[] = [];
  const regex = /\[内部\]|\[外部\]|\[内部知识库\]|\[外部最新信息\]|\[外部最新\]|\*\*\[内部\]\*\*|\*\*\[外部\]\*\*|\*\*\[内部知识库\]\*\*|\*\*\[外部最新信息\]\*\*|\*\*综合结论\*\*/g;
  
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    // 添加匹配前的文本
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    // 添加标签组件
    const matchText = match[0].replace(/\*\*/g, "");
    if (matchText.includes("内部")) {
      parts.push(<InternalTag key={match.index} weight={60} showWeight />);
    } else if (matchText.includes("外部")) {
      parts.push(<ExternalTag key={match.index} weight={40} showWeight />);
    } else if (matchText.includes("综合结论")) {
      parts.push(<ConclusionTag key={match.index} />);
    }

    lastIndex = regex.lastIndex;
  }

  // 添加剩余文本
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 0 ? parts : [text];
};

export default SourceTag;
