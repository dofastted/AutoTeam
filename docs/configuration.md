# 配置说明

## `.env` 配置项

首次运行任何命令时会自动进入配置向导。现在启动阶段只强制要求 `API_KEY`，CloudMail、CPA / Sub2API、代理等运行项也可以在登录后去配置面板补充。只有执行对应功能时，系统才会校验对应配置。也可以手动编辑：

```bash
cp .env.example .env
```

| 配置项 | 说明 | 何时需要 |
|--------|------|------|
| `MAIL_PROVIDER` | 邮箱服务提供者，可选 `mo_email`、`cloudmail`、`cloudflare_temp_email` | 账号池操作时必填 |
| `MO_EMAIL_BASE_URL` | Mo Email API 地址，默认 `https://mo.gymbro.cloud` | 使用 Mo Email 时必填 |
| `MO_EMAIL_API_KEY` | Mo Email API Key | 使用 Mo Email 时必填 |
| `MO_EMAIL_DOMAIN` | Mo Email 邮箱域名（如 `gymbro.cloud`） | 使用 Mo Email 时必填 |
| `MO_EMAIL_NAME_PREFIX` | Mo Email 邮箱名前缀（如 `abc`） | 使用 Mo Email 时必填 |
| `MO_EMAIL_START_INDEX` | Mo Email 起始序号 | 使用 Mo Email 时必填 |
| `MO_EMAIL_EXPIRY_TIME` | Mo Email 有效期毫秒数，可填 `3600000`、`86400000`、`604800000`、`0` | 使用 Mo Email 时必填 |
| `CLOUDMAIL_BASE_URL` | CloudMail API 地址 | 账号池操作时必填 |
| `CLOUDMAIL_EMAIL` | CloudMail 登录邮箱 | 账号池操作时必填 |
| `CLOUDMAIL_PASSWORD` | CloudMail 登录密码 | 账号池操作时必填 |
| `CLOUDMAIL_DOMAIN` | 临时邮箱域名（如 `@example.com`） | 账号池操作时必填 |
| `SYNC_TARGET_CPA` | 是否启用 CPA 同步（`true/false`） | 否 |
| `CPA_URL` | CPA（CLIProxyAPI）地址 | 启用 CPA 时必填（默认 `http://127.0.0.1:8317`）；可填管理页 `http://127.0.0.1:8317/management.html#/auth-files`，后端会归一化为 API 根地址 |
| `CPA_KEY` | CPA 管理密钥 | 启用 CPA 时必填 |
| `SYNC_TARGET_SUB2API` | 是否启用 Sub2API 同步（`true/false`） | 否 |
| `SUB2API_URL` | Sub2API 地址 | 启用 Sub2API 时必填 |
| `SUB2API_EMAIL` | Sub2API 管理员邮箱 | 启用 Sub2API 时必填 |
| `SUB2API_PASSWORD` | Sub2API 管理员密码 | 启用 Sub2API 时必填 |
| `SUB2API_GROUP` | Sub2API 分组名或分组 ID，多个用逗号分隔 | 启用 Sub2API 且希望自动加入分组时填写 |
| `API_KEY` | Web 面板 / API 鉴权密钥 | 启动时必填（首次启动可自动生成） |
| `PLAYWRIGHT_BROWSER_MODE` | 浏览器显示方式，可选 `hidden`、`visible`、`embedded` | 否（默认 `hidden`） |
| `PLAYWRIGHT_HEADLESS` | 旧版兼容项，`false` 等同 `PLAYWRIGHT_BROWSER_MODE=visible` | 否（默认 `true`） |
| `BROWSER_PARALLEL_WORKERS` | 账号补满、轮转和直注批量任务的并行窗口数，范围 `1..3` | 否（默认 `1`） |
| `OUTBOUND_PROXY_ENABLED` | 是否启用全局出口代理池 | 否（默认 `true`） |
| `OUTBOUND_PROXY_POOL` | 全局出口代理池，逗号或换行分隔，支持 `http`、`https`、`socks5`、`socks5h`、`direct`、`none` | 否（默认 `http://127.0.0.1:10808`） |
| `OUTBOUND_PROXY_BYPASS` | 出口代理绕过列表 | 否（默认 `localhost,127.0.0.1,::1`） |
| `OUTBOUND_PROXY_STRATEGY` | 出口代理选择策略 | 否（当前为 `task-sticky`） |
| `OUTBOUND_PROXY_FAILOVER` | 网络失败后是否尝试下一个代理 | 否（默认 `true`） |
| `PROXY_NODE_ENABLED` | 是否启用代理节点接口 | 否（默认 `false`） |
| `PROXY_NODE_PROVIDER` | 节点提供者，当前支持 `none` / `webshare` | 否（默认 `none`） |
| `PROXY_NODE_API_KEY` | 节点 API Key | 否 |
| `PROXY_NODE_BASE_URL` | 节点 API 地址 | 否（默认 Webshare API v2） |
| `PROXY_NODE_PROTOCOL` | 写入出口池的协议，支持 `http`、`socks5`、`socks5h` | 否（默认 `http`） |
| `PROXY_NODE_AUTO_REFRESH` | 自动化任务和巡检前是否轮询刷新节点 | 否（默认 `false`） |
| `PROXY_NODE_POLL_INTERVAL_SECONDS` | 等待新节点时的轮询间隔 | 否（默认 `5`） |
| `PROXY_NODE_POLL_TIMEOUT_SECONDS` | 等待新节点的超时秒数 | 否（默认 `120`） |
| `PLAYWRIGHT_PROXY_URL` | Playwright 浏览器代理 URL，如 `socks5://host:port` 或 `http://user:pass@host:port` | 否 |
| `PLAYWRIGHT_PROXY_BYPASS` | Playwright 代理绕过列表，如 `localhost,127.0.0.1` | 否 |
| `AUTO_CHECK_THRESHOLD` | 额度低于此百分比触发轮转 | 否（默认 `10`） |
| `AUTO_CHECK_INTERVAL` | 巡检间隔（秒） | 否（默认 `300`） |
| `AUTO_CHECK_MIN_LOW` | 至少几个账号低于阈值才触发 | 否（默认 `2`） |
| `TEAM_TARGET_SEATS` | Team 总人数目标 | 否（默认 `999`） |
| `FILL_BATCH_SIZE` | 「补满成员」每次最多新增账号数 | 否（默认 `10`） |

