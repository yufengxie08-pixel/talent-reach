# Talent Reach MCP Suite

这是一个按 Agent Reach 思路实现、但按平台拆分的公开人才研究工具组。它不是一个
`public-web` MCP 同时假装支持所有网站；每个平台都有独立的 MCP 入口、工具契约、
解析逻辑、后端顺序和健康检查。共享代码只负责安全抓取、浏览器桥接、数据模型和证据
规范。

## 架构

```text
调用方 / Agent Reach
  ├─ mcp-aboutme ───────── About.me 搜索与公开资料解析
  ├─ mcp-quora ─────────── Quora 专业活动证据
  ├─ mcp-wellfound ─────── Wellfound 公开履历
  ├─ mcp-stackexchange ─── Stack Exchange API、声誉与技术标签
  ├─ mcp-github-public ─── GitHub 公共 REST、公开邮箱字段与仓库语言
  ├─ mcp-personal-site ─── 有界同域网站、浏览器回退与公开 CV PDF
  ├─ mcp-talent-resolver ─ 跨平台身份核验与证据合并
  ├─ mcp-org-ranking ───── 版本化 QS / Fortune 机构证据
  ├─ mcp-talent-qualifier  博士、排名、STEM、单位、邮箱硬条件判断
  └─ mcp-talent-batch ──── 有界并发、失败隔离、汇总与安全 CSV
                    │
                    └─ 共享安全内核：SSRF、robots、限速、证据来源、OpenCLI
```

`talent-reach` 命令保留为 `mcp-talent-resolver` 的兼容别名。旧的通用网页读取模块仍是
内部低层组件，但不再作为多平台 MCP 接口暴露。

## MCP 与工具

| MCP 配置名 | 可执行文件 | 工具 | 后端顺序 |
|---|---|---|---|
| `aboutme` | `mcp-aboutme` | `search_aboutme_profiles`、`read_aboutme_profile`、`aboutme_doctor` | OpenCLI 浏览器 → 公开 HTTP |
| `quora` | `mcp-quora` | `search_quora_profiles`、`read_quora_profile`、`quora_doctor` | OpenCLI 浏览器 → 公开 HTTP |
| `wellfound` | `mcp-wellfound` | `search_wellfound_people`、`read_wellfound_profile`、`wellfound_doctor` | 公开 HTTP → OpenCLI 补充 |
| `stackexchange` | `mcp-stackexchange` | `search_stackoverflow_people`、`read_stackoverflow_profile`、`stackexchange_doctor` | Stack Exchange 公共 API |
| `github-public` | `mcp-github-public` | `search_github_people`、`read_github_profile`、`github_public_doctor` | GitHub 公共 REST |
| `personal-site` | `mcp-personal-site` | `read_personal_site`、`read_public_cv_pdf`、`personal_site_doctor` | 有界公开抓取 → OpenCLI → 公开 CV PDF |
| `talent-resolver` | `mcp-talent-resolver` | `resolve_candidate_profiles`、`enrich_candidate_urls`、`talent_platforms_doctor` | 按 URL 分发后保守合并 |
| `org-ranking` | `mcp-org-ranking` | 排名查询、机构解析、快照校验、doctor | 本地版本化证据快照 |
| `talent-qualifier` | `mcp-talent-qualifier` | `qualify_talent_candidate`、`research_and_qualify_candidate`、`talent_qualifier_doctor` | 五项硬条件三态规则引擎 |
| `talent-batch` | `mcp-talent-batch` | `qualify_talent_batch`、`qualification_results_to_csv`、`talent_batch_doctor` | 最多 100 人、并发上限 8、逐人失败隔离 |

LinkedIn、Facebook 和 X/Twitter 不在这套代码里重复实现：它们继续使用已经安装的
`mcp-server-linkedin`、OpenCLI 和 `twitter-cli`。本套件负责 Agent Reach 原来缺失或
需要加强的渠道。

## 统一输出与身份核验

所有平台输出统一包含 `platform`、`profile_url`、`name`、`headline`、`location`、
`current_org`、`education`、`education_records`、`employment_records`、`skills`、
`contacts`、`links`、`evidence`、`fetched_at`
和 `warnings`。每个可用邮箱都标记来源 URL，且只能来自页面、公共 API 字段或公开 CV
中明确展示的内容。

