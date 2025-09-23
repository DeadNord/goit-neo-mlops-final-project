output "cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS cluster endpoint"
  value       = module.eks.cluster_endpoint
}

output "node_group_names" {
  description = "Names of managed node groups"
  value       = keys(module.eks.eks_managed_node_groups)
}