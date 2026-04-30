# 浏览器自动化脚本研究

本文记录当前 AutoTeam 里 Playwright / Chromium 相关脚本能做什么、由哪些入口触发、适合复用哪些部分，以及开发新脚本时需要避开的限制。

## 事实来源

- `src/autoteam/config.py` (`get_playwright_launch_options`): 统一的 Chromium 启动参数。
- `src/autoteam/chatgpt_api.py` (`ChatGPTTeamAPI`): ChatGPT Team 管理员会话、Team 内部接口调用、管理员登录。
- `src/autoteam/codex_auth.py`: Codex OAuth 登录、主号 Codex 登录、token 交换、额度查询。
- `src/autoteam/invite.py`: 邀请链接注册流程。
- `src/autoteam/manager.py`: CLI 任务编排、直接注册、复用旧账号、轮转、补位、清理。
- `src/autoteam/manual_account.py`: 手动 OAuth 链接、localhost 回调和手动粘贴回调。
- `src/autoteam/api.py`: Web API、后台任务、Playwright 专用线程、自动巡检。
- `src/autoteam/account_ops.py`: Team 成员和邀请状态读取，成员 / 邀请删除。

## 浏览器运行方式

所有主要浏览器流程都使用 Playwright 的同步 API。Chromium 启动参数来自 `src/autoteam/config.py` (`get_playwright_launch_options`)。

当前固定参数：

- `headless=False`，因此会弹出可见浏览器窗口。
- Chromium 参数包含 `--disable-blink-features=AutomationControlled` 和 `--no-sandbox`。
- 支持 `PLAYWRIGHT_PROXY_URL`、`PLAYWRIGHT_PROXY_SERVER`、`PLAYWRIGHT_PROXY_USERNAME`、`PLAYWRIGHT_PROXY_PASSWORD`、`PLAYWRIGHT_PROXY_BYPASS`。
- 浏览器上下文常用 `1280x800` viewport 和固定 Windows Chrome User-Agent。
- 多数流程会把截图写入 `screenshots/`，用于定位页面变化或失败点。

API 模式下，Playwright 操作被放到 `src/autoteam/api.py` (`_PlaywrightExecutor`) 的专用线程执行，避免跨线程调用 Playwright 对象。全局 `_playwright_lock` 限制同一时间只跑一个浏览器相关任务。若已有浏览器任务，新的相关请求通常会返回 `409`。

## 核心浏览器对象

`src/autoteam/chatgpt_api.py` 的 `ChatGPTTeamAPI` 是 Team 管理能力的核心。

它负责：

- 启动 Chromium，创建 browser / context / page。
- 访问 `https://chatgpt.com/` 并等待 Cloudflare 页面结束。
- 注入管理员 `session_token`。
- 从 `/api/auth/session`、`bearer_token` 文件或 localStorage 获取 access token。
- 根据保存的 `account_id` 和 `workspace_name` 进入 Team workspace。
- 在页面上下文中发起 `fetch`，调用 ChatGPT 内部接口。

`_api_fetch` 会在页面里请求 `https://chatgpt.com{path}`，并带上：

- `Content-Type: application/json`
- `chatgpt-account-id`
- `oai-device-id`
- `oai-language`
- `authorization: Bearer ...`，前提是拿到了 access token。

这说明当前脚本不是纯 HTTP 客户端。它依赖浏览器先拿到 ChatGPT 站点的 cookie、页面环境和 token，再在页面上下文里调用内部接口。

## 现在能做的事

### 1. 管理员登录

入口：

- CLI: `uv run autoteam admin-login`
- API: `POST /api/admin/login/start`
- API 后续步骤：`/api/admin/login/password`、`/api/admin/login/code`、`/api/admin/login/workspace`
- API 手动导入 session: `POST /api/admin/login/session`

能力：

- 打开 `chatgpt.com`，进入登录页。
- 识别邮箱、密码、邮箱验证码、workspace 选择、已完成、错误状态。
- 自动填写邮箱。
- 接收用户提交的密码或验证码。
- 检测多个 workspace，并返回可选项。
- 选择指定 workspace。
- 登录完成后保存管理员邮箱、session token、workspace ID、workspace 名称。
- 也可以直接导入已有 `session_token`，再用浏览器验证并补齐 workspace 信息。

关键代码：

- `src/autoteam/chatgpt_api.py` (`begin_login`, `submit_login_password`, `submit_login_code`, `select_workspace_option`, `complete_admin_login`)
- `src/autoteam/manager.py` (`cmd_admin_login`, `cmd_admin_session`)
- `src/autoteam/api.py` (`post_admin_login_start`, `post_admin_login_session`)

### 2. 调用 ChatGPT Team 内部接口

入口：

