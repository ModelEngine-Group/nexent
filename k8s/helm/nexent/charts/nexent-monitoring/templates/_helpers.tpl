{{- define "nexent-monitoring.provider" -}}
{{- $globalMonitoring := default dict .Values.global.monitoring -}}
{{- $provider := default .Values.provider $globalMonitoring.provider | default "otlp" | lower -}}
{{- if eq $provider "collector" -}}otlp{{- else -}}{{ $provider }}{{- end -}}
{{- end -}}

{{- define "nexent-monitoring.collectorConfigFile" -}}
{{- if .Values.collector.configFile -}}
{{- .Values.collector.configFile -}}
{{- else -}}
{{- $provider := include "nexent-monitoring.provider" . -}}
{{- if eq $provider "phoenix" -}}otel-collector-phoenix-config.yml
{{- else if eq $provider "langfuse" -}}otel-collector-langfuse-config.yml
{{- else if eq $provider "langsmith" -}}otel-collector-langsmith-config.yml
{{- else if eq $provider "grafana" -}}otel-collector-grafana-config.yml
{{- else if eq $provider "zipkin" -}}otel-collector-zipkin-config.yml
{{- else -}}otel-collector-config.yml
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "nexent-monitoring.phoenixEnabled" -}}
{{- if or .Values.phoenix.enabled (eq (include "nexent-monitoring.provider" .) "phoenix") -}}true{{- end -}}
{{- end -}}

{{- define "nexent-monitoring.grafanaEnabled" -}}
{{- if or .Values.grafana.enabled (eq (include "nexent-monitoring.provider" .) "grafana") -}}true{{- end -}}
{{- end -}}

{{- define "nexent-monitoring.tempoEnabled" -}}
{{- if or .Values.tempo.enabled .Values.grafana.enabled (eq (include "nexent-monitoring.provider" .) "grafana") -}}true{{- end -}}
{{- end -}}

{{- define "nexent-monitoring.zipkinEnabled" -}}
{{- if or .Values.zipkin.enabled (eq (include "nexent-monitoring.provider" .) "zipkin") -}}true{{- end -}}
{{- end -}}

{{- define "nexent-monitoring.langfuseEnabled" -}}
{{- if or .Values.langfuse.enabled (eq (include "nexent-monitoring.provider" .) "langfuse") -}}true{{- end -}}
{{- end -}}

{{- define "nexent-monitoring.langfuseAuthHeader" -}}
{{- if .Values.collector.env.langfuseOtlpAuthHeader -}}
{{- .Values.collector.env.langfuseOtlpAuthHeader -}}
{{- else -}}
Basic {{ printf "%s:%s" .Values.langfuse.init.projectPublicKey .Values.langfuse.init.projectSecretKey | b64enc }}
{{- end -}}
{{- end -}}

{{- define "nexent-monitoring.langsmithApiKey" -}}
{{- $globalMonitoring := default dict .Values.global.monitoring -}}
{{- default (default "" $globalMonitoring.langsmithApiKey) .Values.collector.env.langsmithApiKey -}}
{{- end -}}

{{- define "nexent-monitoring.langsmithProject" -}}
{{- $globalMonitoring := default dict .Values.global.monitoring -}}
{{- default (default (default "nexent" $globalMonitoring.projectName) $globalMonitoring.langsmithProject) .Values.collector.env.langsmithProject -}}
{{- end -}}

{{- define "nexent-monitoring.langsmithOtlpTracesEndpoint" -}}
{{- $globalMonitoring := default dict .Values.global.monitoring -}}
{{- default (default "" $globalMonitoring.langsmithOtlpTracesEndpoint) .Values.collector.env.langsmithOtlpTracesEndpoint -}}
{{- end -}}

{{- define "nexent-monitoring.langfuseEnv" -}}
- name: NEXTAUTH_URL
  value: {{ .Values.langfuse.nextauthUrl | quote }}
- name: NEXTAUTH_SECRET
  value: {{ .Values.langfuse.nextauthSecret | quote }}
- name: DATABASE_URL
  value: {{ printf "postgresql://%s:%s@nexent-langfuse-postgres:5432/%s" .Values.langfuse.postgres.user .Values.langfuse.postgres.password .Values.langfuse.postgres.database | quote }}