## 配置面板分区

登录 Web 面板后，配置面板已拆成独立分区：

- **CloudMail**
- **远端同步**
- **代理 / 高级**
- **安全 / 访问控制**
- **管理员 / 主号**
- **巡检设置**
- **源文件编辑**

其中：

- `API_KEY` 单独放在 **安全 / 访问控制**
- CPA / Sub2API 开关和连接信息放在 **远端同步**
- `.env` 原文编辑保留在 **源文件编辑**
- 浏览器显示方式、全局出口代理池和 Playwright 覆盖代理放在 **代理 / 高级**

## Sub2API 分组

如果希望同步到 Sub2API 的账号自动加入指定分组，可以设置：

```dotenv
SUB2API_GROUP=Team Pool
```

也可以填写分组 ID，或多个分组：

```dotenv
SUB2API_GROUP=12,Team Pool
```

说明：

- 支持 **分组名** 或 **分组 ID**
- 多个分组用英文逗号分隔
- 同步账号池账号时会自动带上这些分组
- 同步主号 Codex 到 Sub2API 时也会自动带上这些分组
- 找不到分组时，账号仍会推送到 Sub2API，并在返回结果的 `warnings` 中提示已跳过分组绑定
- 更新时会保留账号原本手动绑定的其他分组，只替换 AutoTeam 自己管理的分组绑定
- 账号 payload 按 `C:\Users\Administrator\Downloads\sub2api示列.json` 的 OpenAI OAuth 账号结构写入，包含默认模型映射、隐私模式和基础调度字段

