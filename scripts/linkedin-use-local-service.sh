#!/bin/sh
set -eu

mcporter config add linkedin \
  --scope project \
  --url http://127.0.0.1:8765/mcp \
  --description "LinkedIn MCP 4.24.3 via local macOS service"

mcporter list linkedin --json
