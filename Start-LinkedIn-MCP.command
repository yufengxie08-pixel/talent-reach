#!/bin/sh
set -eu

PROJECT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"

cd "$PROJECT_DIR"

echo "Step 1/3: Create or refresh the dedicated LinkedIn session."
./scripts/linkedin-login.sh

echo "Step 2/3: Point Talent Reach at the local macOS service."
mcporter config add linkedin \
  --scope project \
  --url http://127.0.0.1:8765/mcp \
  --description "LinkedIn MCP 4.24.3 via local macOS service"

echo "Step 3/3: Start the LinkedIn MCP service."
echo "Keep this Terminal window open while LinkedIn tools are in use."
exec ./scripts/linkedin-serve.sh