邮箱联系人额外包含 `owner_name`、`owner_role`、`ownership_confidence`、
`association_basis`、`extraction_method` 和可见原文。只有 `owner_role=candidate` 且归属
置信度至少 0.85 的公开邮箱，才会通过硬条件验证；助理、管理员、实验室和归属不明邮箱
不会被当作候选人邮箱。

身份解析器不会仅凭同名自动合并。当前可解释权重是：公开邮箱重合 0.45、资料页直接
链接到另一资料页 0.45（普通共享链接 0.20）、姓名相似度最高 0.20、机构 0.10、地点
0.05；姓名相似度太低时总分封顶。
分数达到 0.65 才标记为 `same_person_likely`，其余结果要求人工复核。

## 排名和硬条件验证

内置 QS 2027 数据是从 QS 官方页面核验过的**有限子集**，不是伪装成完整榜单。
未覆盖学校返回 `unresolved`，绝不会按名称相似度猜排名。可以用
`TALENT_REACH_QS_DATA=/absolute/path/qs.json` 接入有权使用的完整快照。

Fortune 数据默认不内置，因为需要确定榜单类型、年份和合法数据来源。设置
`TALENT_REACH_FORTUNE_DATA=/absolute/path/fortune.json` 后才启用；未配置时明确返回
`unavailable`，不会把知名企业自动当作 Fortune 500。

自定义快照的最小格式：

```json
{
  "edition": "2027",
  "coverage": "full_authorized_snapshot",
  "source_url": "https://official-source.example/",
  "organizations": [
    {
      "canonical_name": "Example University",
      "aliases": ["EU"],
      "domains": ["example.edu"],
      "type": "university",
      "ranking_system": "QS_WUR",
      "edition": "2027",
      "rank": 42,
      "country_or_region": "Example",
      "source_url": "https://official-source.example/record"
    }
  ]
}
```

Fortune 记录使用同样的机构基础字段，并在 `memberships` 中保存 `list`、`year`、`rank`
和 `source_url`。不要把 QS 与 Fortune 两套来源混成单一的“知名机构”标记。

配置快照前可调用 `org-ranking.validate_organization_snapshot`。缺少版本、来源 URL、有效
排名、机构类型，或者存在重复别名/域名时会返回逐条错误。环境变量指向不存在或损坏的
文件时返回 `config_error`，不会静默退回内置数据。

资格验证器逐项返回 `pass`、`fail` 或 `review`：

1. 有明确博士证据；
2. 博士学校满足指定 QS 名次，且按配置属于海外；
3. 当前单位是指定 QS 名次内学校，或在已配置 Fortune 快照中；
4. 履历中有明确 STEM 学科或研究方向；
5. 有候选人本人明确公开且归属可信的邮箱。

只有五项全部 `pass` 才输出 `decision=eligible`。证据不足一律是 `review`，不会自动放行。

## 批量运行和导出

`talent-batch.qualify_talent_batch` 接受最多 100 个任务。每个任务必须提供
`candidate_name`，再二选一提供：

- 已由 LinkedIn 或其他 MCP 规范化的 `profiles`；
- 最多 10 个可公开读取的 `urls`。

默认并发为 3，硬上限为 8。单个候选人失败只记录在该行，不会中断整批任务。结果包含
`eligible`、`ineligible`、`review`、`error` 汇总。

`qualification_results_to_csv` 返回 UTF-8 CSV 文本，包含姓名、本人公开邮箱、完整教育
经历、博士学校和 QS 名次、当前单位、STEM/邮箱检查、未解决项和来源链接。对以
`= + - @` 开头的单元格自动加前缀，避免 Excel/Google Sheets 公式注入。

也可以直接使用命令行：

```bash
talent-reach-batch \
  --input examples/batch_jobs.example.json \
  --output candidates.csv \
  --json-output candidates.evidence.json
```

## 安装和注册

在本项目目录直接运行一键脚本（会覆盖安装 `talent-reach`，并重建本套件的 10 个
MCP 配置；不会修改独立的 LinkedIn 配置）：

```bash
./install-v0.4.sh
```

或者手工执行：

