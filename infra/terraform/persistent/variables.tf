# Shared variables (same set in every stack so one shop.tfvars feeds them all).
variable "aws_region" { type = string }
variable "cluster_name" { type = string }
variable "github_owner" { type = string }
variable "github_repo" { type = string }
variable "kubernetes_version" { type = string }
variable "node_instance_type" { type = string }
variable "node_count" { type = number }


variable "state_bucket" {
  type        = string
  description = "The Terraform state bucket (passed by scripts/infra.sh). Also holds secrets/shop-secrets.json."
}