- name: SALT
  value: {{ .Values.langfuse.salt | quote }}
- name: ENCRYPTION_KEY
  value: {{ .Values.langfuse.encryptionKey | quote }}
- name: TELEMETRY_ENABLED
  value: {{ .Values.langfuse.telemetryEnabled | quote }}
- name: LANGFUSE_ENABLE_EXPERIMENTAL_FEATURES
  value: {{ .Values.langfuse.enableExperimentalFeatures | quote }}
- name: CLICKHOUSE_MIGRATION_URL
  value: clickhouse://nexent-langfuse-clickhouse:9000
- name: CLICKHOUSE_URL
  value: http://nexent-langfuse-clickhouse:8123
- name: CLICKHOUSE_USER
  value: {{ .Values.langfuse.clickhouse.user | quote }}
- name: CLICKHOUSE_PASSWORD
  value: {{ .Values.langfuse.clickhouse.password | quote }}
- name: CLICKHOUSE_CLUSTER_ENABLED
  value: "false"
- name: REDIS_HOST
  value: nexent-langfuse-redis
- name: REDIS_PORT
  value: "6379"
- name: REDIS_AUTH
  value: {{ .Values.langfuse.redis.auth | quote }}
- name: REDIS_TLS_ENABLED
  value: "false"
- name: LANGFUSE_USE_AZURE_BLOB
  value: "false"
- name: LANGFUSE_USE_OCI_NATIVE_OBJECT_STORAGE
  value: "false"
- name: LANGFUSE_S3_EVENT_UPLOAD_BUCKET
  value: {{ .Values.langfuse.minio.bucket | quote }}
- name: LANGFUSE_S3_EVENT_UPLOAD_REGION
  value: auto
- name: LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID
  value: {{ .Values.langfuse.minio.rootUser | quote }}
- name: LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY
  value: {{ .Values.langfuse.minio.rootPassword | quote }}
- name: LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT
  value: http://nexent-langfuse-minio:9000
- name: LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE
  value: "true"
- name: LANGFUSE_S3_EVENT_UPLOAD_PREFIX
  value: events/
- name: LANGFUSE_S3_MEDIA_UPLOAD_BUCKET
  value: {{ .Values.langfuse.minio.bucket | quote }}
- name: LANGFUSE_S3_MEDIA_UPLOAD_REGION
  value: auto
- name: LANGFUSE_S3_MEDIA_UPLOAD_ACCESS_KEY_ID
  value: {{ .Values.langfuse.minio.rootUser | quote }}
- name: LANGFUSE_S3_MEDIA_UPLOAD_SECRET_ACCESS_KEY
  value: {{ .Values.langfuse.minio.rootPassword | quote }}
- name: LANGFUSE_S3_MEDIA_UPLOAD_ENDPOINT
  value: http://nexent-langfuse-minio:9000
- name: LANGFUSE_S3_MEDIA_UPLOAD_FORCE_PATH_STYLE
  value: "true"
- name: LANGFUSE_S3_MEDIA_UPLOAD_PREFIX
  value: media/
- name: LANGFUSE_S3_BATCH_EXPORT_ENABLED
  value: "false"
- name: LANGFUSE_S3_BATCH_EXPORT_BUCKET
  value: {{ .Values.langfuse.minio.bucket | quote }}
- name: LANGFUSE_S3_BATCH_EXPORT_REGION
  value: auto
- name: LANGFUSE_S3_BATCH_EXPORT_ENDPOINT
  value: http://nexent-langfuse-minio:9000
- name: LANGFUSE_S3_BATCH_EXPORT_EXTERNAL_ENDPOINT
  value: http://nexent-langfuse-minio:9000
- name: LANGFUSE_S3_BATCH_EXPORT_ACCESS_KEY_ID
  value: {{ .Values.langfuse.minio.rootUser | quote }}
- name: LANGFUSE_S3_BATCH_EXPORT_SECRET_ACCESS_KEY
  value: {{ .Values.langfuse.minio.rootPassword | quote }}
- name: LANGFUSE_S3_BATCH_EXPORT_FORCE_PATH_STYLE
  value: "true"
{{- end -}}
