module "vpc" {
  source = "./vpc"

  vpc_name             = var.vpc_name
  vpc_cidr             = var.vpc_cidr
  availability_zones   = var.availability_zones
  public_subnets       = var.public_subnets
  private_subnets      = var.private_subnets
  enable_nat_gateway   = var.enable_nat_gateway
  enable_dns_hostnames = var.enable_dns_hostnames
  enable_dns_support   = var.enable_dns_support
  single_nat_gateway   = var.single_nat_gateway
  tags                 = var.tags
  region               = var.region
  profile              = var.profile
}

module "eks" {
  source = "./eks"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  cpu_instance_type = var.cpu_instance_type
  gpu_instance_type = var.gpu_instance_type

  cpu_min_size     = var.cpu_min_size
  cpu_max_size     = var.cpu_max_size
  cpu_desired_size = var.cpu_desired_size

  gpu_min_size     = var.gpu_min_size
  gpu_max_size     = var.gpu_max_size
  gpu_desired_size = var.gpu_desired_size

  vpc_id                          = module.vpc.vpc_id
  private_subnets                 = module.vpc.private_subnets
  cluster_endpoint_public_access  = var.cluster_endpoint_public_access
  cluster_endpoint_private_access = var.cluster_endpoint_private_access
  cluster_public_access_cidrs     = var.cluster_public_access_cidrs
  cluster_admin_users             = var.cluster_admin_users
  region                          = var.region
  profile                         = var.profile
  tags                            = var.tags
}