- CLI: `status`、`rotate`、`fill`、`cleanup`、`add`
- API: `/api/team/members`、`/api/team/members/remove`、`/api/tasks/*`
- 自动巡检线程

能力：

- 读取 Team 成员列表。
- 读取邀请列表。
- 发送 Team 邀请。
- 删除 Team 成员。
- 取消 Team 邀请。
- 查询 Team 实际人数。
- 将远端 Team 成员状态同步到本地 `accounts.json`。
- 删除账号时，同时清理 Team 成员 / 邀请、本地 auth 文件、远端同步目标、邮箱提供者账号。

关键代码：

- `src/autoteam/chatgpt_api.py` (`invite_member`, `list_invites`, `_api_fetch`)
- `src/autoteam/account_ops.py` (`fetch_team_state`, `delete_managed_account`)
- `src/autoteam/manager.py` (`sync_account_states`, `remove_from_team`, `get_team_member_count`, `cmd_cleanup`)
- `src/autoteam/api.py` (`get_team_members`, `post_team_member_remove`)

### 3. 自动注册新账号

当前有两条注册路径。

第一条是邀请链接注册，主要在 `src/autoteam/invite.py`：

- 创建临时邮箱。
- 用管理员会话发送 Team 邀请。
- 等待邀请邮件。
- 提取邀请链接。
- 打开邀请链接。
- 点击注册 / 创建账号。
- 填邮箱。
- 设置随机密码。
- 读取邮箱验证码。
- 填验证码。
- 填 name 和生日 / 年龄。
- 接受条款或加入 workspace。
- 用页面 URL 和页面文本判断是否完成。

第二条是直接注册，主要在 `src/autoteam/manager.py`：

- 创建临时邮箱和随机密码。
- 打开 `https://chatgpt.com/auth/login`。
- 处理多种登录 / 注册页按钮变体。
- 检测邮箱、密码、验证码、about-you、完成、Google 跳转等状态。
- 填邮箱、密码、验证码。
- 处理生日字段，支持 spinbutton 日期字段和普通年龄字段。
- 最多尝试 3 次。
- 若远端确认该邮箱已经在 Team 中，也视为注册完成。

目前 `create_new_account` 优先走直接注册模式。直接注册依赖 ChatGPT Team 已启用 Verified Domains 和自动加入 Team 的设置。

关键代码：

- `src/autoteam/invite.py` (`register_with_invite`, `run`)
- `src/autoteam/manager.py` (`_register_direct_once`, `create_account_direct`, `create_new_account`)

### 4. Codex OAuth 登录和认证文件保存

入口：

- 新账号注册完成后自动调用。
- 旧账号复用时自动调用。
- CLI: `manual-add`
- API: `/api/manual-account/start`、`/api/manual-account/callback`
- 主号 Codex: `main-codex-sync` 或 Web 面板里的主号 Codex 操作。

能力：

- 生成 PKCE `code_verifier` / `code_challenge`。
- 生成 OpenAI OAuth URL。
- 使用 `http://localhost:1455/auth/callback` 作为 redirect URI。
- 捕获 request / response / 当前 URL 中的 OAuth callback。
- 用 authorization code 调 OpenAI token endpoint。
- 从 `id_token` 解析邮箱、ChatGPT account ID、plan type。
- 保存 OAuth RT auth 文件。
- 同一邮箱只保留一份 `codex-{email}-{plan_type}-{hash}-oauth.json`。
- 主号保存为 `codex-main-{account_id}.json`，不进入账号池。
- 查询 Codex 额度 `/backend-api/wham/usage`。
- 用 refresh token 刷新 access token。

全自动账号 OAuth (`login_codex_via_browser`) 会：

- 先登录 ChatGPT 并尽量选择 Team workspace。
- 再打开 Codex OAuth URL。
- 填邮箱、密码、验证码。
- 处理 about-you 页面。
- 处理 workspace 选择、组织选择、授权按钮。
- 捕获 callback code 并交换 token。

主号 Codex OAuth (`SessionCodexAuthFlow`) 会：

- 复用管理员 session。
- 在 `auth.openai.com` 注入 session cookie、`_account` 和 `oai-did`。
- 打开 Codex OAuth URL。
- 尝试自动填写邮箱。
- 遇到密码页时优先切换到一次性验证码入口。
- 等待用户提交验证码或密码。
- 完成后保存主号 auth 文件，或同步到已启用远端。

手动 OAuth (`ManualAccountFlow`) 不启动 Chromium。它只负责生成 OAuth 链接、启动本地回调服务、接收或解析回调 URL、交换 token、保存 auth 文件，并按 plan / 额度结果更新账号状态。

关键代码：

