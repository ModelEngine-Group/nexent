import type { ReactNode } from "react";

export interface ResourceSectionProps {
  highFidelity?: boolean;
  renderSection?: (content: ReactNode, headerActions: ReactNode) => ReactNode;
}
