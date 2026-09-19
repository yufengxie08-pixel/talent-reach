#!/bin/sh
set -eu

PROJECT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
LINKEDIN_MCP_BIN="${LINKEDIN_MCP_BIN:-$(command -v mcp-server-linkedin || true)}"
PROFILE_DIR="${LINKEDIN_PROFILE_DIR:-$PROJECT_DIR/work/linkedin-mcp-session/profile}"
CHROME_BIN="${CHROME_PATH:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

if [ -z "$LINKEDIN_MCP_BIN" ] || [ ! -x "$LINKEDIN_MCP_BIN" ]; then
  echo "LinkedIn MCP is not available on PATH." >&2
  echo "Install mcp-server-linkedin or set LINKEDIN_MCP_BIN to its executable path." >&2
  exit 1
fi

mkdir -p "$(dirname "$PROFILE_DIR")"
chmod 700 "$(dirname "$PROFILE_DIR")"

export LINKEDIN_TRACE_MODE=off
export CHROME_PATH="$CHROME_BIN"

echo "LinkedIn MCP: http://127.0.0.1:8765/mcp"
echo "Keep this Terminal window open while Talent Reach is using LinkedIn."

exec "$LINKEDIN_MCP_BIN" \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8765 \
  --path /mcp \
  --user-data-dir "$PROFILE_DIR" \
  --claim-profile-root \
  --no-auto-import \
  --no-daemon \
  --log-level INFO