- `src/autoteam/codex_auth.py` (`_build_auth_url`, `_exchange_auth_code`, `login_codex_via_browser`, `SessionCodexAuthFlow`, `MainCodexLoginFlow`, `MainCodexSyncFlow`, `save_auth_file`, `save_main_auth_file`, `check_codex_quota`, `refresh_access_token`)
- `src/autoteam/manual_account.py` (`ManualAccountFlow`)
- `src/autoteam/manager.py` (`reinvite_account`, `cmd_manual_add`, `cmd_main_codex_sync`)

### 5. 账号轮转、补位和清理

入口：

- CLI: `rotate`、`fill`、`cleanup`、`check`、`add`
- API: `/api/tasks/rotate`、`/api/tasks/fill`、`/api/tasks/cleanup`、`/api/tasks/check`、`/api/tasks/add`
- 自动巡检触发的 `auto-rotate` 或 `auto-cleanup`

能力：

- 同步 Team 实际状态到本地。
- 检查 active 账号 Codex 额度。
- refresh token 失效时尝试刷新。
- 将额度不足账号标记为 `exhausted`。
- 从 Team 移出 exhausted 账号并改为 `standby`。
- 优先复用 standby 账号，复用前检查额度是否恢复。
- 复用旧账号时重新跑 Codex OAuth，只有拿到 `plan_type=team` 才恢复为 active。
- 空缺仍未补满时创建新账号。
- Team 超员时只清理本地管理的账号，避免误删外部成员。
- 任务结束后同步到已启用远端。

关键代码：

- `src/autoteam/manager.py` (`cmd_check`, `cmd_rotate`, `cmd_fill`, `cmd_cleanup`, `reinvite_account`, `create_new_account`)
- `src/autoteam/api.py` (`post_check`, `post_rotate`, `post_fill`, `post_cleanup`, `post_add`)

### 6. Web 面板触发浏览器

Web 面板不是只读页面。以下操作会或可能会启动 Chromium：

- 进入 Team 成员页：请求 `/api/team/members`，会读取 Team 成员和邀请。
- 移除 Team 成员：请求 `/api/team/members/remove`。
- 管理员登录：`/api/admin/login/*`。
- 主号 Codex 登录 / 同步：`/api/main-codex/*`。
- 账号池操作：`/api/tasks/check|rotate|add|fill|cleanup`。
- 同步账号：`/api/sync/accounts` 会调用 `sync_account_states`。

如果管理员 session 已过期，这些请求仍会先启动浏览器并注入旧 session，然后 Team 内部接口返回 `401/403`，最终报“请重新完成管理员登录”。

### 7. 自动巡检为什么会启动浏览器

API 启动后会在 startup 事件中启动后台巡检线程。

巡检每轮会：

- 等待 `AUTO_CHECK_INTERVAL` 秒，默认 300 秒。
- 读取 active 账号 auth 文件。
- 用 `check_codex_quota` 查询额度。
- 如果低额度账号数量不足以直接触发轮转，就调用 `_auto_check_team_member_count` 查询 Team 实际人数。
- `_auto_check_team_member_count` 会创建 `ChatGPTTeamAPI`、调用 `start()`，这一步会启动 Chromium。
- 如果 Team 人数不足，触发 `auto-rotate`。
- 如果 Team 人数超过目标，触发 `auto-cleanup`。

所以即使没有人在面板里点按钮，API 模式下也可能按巡检间隔启动浏览器。当前没有 `AUTO_CHECK_ENABLED` 之类的总开关，只能通过调大 `AUTO_CHECK_INTERVAL` 或改代码避免。

关键代码：

- `src/autoteam/api.py` (`_start_auto_check`, `_auto_check_loop`, `_auto_check_team_member_count`)
- `src/autoteam/config.py` (`AUTO_CHECK_INTERVAL`, `AUTO_CHECK_THRESHOLD`, `AUTO_CHECK_MIN_LOW`)

## 已有脚本的可复用点

开发新脚本时，优先复用以下部分：

- 浏览器启动配置：`src/autoteam/config.py` (`get_playwright_launch_options`)
- ChatGPT 管理员 session 启动：`src/autoteam/chatgpt_api.py` (`ChatGPTTeamAPI.start_with_session`)
- 页面内请求 ChatGPT API：`src/autoteam/chatgpt_api.py` (`_api_fetch`)
- Team 成员 / 邀请读取：`src/autoteam/account_ops.py` (`fetch_team_state`)
- Codex OAuth URL 和 token 交换：`src/autoteam/codex_auth.py` (`_build_auth_url`, `_exchange_auth_code`)
- auth 文件写入：`src/autoteam/codex_auth.py` (`save_auth_file`, `save_main_auth_file`)
- 额度查询：`src/autoteam/codex_auth.py` (`check_codex_quota`)
- 手动 OAuth 回调模式：`src/autoteam/manual_account.py` (`ManualAccountFlow`)
- API 内单浏览器任务互斥：`src/autoteam/api.py` (`_playwright_lock`, `_PlaywrightExecutor`)

