variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
}

variable "cluster_version" {
  description = "Kubernetes version"
  type        = string
}

variable "cpu_instance_type" {
  description = "Instance type for CPU node group"
  type        = string
}

variable "gpu_instance_type" {
  description = "Instance type for GPU node group"
  type        = string
}

variable "cpu_min_size" {
  description = "Minimum nodes in CPU node group"
  type        = number
}

variable "cpu_max_size" {
  description = "Maximum nodes in CPU node group"
  type        = number
}

variable "cpu_desired_size" {
  description = "Desired nodes in CPU node group"
  type        = number
}

variable "gpu_min_size" {
  description = "Minimum nodes in GPU node group"
  type        = number
}

variable "gpu_max_size" {
  description = "Maximum nodes in GPU node group"
  type        = number
}

variable "gpu_desired_size" {
  description = "Desired nodes in GPU node group"
  type        = number
}

variable "region" {
  description = "AWS region"
  type        = string
}

variable "profile" {
  description = "AWS profile"
  type        = string
  default     = null
}

variable "tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}

variable "cluster_endpoint_public_access" {
  description = "Enable public access for the EKS cluster endpoint"
  type        = bool
}

variable "cluster_endpoint_private_access" {
  description = "Enable private access for the EKS cluster endpoint"
  type        = bool
}

variable "cluster_public_access_cidrs" {
  description = "List of CIDR blocks that can access the Amazon EKS public API server endpoint"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "cluster_admin_users" {
  description = "List of IAM user ARNs to be granted cluster admin access"
  type        = list(string)
  default     = []
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "private_subnets" {
  description = "List of private subnet IDs"
  type        = list(string)
}
