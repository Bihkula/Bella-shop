# Reads the passwords file the persistent stack saved in the state bucket and
# creates the Kubernetes Secrets the apps expect. Runs on every `up`, so a
# rebuilt cluster always gets the same passwords.

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.aws_region]
  }
}

data "aws_s3_object" "secrets" {
  bucket = var.state_bucket
  key    = "secrets/shop-secrets.json"
}

locals {
  secrets = jsondecode(data.aws_s3_object.secrets.body)

  # Kubernetes namespace => which block of the file to use.
  shop_namespaces = {
    "shop-dev"  = "dev"
    "shop-prod" = "prod"
  }
}

# Namespaces are also declared in git (k8s/overlays/*/namespace.yaml) and
# managed by Argo CD; Terraform only makes sure they exist first so the
# Secrets have somewhere to live. Argo's labels/annotations are left alone.
resource "kubernetes_namespace_v1" "this" {
  for_each = toset(concat(keys(local.shop_namespaces), ["monitoring"]))

  metadata {
    name = each.key
  }

  lifecycle {
    ignore_changes = [metadata[0].labels, metadata[0].annotations]
  }

  depends_on = [module.eks]
}

resource "kubernetes_secret_v1" "shop" {
  for_each = local.shop_namespaces

  metadata {
    name      = "shop-secrets"
    namespace = kubernetes_namespace_v1.this[each.key].metadata[0].name
  }

  data = local.secrets[each.value]
}

resource "kubernetes_secret_v1" "grafana_admin" {
  metadata {
    name      = "grafana-admin"
    namespace = kubernetes_namespace_v1.this["monitoring"].metadata[0].name
  }

  data = local.secrets["grafana"]
}
