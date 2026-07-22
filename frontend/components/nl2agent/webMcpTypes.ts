export interface WebMcpInstallField {
  key: string;
  name: string;
  label?: string;
  description?: string;
  type?: "text" | "number" | "url" | "json";
  required?: boolean;
  secret?: boolean;
  default?: string | number | boolean | null;
  placeholder?: string;
  choices?: string[];
  category?: string;
  argument_type?: "named" | "positional";
  argument_name?: string | null;
  repeated?: boolean;
}

export interface WebMcpInstallOption {
  option_id: string;
  type: string;
  transport?: string | null;
  server_url_template?: string | null;
  requires_configuration?: boolean;
  label?: string;
  description?: string;
  status?: "ready" | "configuration_required" | "unsupported";
  supported?: boolean;
  unsupported_reason?: string;
  package_identifier?: string | null;
  registry_type?: string | null;
  runtime_hint?: string | null;
  fields?: WebMcpInstallField[];
}

export interface WebMcpCardItem {
  recommendation_id?: string;
  name: string;
  description?: string;
  source?: "registry" | "community";
  tags?: string[];
  transport?: string | null;
  score?: number;
  reason?: string;
  install_options?: WebMcpInstallOption[];
}
