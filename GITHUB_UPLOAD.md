# Talent Reach GitHub 上传说明

这是按“海外人才数据搜索”范围整理的精简源码包。包内只有运行项目所需的源码、平台
适配器、MCP 服务入口、排名与资格判定、测试、示例、安装脚本和 LinkedIn 辅助脚本。

没有打包本机配置、浏览器登录会话、Cookie、实时候选人结果、旧版安装脚本或验收报告。
`config/mcporter.example.json` 是不含本机绝对路径的示例配置。

## 安装与测试

```bash
cd talent-reach
uv sync --extra test
./install-v0.4.sh
uv run pytest
```

LinkedIn 需要在目标电脑上另外安装 `mcp-server-linkedin`，再运行：

```bash
./scripts/linkedin-login.sh
./scripts/linkedin-serve.sh
```

登录资料只会写入项目的 `work/` 目录；该目录已加入 `.gitignore`，不要上传。

## 上传到 GitHub

```bash
git init
git add .
git commit -m "Initial Talent Reach MCP suite"
git branch -M main
git remote add origin https://github.com/<用户名>/<仓库名>.git
git push -u origin main
```
