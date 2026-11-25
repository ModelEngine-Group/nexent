{{- /*
Nexent Helm Chart - Helper templates
*/ -}}

{{- define "nexent.fullname" -}}
{{- default .Chart.Name .Values.global.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "nexent.namespace" -}}
{{- default .Values.global.namespace }}
{{- end }}

{{- define "nexent.labels" -}}
app.kubernetes.io/name: {{ include "nexent.fullname" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}

{{- define "nexent.podLabels" -}}
app: {{ include "nexent.fullname" . }}
{{- end }}

{{- define "nexent.backendPlatformEnv" -}}
{{- $provider := default "docker" .Values.global.sandboxProvider -}}
{{- if not (has $provider (list "docker" "kubernetes")) -}}
{{- fail "global.sandboxProvider must be docker or kubernetes" -}}
{{- end -}}
- name: TZ
  valueFrom:
    configMapKeyRef:
      name: nexent-config
      key: TZ
- name: IS_DEPLOYED_BY_KUBERNETES
  value: "true"
- name: KUBERNETES_NAMESPACE
  value: {{ .Values.global.namespace | quote }}
- name: NEXENT_MCP_DOCKER_IMAGE
  valueFrom:
    configMapKeyRef:
      name: nexent-config
      key: NEXENT_MCP_DOCKER_IMAGE
- name: NEXENT_SANDBOX_DOCKER_IMAGE
  valueFrom:
    configMapKeyRef:
      name: nexent-config
      key: NEXENT_SANDBOX_DOCKER_IMAGE
- name: NEXENT_SANDBOX_DEFAULT_LEVEL
  value: {{ ternary "local" $provider (eq (default "lightweight" .Values.global.sandboxMode) "disabled") | quote }}
- name: NEXENT_SANDBOX_PROVIDER
  value: {{ $provider | quote }}
- name: NEXENT_RUNTIME_DEPLOYMENT_ID
  value: {{ .Release.Name | quote }}
- name: NEXENT_SANDBOX_ENABLED
  value: {{ ternary "false" "true" (eq (default "lightweight" .Values.global.sandboxMode) "disabled") | quote }}
{{- if eq $provider "kubernetes" }}
- name: NEXENT_SANDBOX_DEFAULT_SCOPE
  value: "system"
- name: NEXENT_SANDBOX_FAILURE_POLICY
  value: "error"
{{- end }}
{{- end }}
