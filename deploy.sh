#!/bin/bash
set -e

IMAGE="lucasabu1988/omnicapital:latest"

echo "Building Docker image (linux/amd64)..."
docker buildx build --platform linux/amd64 -t "$IMAGE" .

echo "Pushing image to Docker Hub..."
docker push "$IMAGE"

echo "Triggering Render deploy..."
if [ -n "$RENDER_DEPLOY_HOOK_URL" ]; then
    curl -s -X POST "$RENDER_DEPLOY_HOOK_URL"
    echo ""
    echo "Deploy triggered on Render!"
else
    echo "WARNING: RENDER_DEPLOY_HOOK_URL not set. Set it to auto-trigger deploys."
    echo "Find it at: Render Dashboard > omnicapital > Settings > Deploy Hook"
    echo "Then: export RENDER_DEPLOY_HOOK_URL='https://api.render.com/deploy/...'"
fi

echo "Done!"