## Playwright 浏览器运行

AutoTeam 的浏览器流量（ChatGPT 登录、邀请接受、Codex OAuth 等）默认不弹出窗口。账号补满、轮转和直注批量任务可通过 `BROWSER_PARALLEL_WORKERS` 开 1 到 3 个独立 Chromium；其他浏览器流程仍按单任务运行。推荐使用新配置：

```dotenv
PLAYWRIGHT_BROWSER_MODE=hidden
BROWSER_PARALLEL_WORKERS=1
```

可选值：

- `hidden`: 无头运行，不弹出窗口。
- `visible`: 显示独立浏览器窗口，适合临时观察页面。
- `embedded`: 当前按无头运行，预留给后续页面内嵌预览。

可见窗口启动时固定使用 `1280x800`，位置为屏幕左上角。

旧配置仍兼容：

```dotenv
PLAYWRIGHT_HEADLESS=false
```

当同时存在 `PLAYWRIGHT_BROWSER_MODE` 和 `PLAYWRIGHT_HEADLESS` 时，优先使用 `PLAYWRIGHT_BROWSER_MODE`。

如需复用内置 Chromium 的固定 profile，可设置：

```dotenv
PLAYWRIGHT_USER_DATA_DIR=/path/to/chromium-profile
```

该配置留空时沿用临时 profile。设置后，AutoTeam 会用持久化 profile 启动一个保活窗口；每次账号流程仍创建独立 Playwright context，任务结束时只关闭临时 context，不关闭保活窗口。若设置了 `PLAYWRIGHT_BROWSER_CDP_URL`，CDP 路径优先，`PLAYWRIGHT_USER_DATA_DIR` 不生效。

### 出口代理池

AutoTeam 后端访问 OpenAI/ChatGPT、邮箱服务、CPA、Sub2API 时会使用全局出口代理池。默认值是 Windows Clash：

```dotenv
OUTBOUND_PROXY_ENABLED=true
OUTBOUND_PROXY_POOL=http://127.0.0.1:10808
OUTBOUND_PROXY_BYPASS=localhost,127.0.0.1,::1
OUTBOUND_PROXY_STRATEGY=task-sticky
OUTBOUND_PROXY_FAILOVER=true
```

说明：

- 一次账号注册、OAuth、额度检查或同步任务内固定同一个代理。
- 连接超时、代理握手失败等网络错误会尝试下一个代理。
- HTTP 401/403、账号失效、CPA/Sub2API 鉴权失败不会切换代理。
- `OUTBOUND_PROXY_POOL` 支持逗号或换行分隔，支持 `http`、`https`、`socks5`、`socks5h`，也支持 `direct` / `none` 表示直连。
- `localhost`、`127.0.0.1`、`::1` 默认不走代理，避免影响 OAuth 本地回调和本地 API。
- 如果使用 `socks5`，当前 Python 环境需要安装 `requests[socks]`；否则请改用 HTTP 代理。

### 代理节点接口

AutoTeam 可从代理节点 API 获取最新节点，并写入 `OUTBOUND_PROXY_POOL`。当前迁移的是 `Gpt-Agreement-Payment` 中的 Webshare 节点逻辑：读取当前代理、触发 refresh、按间隔轮询到新 IP 后格式化为代理 URL。

```dotenv
PROXY_NODE_ENABLED=true
PROXY_NODE_PROVIDER=webshare
PROXY_NODE_API_KEY=your_webshare_api_key
PROXY_NODE_BASE_URL=https://proxy.webshare.io/api/v2
PROXY_NODE_PROTOCOL=http
PROXY_NODE_AUTO_REFRESH=false
PROXY_NODE_REFRESH_BEFORE_TASK=true
PROXY_NODE_POLL_INTERVAL_SECONDS=5
PROXY_NODE_POLL_TIMEOUT_SECONDS=120
PROXY_NODE_COUNTRY=US
PROXY_NODE_APPLY_TO_OUTBOUND_POOL=true
```

