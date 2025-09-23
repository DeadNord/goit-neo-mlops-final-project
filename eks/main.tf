module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.4"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  vpc_id     = var.vpc_id
  subnet_ids = var.private_subnets

  cluster_endpoint_public_access       = var.cluster_endpoint_public_access
  cluster_endpoint_private_access      = var.cluster_endpoint_private_access
  cluster_endpoint_public_access_cidrs = var.cluster_public_access_cidrs

  cluster_addons = {
    coredns = {
      most_recent = true
    }
    kube-proxy = {
      most_recent = true
    }
    vpc-cni = {
      most_recent = true
      configuration_values = jsonencode({
        env = {
          ENABLE_PREFIX_DELEGATION = "true"
          WARM_PREFIX_TARGET       = "1"
        }
      })
    }
  }

  eks_managed_node_groups = {
    cpu = {
      instance_types = [var.cpu_instance_type]
      min_size       = var.cpu_min_size
      max_size       = var.cpu_max_size
      desired_size   = var.cpu_desired_size
    }
    gpu = {
      instance_types = [var.gpu_instance_type]
      min_size       = var.gpu_min_size
      max_size       = var.gpu_max_size
      desired_size   = var.gpu_desired_size
    }
  }

  tags = var.tags
}

resource "aws_eks_access_entry" "cluster_admin" {
  count         = length(var.cluster_admin_users)
  cluster_name  = module.eks.cluster_name
  principal_arn = var.cluster_admin_users[count.index]
  type          = "STANDARD"

  depends_on = [module.eks]
}

# Associate cluster admin policy
resource "aws_eks_access_policy_association" "cluster_admin" {
  count         = length(var.cluster_admin_users)
  cluster_name  = module.eks.cluster_name
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  principal_arn = var.cluster_admin_users[count.index]

  access_scope {
    type = "cluster"
  }

  depends_on = [aws_eks_access_entry.cluster_admin]
}
