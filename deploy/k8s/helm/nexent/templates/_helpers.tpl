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