说明：

- 手动刷新接口是 `POST /api/proxy-nodes/refresh`。
- 状态接口是 `GET /api/proxy-nodes/status`。
- `PROXY_NODE_PROTOCOL=http` 会生成 `http://user:pass@host:port`；`socks5` / `socks5h` 会生成对应协议的 URL。
- `PROXY_NODE_AUTO_REFRESH=true` 时，API 后台任务开始前会先调用节点接口刷新，再用刷新后的代理进入任务固定上下文。
- 自动巡检线程也会在每轮检查前刷新节点；失败时只记录警告，本轮继续使用现有出口代理。

### Playwright 覆盖代理

`PLAYWRIGHT_PROXY_URL` 留空时，浏览器跟随后端出口代理池。如果只想让浏览器使用单独代理，可以设置：

```dotenv
PLAYWRIGHT_PROXY_URL=socks5://host.docker.internal:1080
PLAYWRIGHT_PROXY_BYPASS=localhost,127.0.0.1
```

如果代理需要认证，建议改用 HTTP 代理并直接写进 URL：

```dotenv
PLAYWRIGHT_PROXY_URL=http://username:password@host.docker.internal:1080
```

说明：

- `PLAYWRIGHT_PROXY_URL` 会被解析为 Playwright 所需的 `server` / `username` / `password` 字段
- Playwright / Chromium **不支持带认证的 socks5**，因此不要使用 `socks5://username:password@host:port`
- `PLAYWRIGHT_PROXY_BYPASS` 建议至少包含 `localhost,127.0.0.1`，避免本地回调或容器内本地服务误走代理

### 内联注释

`.env` 支持尾部内联注释，例如：

```env
AUTO_CHECK_INTERVAL=300  # 5 分钟
```

Windows / macOS 下也会按 UTF-8 正常读取。

### Mo Email

`MAIL_PROVIDER=mo_email` 时，系统会用 `MO_EMAIL_BASE_URL` 和 `MO_EMAIL_API_KEY` 调用 Mo Email API。`MO_EMAIL_DOMAIN` 可填写 `/api/config` 返回的任一域名。

自动创建邮箱时，系统会读取远端邮箱列表和本地账号记录，按 `MO_EMAIL_NAME_PREFIX` 查找已有最大序号，再加 1。例如已存在 `abc-1@gymbro.cloud`，下一个邮箱会是 `abc-2@gymbro.cloud`。

Mo Email 当前公开接口没有删除邮箱或删除邮件端点，所以删除账号时只会删除本地账号记录和远端同步目标中的认证文件，不会误报邮箱已从 Mo Email 删除。

### 邮件等待

`EMAIL_POLL_INTERVAL` 是刷新间隔，单位秒。`EMAIL_POLL_TIMEOUT` 是最多等待多久；设置为 `0` 时会一直刷新，直到收到目标邮件。

## 管理员登录态

首次启动后，在 Web 面板「配置面板 → 管理员 / 主号」或命令行完成主号登录：

```bash
uv run autoteam admin-login
uv run autoteam admin-login --email you@example.com
```

系统会自动保存到 `state.json`，包括：
- 邮箱
- session token
- workspace ID
- workspace 名称
- 密码（如果你走的是密码登录）

## 主号 Codex 同步

`main-codex-sync` 用于把管理员主号的 Codex 登录态单独同步到当前已启用远端（CPA / Sub2API）。

- **前置条件**：先完成 `admin-login`
- **结果文件**：`auths/codex-main-*.json`
- **作用范围**：主号专用，不进入轮转池

```bash
uv run autoteam main-codex-sync
```

## 认证文件格式

OAuth RT 文件兼容 CLIProxyAPI，文件名格式：

```text
codex-{email}-{plan_type}-{hash}-oauth.json
```