建议新脚本不要重新实现 OAuth token 交换、auth 文件命名、Team 内部接口头部、额度查询这些部分。它们已经散落在现有模块里，但行为相对明确。

## 当前限制

- 浏览器显示方式由 `PLAYWRIGHT_BROWSER_MODE` 控制；`hidden` 和 `embedded` 当前都不会弹出独立窗口。
- API 模式没有关闭自动巡检的配置总开关。
- 自动巡检的目标人数写死为 `5`，不是从页面或 `.env` 读取。
- 大量页面操作依赖中英文按钮文字、URL 片段和输入框 selector，OpenAI 页面变化会直接影响结果。
- ChatGPT Team 内部接口不是公开稳定 API，字段名已有多种兼容写法。
- `session_token` 失效时，脚本会先启动浏览器再在内部接口处失败。
- 全自动 Codex OAuth 依赖邮箱服务能拿到新的验证码邮件。
- Playwright 同步 API 对线程敏感，所以 API 模式必须走专用线程执行器。
- 同一时间只支持一个浏览器任务。
- 直接注册依赖 Verified Domains 自动加入 Team；没有这个前提时应使用邀请链接注册或手动流程。
- 手动 OAuth 流程本身不控制浏览器，它只生成链接和处理 callback。
- OAuth callback 端口固定为 `1455`，端口被占用时会退到手动粘贴。
- `screenshots/` 可能留下登录和注册过程截图，排查后应注意清理敏感画面。

## 新脚本开发建议

建议把新脚本分成四层：

1. 浏览器运行层：只负责启动、代理、viewport、User-Agent、关闭资源。
2. ChatGPT 会话层：只负责 session 注入、access token 获取、workspace 选择。
3. 业务动作层：读取成员、邀请、移除、注册、OAuth、额度查询分别做成独立函数。
4. 入口层：CLI / API / 后台任务只负责参数、状态和互斥，不直接写页面细节。

这样可以让新脚本在保留现有能力的同时，减少页面变动时的修改范围。

优先做的改造：

- 给后台巡检增加启用开关，避免启动 API 后定时打开 Chromium。
- 将 `target_seats=5` 做成配置项。
- 将 Team 成员读取改成先尝试已有 token 的 HTTP 请求，失败再启动浏览器刷新会话。
- 把注册、Codex OAuth、Team API 调用拆成清晰的类，保留统一截图和日志命名。
- 为每条浏览器流程增加“为什么启动浏览器”的日志字段，例如 `reason=team_members`、`reason=auto_check`、`reason=codex_oauth`。

## 触发入口速查

| 入口 | 是否启动浏览器 | 主要用途 |
|------|----------------|----------|
| `uv run autoteam api` | 可能 | 启动自动巡检；巡检到点后可能查 Team 人数 |
| Web「Team 成员」 | 是 | 读取成员和邀请 |
| Web「管理员登录」 | 是 | 登录管理员并保存 session |
| Web「主号 Codex」 | 是 | 主号 Codex OAuth |
| Web「OAuth 登录」 | 否 | 生成链接和接收 / 粘贴 callback |
| Web「账号池操作」 | 是 | 检查、轮转、添加、补位、清理 |
| `uv run autoteam status` | 可能 | 同步 Team 状态时会启动浏览器 |
| `uv run autoteam rotate` | 是 | 轮转账号池 |
| `uv run autoteam fill` | 是 | 补 Team 成员 |
| `uv run autoteam cleanup` | 是 | 清理本地管理的多余成员 |
| `uv run autoteam manual-add` | 否 | 手动 Codex OAuth 导入 |
| `uv run autoteam admin-login` | 是 | 管理员登录 |
| `uv run autoteam main-codex-sync` | 是或否 | 有本地主号 auth 文件时可直接同步，否则启动 OAuth |

## 对“为什么一直自动启动浏览器”的结论

当前配置下，浏览器自动出现通常来自两类触发：

1. 用户打开或刷新了会调用 Team 内部接口的页面，例如 Web「Team 成员」。这会请求 `/api/team/members`，后端必须启动 `ChatGPTTeamAPI`。
2. API 模式后台巡检到点。默认每 5 分钟，巡检在低额度账号不足以触发轮转时，会查 Team 实际人数，这一步会启动 Chromium。

如果管理员 session 已失效，浏览器仍会被启动，因为脚本需要先进 ChatGPT 页面注入 session、取 token，再调用内部接口。随后内部接口返回 `401/403`，日志会提示重新完成管理员登录。
