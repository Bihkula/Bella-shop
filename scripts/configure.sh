#!/usr/bin/env bash
# Fill in your details once. Writes infra/terraform/shop.tfvars and replaces the
# placeholders in k8s/, argocd/ and platform/.
#
#   GITHUB_OWNER=me GITHUB_REPO=shop AWS_REGION=eu-west-2 bash scripts/configure.sh
#
# Optional: EKS_CLUSTER_NAME (default shop), KUBERNETES_VERSION (1.34),
# NODE_INSTANCE_TYPE (t3.large), NODE_COUNT (2),
# and for production later: RDS_ENDPOINT, ACM_CERTIFICATE_ARN, SHOP_DOMAIN.
set -euo pipefail
cd "$(dirname "$0")/.."

for v in GITHUB_OWNER GITHUB_REPO AWS_REGION; do
  [ -n "${!v:-}" ] || { echo "missing $v (see the top of this script)" >&2; exit 1; }
done
# ghcr.io image paths must be lowercase.
GHCR_OWNER=$(echo "$GITHUB_OWNER" | tr '[:upper:]' '[:lower:]')

: "${EKS_CLUSTER_NAME:=shop}" "${KUBERNETES_VERSION:=1.34}"
: "${NODE_INSTANCE_TYPE:=t3.large}" "${NODE_COUNT:=2}"
: "${RDS_ENDPOINT:=RDS_ENDPOINT}" "${ACM_CERTIFICATE_ARN:=ACM_CERTIFICATE_ARN}" "${SHOP_DOMAIN:=SHOP_DOMAIN}"

cat > infra/terraform/shop.tfvars <<EOF
# Written by scripts/configure.sh — shared by all three Terraform stacks.
aws_region         = "${AWS_REGION}"
cluster_name       = "${EKS_CLUSTER_NAME}"
github_owner       = "${GITHUB_OWNER}"
github_repo        = "${GITHUB_REPO}"
kubernetes_version = "${KUBERNETES_VERSION}"
node_instance_type = "${NODE_INSTANCE_TYPE}"
node_count         = ${NODE_COUNT}
EOF
echo "wrote infra/terraform/shop.tfvars"

files=$(grep -rlE 'GHCR_OWNER|AWS_REGION|GITHUB_OWNER|GITHUB_REPO|RDS_ENDPOINT|ACM_CERTIFICATE_ARN|SHOP_DOMAIN' \
  k8s argocd platform --include='*.yaml' || true)
for f in $files; do
  sed -i.bak \
    -e "s|ACM_CERTIFICATE_ARN|${ACM_CERTIFICATE_ARN}|g" \
    -e "s|GHCR_OWNER|${GHCR_OWNER}|g" \
    -e "s|AWS_REGION|${AWS_REGION}|g" \
    -e "s|GITHUB_OWNER|${GITHUB_OWNER}|g" \
    -e "s|GITHUB_REPO|${GITHUB_REPO}|g" \
    -e "s|RDS_ENDPOINT|${RDS_ENDPOINT}|g" \
    -e "s|SHOP_DOMAIN|${SHOP_DOMAIN}|g" \
    "$f"
  rm -f "$f.bak"
  echo "configured $f"
done

left=$(grep -rnwE 'RDS_ENDPOINT|ACM_CERTIFICATE_ARN|SHOP_DOMAIN' k8s || true)
if [ -n "$left" ]; then
  echo
  echo "Only needed for production later (fine to leave for now):"
  echo "$left"
fi