```bash
uv tool install --force --from /absolute/path/to/talent-reach talent-reach

mcporter config add aboutme --command "$HOME/.local/bin/mcp-aboutme" --scope home
mcporter config add quora --command "$HOME/.local/bin/mcp-quora" --scope home
mcporter config add wellfound --command "$HOME/.local/bin/mcp-wellfound" --scope home
mcporter config add stackexchange --command "$HOME/.local/bin/mcp-stackexchange" --scope home
mcporter config add github-public --command "$HOME/.local/bin/mcp-github-public" --scope home
mcporter config add personal-site --command "$HOME/.local/bin/mcp-personal-site" --scope home
mcporter config add talent-resolver --command "$HOME/.local/bin/mcp-talent-resolver" --scope home
mcporter config add org-ranking --command "$HOME/.local/bin/mcp-org-ranking" --scope home
mcporter config add talent-qualifier --command "$HOME/.local/bin/mcp-talent-qualifier" --scope home
mcporter config add talent-batch --command "$HOME/.local/bin/mcp-talent-batch" --scope home
```

如果要启用企业条件，请复制并填充 `examples/fortune_global_500.example.json`，仅使用你
有权使用且逐条保留来源的榜单数据，然后在启动 MCP 的环境中设置
`TALENT_REACH_FORTUNE_DATA`。完整 QS 快照同理通过 `TALENT_REACH_QS_DATA` 接入。

### LinkedIn 出现 `Connection closed`

LinkedIn MCP 由本机单独安装并由脚本从 `PATH` 或 `LINKEDIN_MCP_BIN` 查找；配置、锁文件和日志放进
可写的项目目录。如果 macOS 权限仍阻止 Chrome 的
Crashpad 或 `/bin/ps`，请在普通 macOS Terminal 中运行浏览器服务：

```bash
# 首次或会话失效时，在专用 Chrome 窗口里登录 LinkedIn
./scripts/linkedin-login.sh

# 登录成功后启动本机服务；使用期间保持此 Terminal 窗口打开
./scripts/linkedin-serve.sh
```

然后另开一个 Terminal，把项目配置切换到回环地址并验证：

```bash
./scripts/linkedin-use-local-service.sh
```

服务只监听 `127.0.0.1:8765`，不会暴露到局域网。专用浏览器资料位于
`work/linkedin-mcp-session/`，包含登录状态，权限设置为仅当前用户可读写；不要提交到 Git
或复制到共享目录。

验收命令：

```bash
talent-reach-doctor
mcporter list aboutme --json
mcporter call aboutme.read_aboutme_profile handle_or_url=Yassir.Elrayah
mcporter call github-public.read_github_profile username=abhimat
mcporter call personal-site.read_personal_site url=https://abhimat.net/
mcporter call org-ranking.get_qs_university_rank name="UC Berkeley" edition=2027
mcporter call talent-batch.talent_batch_doctor
```

开发测试：

```bash
uv sync --extra test
uv run pytest

# 无需 pytest 的离线核心回归
PYTHONPATH=src /path/to/python tests/test_offline_unittest.py
```

## 明确边界

- 仅处理公开数据或用户已授权浏览器能正常看到的数据。
- 不绕过登录、验证码、Cloudflare、付费墙或招聘者权限。
- 不读取 Git commit 邮箱，不猜公司邮箱，不做 SMTP 探测。
- 不依据姓名、照片、语言、学校或地点推断国籍等敏感属性；输出固定注明
  `nationality: not_inferred`。
- 个人网站抓取限制为最多 8 页，默认 5 页；只追踪同域且明确标注的 About、Contact、
  Bio、CV、Resume 页面。禁止从人物详情页退回人员列表、分页、全站 Contact、Staff 或
  Team 页面。公开 PDF 最大 5 MB、最多读取 20 页。
- 搜索结果只是候选发现，不等于身份确认；联系人数据只从已确认的资料合并。

## 渠道能力的现实判断

- **GitHub**：适合公开项目、技术栈、机构和用户主动公开的邮箱；不是隐藏邮箱来源。
- **Stack Overflow**：适合技术声誉与标签；公共 API 不提供私人邮箱。
- **About.me / 个人网站**：最可能出现本人主动公开的联系方式。
- **Wellfound**：适合履历与创业公司经历；招聘者专属联系人不可绕过。
- **Quora**：适合专业主题和活动佐证，通常不应视为邮箱补全渠道。

因此，这套工具能提高公开邮箱的覆盖率和人物身份的可验证性，但不能保证每位候选人
都有邮箱，也不会把无法确认的跨平台账号强行合并。
