# Backend configuration for storing Terraform state
# Local backend for development
terraform {
  backend "local" {
    path = "terraform.tfstate"
  }
}
