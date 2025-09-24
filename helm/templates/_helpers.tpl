+17
-0

{{- define "aiops.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "aiops.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "aiops.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" -}}
{{- end -}}

{{-/*
Provide compatibility aliases that follow the Helm chart's full name so the
templates can reference {{ include "aiops-quality-service.*" }} without
duplicating logic.
*/ -}}
{{- define "aiops-quality-service.name" -}}
{{- include "aiops.name" . -}}
{{- end -}}

{{- define "aiops-quality-service.fullname" -}}
{{- include "aiops.fullname" . -}}
{{- end -}}