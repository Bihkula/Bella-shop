# PERSISTENT stack — things that must survive a nightly cluster teardown.
# Never destroyed by scripts/infra.sh.
#   * The app passwords, generated once and saved as a JSON file in the
#     (private, encrypted, versioned) Terraform state bucket:
#       s3://<state bucket>/secrets/shop-secrets.json
#     The cluster stack reads that file on every `up` and creates the
#     Kubernetes Secrets, so passwords stay the same across rebuilds.
# (Container images live in GitHub Container Registry, not AWS.)
#
# Learning-project trade-off: a dedicated secrets store (AWS Secrets Manager)
# adds rotation and per-secret audit logs. Here the state file already holds
# these values anyway, so keeping them in the same locked-down bucket costs
# nothing extra.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  # bucket + region are passed by scripts/infra.sh (-backend-config).
  backend "s3" {
    key          = "persistent/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region
  default_tags { tags = { Project = "shop", Stack = "persistent" } }
}

# ------------------------------------------------------------ passwords
resource "random_password" "db" {
  for_each = toset(["dev", "prod"])
  length   = 32
  special  = false # used inside a DB connection URL
}

resource "random_password" "jwt" {
  for_each = toset(["dev", "prod"])
  length   = 64
  special  = false
}

resource "random_password" "internal" {
  for_each = toset(["dev", "prod"])
  length   = 40
  special  = false
}

resource "random_password" "admin" {
  for_each = toset(["dev", "prod", "grafana"])
  length   = 20
  special  = false
}

locals {
  env_secrets = {
    for env in ["dev", "prod"] : env => {
      DB_PASSWORD            = random_password.db[env].result
      JWT_SECRET             = random_password.jwt[env].result
      INTERNAL_TOKEN         = random_password.internal[env].result
      ADMIN_EMAIL            = "admin@example.com"
      ADMIN_PASSWORD         = random_password.admin[env].result
      STRIPE_SECRET_KEY      = ""
      STRIPE_WEBHOOK_SECRET  = ""
      STRIPE_PUBLISHABLE_KEY = ""
    }
  }
}

# Written once. ignore_changes means edits you make to the file yourself
# (e.g. adding Stripe keys or an RDS password) are never overwritten.
resource "aws_s3_object" "secrets" {
  bucket       = var.state_bucket
  key          = "secrets/shop-secrets.json"
  content_type = "application/json"

  server_side_encryption = "AES256"
  content = jsonencode({
    dev  = local.env_secrets["dev"]
    prod = local.env_secrets["prod"]
    grafana = {
      "admin-user"     = "admin"
      "admin-password" = random_password.admin["grafana"].result
    }
  })

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [content]
  }
}

output "secrets_file" {
  value = "s3://${var.state_bucket}/${aws_s3_object.secrets.key}"
}
