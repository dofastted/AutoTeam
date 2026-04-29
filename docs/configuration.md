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
| `CPA_URL` | CPA（CLIProxyAPI）地址 | 启用 CPA 时必填（默认 `http://127.0.0.1:8317`） |
| `CPA_KEY` | CPA 管理密钥 | 启用 CPA 时必填 |
| `SYNC_TARGET_SUB2API` | 是否启用 Sub2API 同步（`true/false`） | 否 |
| `SUB2API_URL` | Sub2API 地址 | 启用 Sub2API 时必填 |
| `SUB2API_EMAIL` | Sub2API 管理员邮箱 | 启用 Sub2API 时必填 |
| `SUB2API_PASSWORD` | Sub2API 管理员密码 | 启用 Sub2API 时必填 |
| `SUB2API_GROUP` | Sub2API 分组名或分组 ID，多个用逗号分隔 | 启用 Sub2API 且希望自动加入分组时填写 |
| `API_KEY` | Web 面板 / API 鉴权密钥 | 启动时必填（首次启动可自动生成） |
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
- 代理配置属于低频项，默认折叠

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
- 更新时会保留账号原本手动绑定的其他分组，只替换 AutoTeam 自己管理的分组绑定

## Playwright 代理

AutoTeam 的浏览器流量（ChatGPT 登录、邀请接受、Codex OAuth 等）现在支持单独配置代理。

推荐优先使用一个环境变量：

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

兼容 CLIProxyAPI，文件名格式：

```text
codex-{email}-{plan_type}-{hash}.json
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
  "last_refresh": "2026-04-10T10:00:00Z"
}
```

反向同步 (`pull-cpa`) 时，CPA 中下载回来的文件也会被重新整理成这个命名规范。

## Team 补位批次

`TEAM_TARGET_SEATS` 是 Team 总人数目标，默认 `999`。`FILL_BATCH_SIZE` 是「补满成员」一次最多新增的账号数，默认 `10`。

Web 面板点击「补满成员」时，如果不手动传目标人数，后端只会执行一批：当前 Team 人数加上 `FILL_BATCH_SIZE`，且不超过 `TEAM_TARGET_SEATS`。如果通过 CLI 或 API 明确传入较大的目标，执行过程仍会按 `FILL_BATCH_SIZE` 分批记录日志，并在每批结束后上传 CPA 认证文件。

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
- `auths/codex-{email}-{plan}-{hash}.json` 是轮转账号
- 从 CPA 反向同步时会自动清理同账号重复文件

## 启动验证

保存运行配置时会按当前已启用目标验证连通性：

- CloudMail：登录 → 创建测试邮箱 → 删除
- CPA：获取认证文件列表
- Sub2API：管理员登录 → 获取 OpenAI OAuth 账号列表 → 校验 `SUB2API_GROUP`（如已填写）

验证失败会提示具体哪个环节有问题，保存会被拒绝。
