#!/bin/bash
set -euo pipefail

# Renders the hello-world Backstage skeleton with substituted template variables
# so you can test the output locally without going through RHDH.
#
# Usage: ./test-template.sh <component-id> [github-owner] [github-repo]
#
# Example:
#   ./test-template.sh my-app alex-struk my-app
#   cd .test-output/my-app && docker build -t my-app .
#   oc apply --dry-run=server -f .test-output/my-app/openshift/ -n fd34fb-prod

COMPONENT_ID="${1:?Usage: $0 <component-id> [github-owner] [github-repo]}"
GITHUB_OWNER="${2:-alex-struk}"
GITHUB_REPO="${3:-$COMPONENT_ID}"
DESCRIPTION="A simple hello world Node.js service"
OWNER="user:default/test-user"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKELETON_DIR="$SCRIPT_DIR/templates/hello-world/skeleton"
OUTPUT_DIR="$SCRIPT_DIR/.test-output/$COMPONENT_ID"

if [ ! -d "$SKELETON_DIR" ]; then
  echo "ERROR: Skeleton directory not found at $SKELETON_DIR"
  exit 1
fi

rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"
cp -r "$SKELETON_DIR"/. "$OUTPUT_DIR"/

# Substitute Backstage template variables
find "$OUTPUT_DIR" -type f | while read -r file; do
  sed -i \
    -e "s|\\\${{ *values.component_id *}}|${COMPONENT_ID}|g" \
    -e "s|\\\${{ *values.description *}}|${DESCRIPTION}|g" \
    -e "s|\\\${{ *values.owner *}}|${OWNER}|g" \
    -e "s|\\\${{ *values.destination.owner + \"/\" + values.destination.repo *}}|${GITHUB_OWNER}/${GITHUB_REPO}|g" \
    -e "s|\\\${{ *values.destination.owner *}}|${GITHUB_OWNER}|g" \
    -e "s|\\\${{ *values.destination.repo *}}|${GITHUB_REPO}|g" \
    -e 's/{% raw %}//g' \
    -e 's/{% endraw %}//g' \
    "$file"
done

echo "Rendered template to: $OUTPUT_DIR"
echo ""
echo "Next steps:"
echo "  Inspect:    ls -la $OUTPUT_DIR"
echo "  Build:      cd $OUTPUT_DIR && docker build -t $COMPONENT_ID ."
echo "  Dry-run:    oc apply --dry-run=server -f $OUTPUT_DIR/openshift/ -n fd34fb-prod"
echo "  Deploy:     oc apply -f $OUTPUT_DIR/openshift/ -n fd34fb-prod"
