# HTTP API 文档

启动后访问 `http://localhost:8787/docs` 查看 Swagger 交互式文档。

所有 `/api/*` 端点需要：

```text
Authorization: Bearer <API_KEY>
```

但以下接口例外：
- `/api/auth/check`
- `/api/setup/status`
- `/api/setup/save`

## 即时返回接口

这些接口直接返回结果，不创建后台任务。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/auth/check` | 验证 API Key |
| GET | `/api/setup/status` | 检查配置是否完整 |
| POST | `/api/setup/save` | 保存初始配置 |
| GET | `/api/config/runtime` | 获取运行配置字段 |
| PUT | `/api/config/runtime` | 保存运行配置 |
| GET | `/api/config/source` | 读取 `.env` 源文件 |
| PUT | `/api/config/source` | 保存 `.env` 源文件 |
| GET | `/api/proxy-nodes/status` | 查看代理节点接口状态、当前节点和最近刷新结果 |
| POST | `/api/proxy-nodes/refresh` | 调用代理节点接口刷新节点，并按配置写入出口代理池 |
| GET | `/api/status` | 账号状态 + 实时额度 |
| GET | `/api/accounts` | 所有账号列表 |
| GET | `/api/accounts/active` | 活跃账号 |
| GET | `/api/accounts/standby` | 待命账号 |
| GET | `/api/team/members` | Team 全部成员（含外部成员与邀请） |
| POST | `/api/team/members/remove` | 移出成员 / 取消邀请 |
| GET | `/api/logs` | 最近日志（支持 `?limit=100&since=0`） |
| GET | `/api/cpa/files` | CPA 认证文件列表 |
| GET | `/api/cpa-batch/runs` | 批量 CPA JSON 运行记录 |
| GET | `/api/cpa-batch/runs/{run_id}` | 单次批量 CPA JSON 详情 |
| POST | `/api/cpa-batch/runs/{run_id}/pause` | 请求批量 CPA JSON 任务暂停 |
| POST | `/api/cpa-batch/runs/{run_id}/resume` | 从已有批量 CPA JSON 记录继续执行 |
| GET | `/api/config/auto-check` | 巡检配置 |
| PUT | `/api/config/auto-check` | 修改巡检配置（运行时生效） |
| POST | `/api/sync` | 上传 active 账号的本地 OAuth RT 文件到已启用远端 |
| POST | `/api/sync/cpa` | 只上传 active 账号的本地 OAuth RT 文件到 CPA |
| POST | `/api/sync/sub2api` | 只上传 active 账号的本地 OAuth RT 文件到 Sub2API |
| POST | `/api/sync/from-cpa` | 从 CPA 反向导入认证文件到本地，用于恢复和去重 |
| POST | `/api/sync/accounts` | 从 Team / auths 对账到本地账号池 |
| POST | `/api/sync/main-codex/saved` | 只推送本地已有主号 Codex 凭证 |
| POST | `/api/accounts/{email}/cpa-auth` | 为单个 active 席位账号完成 Codex 认证并上传到 CPA |
| POST | `/api/accounts/login` | 对单个账号执行本地 Codex OAuth 登录验证，保存 OAuth RT 文件，不自动同步远端 |
| POST | `/api/accounts/migrate-auth-metadata` | dry-run 或写入旧账号 `rt_auth_file` 元数据，只迁移有效 OAuth RT 文件 |
| POST | `/api/accounts/{email}/kick` | 将 active 账号移出 Team |
| POST | `/api/accounts/check-deactivated-mail` | 检查邮箱是否有 `deactivated` 邮件，命中后标记失效并释放席位 |
| DELETE | `/api/accounts/{email}` | 删除本地管理账号及其资源 |

### Team 成员移除

`POST /api/team/members/remove`

请求体：

```json
{
  "email": "user@example.com",
  "user_id": "123",
  "type": "member"
}
```

- `type = member`：从 Team 中移出
- `type = invite`：取消邀请

### deactivated 邮件检查

`POST /api/accounts/check-deactivated-mail`

请求体：

```json
{
  "keyword": "deactivated",
  "size": 30,
  "directory": null,
  "apply": false,
  "release_team": true,
  "dispose_mailbox": true
}
```

- `apply = false` 时只做 dry-run。
- `directory` 可传 `auths/unusable/account_deactivated`，这时直接从目录中的 `codex-*.json` 读取邮箱清单。
- `release_team = true` 时，命中且仍在 Team 中的账号会尝试移出 Team。
- `dispose_mailbox = true` 时，会尝试调用对应邮箱 provider 的删除接口。
- 命中后本地账号会写入 `status=unavailable`、`sync_disabled=true`、`unavailable_reason=account_deactivated`。

### 单账号 OAuth 登录验证

`POST /api/accounts/login`

请求体：

```json
{
  "email": "user@example.com",
  "force": false
}
```

- 默认拒绝已售出账号和 `sync_disabled=true` 的账号。
- `force = true` 仅用于排查已标记失效账号，会重新执行本地 Codex OAuth 登录验证。
- 登录成功后写入 `rt_auth_file`，兼容保留 `auth_file`，并保留已有 `session_auth_file`。
- 该接口不上传 CPA / Sub2API，也不释放 Team 席位。
- OAuth 页面返回 `account_deactivated` 时，会把本地账号写为 `status=unavailable`、`sync_disabled=true`、`unavailable_reason=account_deactivated`。

### 单账号 CPA 认证

`POST /api/accounts/{email}/cpa-auth`

- 只允许账号池里的 active 席位账号。
- 本地已有 OAuth RT 文件时直接上传 CPA。
- 只有 session 备份或缺少 OAuth RT 文件时，才执行 Codex OAuth 生成 RT 文件。
- `session_auth_file` 不会被上传到 CPA。
- 成功后写入 `rt_auth_file`、`cpa_uploaded_at`，并保留已有 `session_auth_file`。

### 账号认证元数据迁移

`POST /api/accounts/migrate-auth-metadata`

请求体：

```json
{
  "apply": false
}
```

- `apply = false` 时只返回报告。
- `apply = true` 时，只把有效旧 OAuth `auth_file` 补写到 `rt_auth_file`。
- `credential_source=chatgpt_session` 或缺少 `refresh_token` 的文件不会被迁移。
- 该接口只改 `accounts.json` 元数据，不修改 token 文件内容。

## 后台任务接口

这些接口返回 `202 Accepted + task_id`。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tasks/rotate` | 智能轮转 `{"target": 5}` |
| POST | `/api/tasks/check` | 检查额度 |
| POST | `/api/tasks/add` | 自动注册并添加新账号 |
| POST | `/api/tasks/fill` | 补满成员；未传 `target` 时按 `FILL_BATCH_SIZE` 执行一批 |
| POST | `/api/tasks/cpa-batch` | 新做 team 账号 CPA JSON；默认 100 个，支持 `{"join_mode": "direct", "target": 1, "batch_size": 1}` |
| POST | `/api/tasks/cleanup` | 清理成员 `{"max_seats": null}` |
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/tasks/{task_id}` | 任务详情 |

> 同一时间只允许一个 Playwright 操作；如果有任务执行中，新请求可能返回 `409 Conflict`。

## 管理员登录

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/status` | 管理员状态 |
| POST | `/api/admin/login/start` | 开始登录 `{"email": "admin@example.com"}` |
| POST | `/api/admin/login/session` | 手动导入 session_token `{"email": "admin@example.com", "session_token": "..."}` |
| POST | `/api/admin/login/password` | 提交密码 `{"password": "..."}` |
| POST | `/api/admin/login/code` | 提交验证码 `{"code": "123456"}` |
| POST | `/api/admin/login/workspace` | 选择组织 `{"option_id": "0"}` |
| POST | `/api/admin/login/cancel` | 取消登录 |
| POST | `/api/admin/logout` | 清除登录态 |

