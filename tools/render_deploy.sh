#!/usr/bin/env bash
# Create the tab-demo web service on Render without touching the dashboard.
#
#   export RENDER_API_KEY=rnd_xxxxxxxx      # Account Settings -> API Keys -> Create
#   bash tools/render_deploy.sh
#
# Render's Blueprint page needs a tick and an approval click. This does not.
# It talks to the same API the dashboard talks to.
#
# Re-running is safe: if a service called tab-demo already exists it prints the
# URL and stops rather than making a second one.
set -euo pipefail

: "${RENDER_API_KEY:?set RENDER_API_KEY first (Render -> Account Settings -> API Keys)}"
REPO="${RENDER_REPO:-https://github.com/Zeref538/tab}"
NAME="${RENDER_SERVICE_NAME:-tab-demo}"
API="https://api.render.com/v1"
AUTH=(-H "Authorization: Bearer $RENDER_API_KEY" -H "Content-Type: application/json")

# Every service belongs to an owner (you, or a team). The API wants its id.
OWNER=$(curl -fsS "${AUTH[@]}" "$API/owners?limit=1" | python -c 'import json,sys; print(json.load(sys.stdin)[0]["owner"]["id"])')
echo "owner: $OWNER"

EXISTING=$(curl -fsS "${AUTH[@]}" "$API/services?name=$NAME&limit=1" \
  | python -c 'import json,sys; d=json.load(sys.stdin); print(d[0]["service"]["serviceDetails"]["url"] if d else "")')
if [ -n "$EXISTING" ]; then
  echo "already exists: $EXISTING"; exit 0
fi

# Mirrors render.yaml. The API does not read that file, so the values live here
# too - if you change one, change both.
cat > /tmp/render-service.json <<JSON
{
  "type": "web_service",
  "name": "$NAME",
  "ownerId": "$OWNER",
  "repo": "$REPO",
  "branch": "main",
  "autoDeploy": "yes",
  "serviceDetails": {
    "env": "python",
    "plan": "free",
    "region": "singapore",
    "healthCheckPath": "/api/health",
    "envSpecificDetails": {
      "buildCommand": "pip install \".[ocr]\"",
      "startCommand": "tab-demo --host 0.0.0.0"
    }
  },
  "envVars": [
    {"key": "PYTHON_VERSION",          "value": "3.12"},
    {"key": "TAB_RATE_LIMIT_PER_MIN",  "value": "20"},
    {"key": "TAB_MAX_UPLOAD",          "value": "8388608"},
    {"key": "TAB_MAX_CONCURRENT",      "value": "1"},
    {"key": "TAB_DEMO_MAX_EDGE",       "value": "1280"}
  ]
}
JSON

curl -fsS -X POST "${AUTH[@]}" -d @/tmp/render-service.json "$API/services" \
  | python -c 'import json,sys; s=json.load(sys.stdin)["service"]; print("created:", s["id"]); print("url:    ", s["serviceDetails"]["url"])'
echo "first build takes a few minutes. watch it in the dashboard, or:"
echo "  curl -H \"Authorization: Bearer \$RENDER_API_KEY\" $API/services?name=$NAME"
