export interface WebMcpInstallField {
  key: string;
  name: string;
  label?: string;
  description?: string;
  type?: "text" | "number" | "url" | "json";
  required?: boolean;
  secret?: boolean;
  default?: string | null;
  placeholder?: string;
  choices?: string[];
  category?: string;
}

export interface WebMcpInstallOption {
  option_id: string;
  type: string;
  transport?: string;
  server_url_template?: string;
  requires_configuration?: boolean;
  label?: string;
  description?: string;
  status?: "ready" | "configuration_required" | "unsupported";
  supported?: boolean;
  unsupported_reason?: string;
  fields?: WebMcpInstallField[];
}

export interface WebMcpCardItem {
  recommendation_id?: string;
  name: string;
  description?: string;
  source?: string;
  url?: string;
  transport?: string;
  score?: number;
  reason?: string;
  install_options?: WebMcpInstallOption[];
  prefill?: Record<string, string>;
}
