#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
USER_BIN="${HOME}/.local/bin"

for required in uv mcporter; do
  if ! command -v "$required" >/dev/null 2>&1; then
    print -u2 "缺少命令：$required"
    exit 1
  fi
done

uv tool install --force --from "$PROJECT_DIR" talent-reach

register_server() {
  local name="$1"
  local executable="$2"
  mcporter config remove "$name" --scope home >/dev/null 2>&1 || true
  mcporter config add "$name" --command "${USER_BIN}/${executable}" --scope home
}

register_server aboutme mcp-aboutme
register_server quora mcp-quora
register_server wellfound mcp-wellfound
register_server stackexchange mcp-stackexchange
register_server github-public mcp-github-public
register_server personal-site mcp-personal-site
register_server talent-resolver mcp-talent-resolver
register_server org-ranking mcp-org-ranking
register_server talent-qualifier mcp-talent-qualifier
register_server talent-batch mcp-talent-batch

talent-reach-doctor
print "talent-reach 0.4.0 已安装，并注册 10 个 MCP。"
