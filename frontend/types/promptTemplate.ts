export interface PromptTemplate {
  template_id: number;
  name: string;
  description?: string | null;
  prompt_text: string;
  is_builtin?: boolean;
  tenant_id?: string;
  create_time?: string;
  update_time?: string;
}

export interface PromptTemplateCreateRequest {
  name: string;
  description?: string;
  prompt_text: string;
}

export interface PromptTemplateUpdateRequest {
  template_id: number;
  name?: string;
  description?: string;
  prompt_text?: string;
}

export interface PromptTemplateDeleteRequest {
  template_id: number;
}

