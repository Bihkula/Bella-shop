#!/usr/bin/env bash
# One command for the AWS infrastructure.
#
#   bash scripts/infra.sh setup    # once: S3 state bucket + generated passwords
#   bash scripts/infra.sh up       # create the EKS cluster (~20 min); Argo CD redeploys the shop
#   bash scripts/infra.sh down     # tear the cluster down (~15 min) — stops the hourly cost
#   bash scripts/infra.sh status   # what exists right now
#   bash scripts/infra.sh secrets  # show the passwords (admin login, Grafana, ...)
#
# `down` never touches the S3 bucket (state + passwords file), and images live on
# ghcr.io, so `up` the next day brings back exactly the same shop.
set -euo pipefail
cd "$(dirname "$0")/.."

TF=infra/terraform
VARS=$TF/shop.tfvars
[ -f "$VARS" ] || { echo "Run scripts/configure.sh first." >&2; exit 1; }

var() { sed -n "s/^$1 *= *\"\{0,1\}\([^\"]*\)\"\{0,1\}.*/\1/p" "$VARS" | head -1; }
REGION=$(var aws_region)
CLUSTER=$(var cluster_name)
ACCOUNT=$(aws sts get-caller-identity --query Account --output text | tr -d '\r')
BUCKET="shop-tfstate-${ACCOUNT}-${REGION}"
SECRETS_KEY="secrets/shop-secrets.json"

say() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
tf() { local dir=$1; shift; terraform -chdir="$TF/$dir" "$@"; }
tf_init() {
  tf "$1" init -input=false -reconfigure \
    -backend-config="bucket=$BUCKET" -backend-config="region=$REGION" >/dev/null
}
cluster_exists() {
  aws eks describe-cluster --name "$CLUSTER" --region "$REGION" >/dev/null 2>&1
}
kubeconfig() {
  aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION" >/dev/null
}

cmd_setup() {
  say "State bucket s3://$BUCKET"
  if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
    echo "already exists"
  else
    tf bootstrap init -input=false >/dev/null
    tf bootstrap apply -var-file=../shop.tfvars -var "state_bucket=$BUCKET"
  fi

  say "Passwords file (s3://$BUCKET/$SECRETS_KEY)"
  tf_init persistent
  tf persistent apply -var-file=../shop.tfvars -var "state_bucket=$BUCKET"

  say "Done. These stay when you run 'down'."
}

cmd_up() {
  say "Creating cluster '$CLUSTER' in $REGION (takes ~20 minutes)"
  aws s3api head-object --bucket "$BUCKET" --key "$SECRETS_KEY" >/dev/null 2>&1 ||
    { echo "Passwords file not found. Run 'bash scripts/infra.sh setup' first." >&2; exit 1; }
  tf_init cluster
  tf cluster apply -var-file=../shop.tfvars -var "state_bucket=$BUCKET"
  kubeconfig
  say "Cluster is up"
  echo "Argo CD is now deploying everything from git (5-10 minutes). Watch it with:"
  echo "  kubectl get applications -n argocd"
  echo "  kubectl get pods -n shop-dev"
  echo "Shop address (once ready):"
  echo "  kubectl -n shop-dev get ingress shop"
}

wait_for() { # wait_for <description> <timeout-seconds> <command...> (until command prints nothing)
  local what=$1 timeout=$2; shift 2
  local waited=0
  while [ -n "$("$@" 2>/dev/null)" ]; do
    if [ "$waited" -ge "$timeout" ]; then echo "  gave up waiting for $what"; return 1; fi
    echo "  waiting for $what..."; sleep 15; waited=$((waited + 15))
  done
}

albs() {
  aws resourcegroupstaggingapi get-resources --region "$REGION" \
    --resource-type-filters elasticloadbalancing:loadbalancer \
    --tag-filters "Key=elbv2.k8s.aws/cluster,Values=$CLUSTER" \
    --query 'ResourceTagMappingList[].ResourceARN' --output text | tr -d '\r'
}

cmd_down() {
  if cluster_exists; then
    kubeconfig
    # Remove what Kubernetes created *outside* Terraform's knowledge first:
    # the ALB (made by the load balancer controller) and EBS volumes (made by
    # PVCs). Otherwise they'd keep costing money and block deleting the VPC.
    say "Stopping Argo CD from recreating things"
    kubectl -n argocd delete applications --all --wait=false 2>/dev/null || true

    say "Deleting load balancers"
    kubectl delete ingress --all -A --wait=false 2>/dev/null || true
    wait_for "ALBs to be deleted" 600 albs || true

    say "Deleting volumes"
    kubectl delete statefulset --all -A --wait=false 2>/dev/null || true
    kubectl delete pvc --all -A --wait=false 2>/dev/null || true
    wait_for "EBS volumes to be released" 600 kubectl get pv -o name || true
  else
    echo "Cluster '$CLUSTER' not found; destroying whatever Terraform still tracks."
  fi

  say "Destroying cluster infrastructure (takes ~15 minutes)"
  tf_init cluster
  # Things that live *inside* the cluster disappear with it, so tell Terraform
  # to forget them instead of deleting them one by one (faster, and avoids
  # hanging on a half-deleted namespace).
  for addr in kubernetes_secret_v1.shop kubernetes_secret_v1.grafana_admin \
              kubernetes_namespace_v1.this helm_release.argocd_root_app \
              helm_release.argocd helm_release.aws_load_balancer_controller; do
    tf cluster state rm "$addr" >/dev/null 2>&1 || true
  done
  tf cluster destroy -var-file=../shop.tfvars -var "state_bucket=$BUCKET"

  leftover=$(albs)
  [ -z "$leftover" ] || echo "WARNING: load balancers still exist, delete them in the EC2 console: $leftover"
  say "Cluster gone. Kept: S3 bucket with state + passwords (images are on ghcr.io). Run 'up' to continue."
}

cmd_status() {
  echo "Region:        $REGION"
  echo "State bucket:  $(aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null && echo "s3://$BUCKET" || echo 'not created (run setup)')"
  echo "Passwords:     $(aws s3api head-object --bucket "$BUCKET" --key "$SECRETS_KEY" >/dev/null 2>&1 && echo "s3://$BUCKET/$SECRETS_KEY" || echo 'not created (run setup)')"
  if cluster_exists; then
    echo "EKS cluster:   $CLUSTER is RUNNING (costing money)"
  else
    echo "EKS cluster:   not running"
  fi
  echo "Leftover ALBs: $(albs || true)"
}

cmd_secrets() {
  aws s3 cp "s3://$BUCKET/$SECRETS_KEY" - | tr -d '\r'
  echo
}

case "${1:-}" in
  setup)   cmd_setup ;;
  secrets) cmd_secrets ;;
  up)     cmd_up ;;
  down)   cmd_down ;;
  status) cmd_status ;;
  *) sed -n '2,11p' "$0"; exit 1 ;;
esac
