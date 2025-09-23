variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "goit-mlops-eks-cluster"
}

variable "argocd_namespace" {
  description = "Kubernetes namespace for ArgoCD"
  type        = string
  default     = "infra-tools"
}

variable "argocd_version" {
  description = "ArgoCD Helm chart version"
  type        = string
  default     = "5.46.8"
}

variable "argocd_values_file" {
  description = "Path to ArgoCD values file"
  type        = string
  default     = "./values/argocd-values.yaml"
}