## 主号 Codex 同步

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/main-codex/status` | 同步状态 |
| POST | `/api/main-codex/start` | 开始登录并同步到已启用远端 |
| POST | `/api/main-codex/password` | 提交密码 |
| POST | `/api/main-codex/code` | 提交验证码 |
| POST | `/api/main-codex/cancel` | 取消同步 |

## 手动 OAuth 导入

后端先生成 Codex OAuth 链接，并尝试在 `localhost:1455` 自动接收回调；如果自动回调不可用，也可以手动提交回调 URL。

手动 OAuth 完成后只保存本地认证文件并更新账号状态，不自动上传 CPA / Sub2API。需要远端同步时，继续调用同步中心对应接口。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/manual-account/status` | 当前手动 OAuth 状态 |
| POST | `/api/manual-account/start` | 开始流程，返回 `auth_url` 与状态信息 |
| POST | `/api/manual-account/callback` | 提交回调 URL |
| POST | `/api/manual-account/cancel` | 取消流程 |

### `/api/manual-account/status` 关键字段

| 字段 | 说明 |
|------|------|
| `status` | `idle / pending_callback / completed / error` |
| `auth_url` | 当前 OAuth 链接 |
| `callback_received` | 是否已收到回调 |
| `callback_source` | `auto` 或 `manual` |
| `auto_callback_available` | 本地自动回调服务是否启动成功 |
| `account` | 完成后导入的账号信息 |

## 调用示例

```bash
# 查看账号状态
curl -H "Authorization: Bearer YOUR_KEY" \
  http://localhost:8787/api/status

# 触发轮转
curl -X POST -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"target": 5}' \
  http://localhost:8787/api/tasks/rotate

# 从 CPA 拉取认证文件到本地
curl -X POST -H "Authorization: Bearer YOUR_KEY" \
  http://localhost:8787/api/sync/from-cpa

# 生成手动 OAuth 链接
curl -X POST -H "Authorization: Bearer YOUR_KEY" \
  http://localhost:8787/api/manual-account/start
```
