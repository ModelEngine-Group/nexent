export interface MemoryItem {
  id: string
  memory: string
  user_id: string
  agent_id: string
  agent_name: string
  update_date: string
}

export interface MemoryGroup {
  title: string
  key: string
  items: MemoryItem[]
}

// Memory modal interfaces
export interface MemoryDeleteModalProps {
  visible: boolean;
  targetTitle?: string | null;
  onOk: () => void;
  onCancel: () => void;
}

export interface MemoryManageModalProps {
  visible: boolean;
  onClose: () => void;
  userRole?: "admin" | "user";
}

// Page size
export const pageSize = 4

// Label with icon function type
export type LabelWithIconFunction = (Icon: React.ElementType, text: string) => JSX.Element;

// Use memory hook options interface
export interface UseMemoryOptions {
  visible: boolean
  currentUserId: string
  currentTenantId: string
  message?: any
}