文件内容示例：

```json
{
  "type": "codex",
  "id_token": "eyJ...",
  "access_token": "eyJ...",
  "refresh_token": "rt_...",
  "account_id": "...",
  "email": "...",
  "expired": "2026-04-20T10:00:00Z",
  "last_refresh": "2026-04-10T10:00:00Z",
  "credential_source": "oauth"
}
```

直注批量流程会先保存 ChatGPT Web session 备份，文件名格式：

```text
codex-{email}-{plan_type}-{hash}-session.json
```

这类文件会带 `credential_source=chatgpt_session`，`access_token` 来自 ChatGPT Web session，`session_token` 用于保留注册完成后的登录凭证。它不包含可长期刷新的 OAuth `refresh_token`，不能上传到 CPA / Sub2API。

CPA / Sub2API 普通同步只上传本地 OAuth RT 文件。账号字段里 `rt_auth_file` 是主来源；旧 `auth_file` 只有内容确认含 `refresh_token` 且不是 ChatGPT session 时才作为兼容来源。

反向同步 (`pull-cpa`) 是恢复入口。CPA 中下载回来的文件会被重新整理成 OAuth 文件命名规范。

## Team 补位批次

`TEAM_TARGET_SEATS` 是 Team 总人数目标，默认 `999`。`FILL_BATCH_SIZE` 是「补满成员」一次最多新增的账号数，默认 `10`。`BROWSER_PARALLEL_WORKERS` 控制每批新号创建时同时开的独立浏览器数，最大为 `3`。

Web 面板点击「补满成员」时，如果不手动传目标人数，后端只会执行一批：当前 Team 人数加上 `FILL_BATCH_SIZE`，且不超过 `TEAM_TARGET_SEATS`。如果通过 CLI 或 API 明确传入较大的目标，执行过程仍会按 `FILL_BATCH_SIZE` 分批记录日志，并在每批结束后上传本地 OAuth RT 文件。

## 批量 CPA JSON

账号池操作页的「批量 CPA JSON」会每次新做 100 个可用 CPA JSON，并固定按 20 个账号为一组处理。页面可选择直注入席或邀请入席。

计入成功必须同时满足：
- 本地账号状态为 `active`
- Codex OAuth 返回或认证文件解析为 `plan_type=team`
- 额度检查返回 `ok`
- CPA 上传成功

运行记录保存到 `flow_runs.json`。该文件只用于本地查看进度和错误，不应提交。邮箱创建后会立即写入真实邮箱；服务重启时，未结束的批量记录会被标记为失败。

暂停按钮会写入暂停请求。当前账号阶段结束后，任务会停止继续创建新账号，并把运行记录标记为 `paused`。

## 本地数据文件

| 文件 / 目录 | 作用 |
|-------------|------|
| `.env` | 运行配置 |
| `accounts.json` | 本地账号池状态 |
| `flow_runs.json` | 批量 CPA JSON 运行记录 |
| `state.json` | 管理员登录态 |
| `auths/` | 轮转账号与主号的 Codex 认证文件 |
| `screenshots/` | 浏览器自动化调试截图 |

其中：
- `auths/codex-main-*.json` 是主号专用
- `auths/codex-{email}-{plan}-{hash}-oauth.json` 是轮转账号的 OAuth RT 文件
- `auths/codex-{email}-{plan}-{hash}-session.json` 是 ChatGPT Web session 备份，不能上传 CPA / Sub2API
- 从 CPA 反向同步时会自动清理同账号重复 OAuth 文件

## 启动验证

保存运行配置时会按当前已启用目标验证连通性：

- CloudMail：登录 → 创建测试邮箱 → 删除
- CPA：获取认证文件列表
- Sub2API：管理员登录 → 获取 OpenAI OAuth 账号列表 → 校验 `SUB2API_GROUP`（如已填写）

验证失败会提示具体哪个环节有问题，保存会被拒绝。
