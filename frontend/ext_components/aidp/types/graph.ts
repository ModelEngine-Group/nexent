export interface AidpGraphParameter {
  param_key: string;
  param_name: string;
  param_value: string;
  param_desc: string;
  regexp: string;
  is_modifiable: boolean;
  template?: Record<string, string>;
}

export interface AidpGraphTemplate {
  value: AidpGraphParameter[];
}

export interface AidpModelOption {
  label: string;
  value: string;
}
