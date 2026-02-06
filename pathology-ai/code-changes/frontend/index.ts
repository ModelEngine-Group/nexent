// Medical Visualization Components
// 医学可视化组件导出

export { MedicalKnowledgeGraph } from './MedicalKnowledgeGraph';
export { DiagnosisFlowChart } from './DiagnosisFlowChart';
export { MedicalDashboard } from './MedicalDashboard';
export { MedicalVisualizationPanel } from './MedicalVisualizationPanel';

// 新增组件
export { PathologyImageGallery } from './PathologyImageGallery';
export type { PathologyImage } from './PathologyImageGallery';

export { DiagnosisConfidenceCard } from './DiagnosisConfidenceCard';
export type { ConfidenceLevel, RiskLevel, EvaluationDimension, DiagnosisConfidenceCardProps } from './DiagnosisConfidenceCard';

export { SourceTag, InternalTag, ExternalTag, ConclusionTag, parseSourceTags } from './SourceTag';
export type { SourceType } from './SourceTag';
