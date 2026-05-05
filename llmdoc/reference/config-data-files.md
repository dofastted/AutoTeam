# 配置与数据文件

## 配置来源

`src/autoteam/config.py`: 启动时从项目根 `.env` 读取环境变量，再导出常量。

`src/autoteam/setup_wizard.py`: 首次配置和 `.env` 写入。

`src/autoteam/api.py`: Web 配置接口，支持读取和写入运行配置。

## 关键配置

- `API_KEY`: Web 面板和 API 鉴权。启动阶段唯一强制项。
- `MAIL_PROVIDER`: `mo_email`、`cloudmail`、`cloudflare_temp_email`。
- `MO_EMAIL_BASE_URL`、`MO_EMAIL_DOMAIN`、`MO_EMAIL_NAME_PREFIX`、`MO_EMAIL_START_INDEX`、`MO_EMAIL_API_KEY`: MoEmail 服务接入。
- `MO_EMAIL_EXPIRY_TIME`: 新建邮箱有效期，毫秒。`0` 表示永久邮箱。批量注册推荐 `0`：临时邮箱（如 1 小时、3 小时）会在 OTP 重试或后续 OAuth 补齐前自毁，导致收不到验证码。
- `CPA_URL`、`CPA_KEY`、`SYNC_TARGET_CPA`: CPA 同步。`CPA_URL` 可填 CLIProxyAPI 根地址，也可填 `management.html#/auth-files` 管理页；运行时会归一化为 API 根地址。
- `SUB2API_URL`、`SUB2API_EMAIL`、`SUB2API_PASSWORD`、`SUB2API_GROUP`、`SYNC_TARGET_SUB2API`: Sub2API 同步。
- `PLAYWRIGHT_BROWSER_MODE`: 浏览器显示方式，`hidden` 不弹窗，`visible` 显示窗口，`embedded` 当前按不弹窗运行。
- `PLAYWRIGHT_HEADLESS`: 旧版兼容项，`false` 等同可见窗口。
- `BROWSER_PARALLEL_WORKERS`: 账号补满、轮转和直注批量任务的新号创建并行窗口数，范围 `1..3`。
- `OUTBOUND_PROXY_ENABLED`、`OUTBOUND_PROXY_POOL`、`OUTBOUND_PROXY_BYPASS`、`OUTBOUND_PROXY_STRATEGY`、`OUTBOUND_PROXY_FAILOVER`: 后端外部请求出口代理池。默认使用 `http://127.0.0.1:10808`，本地地址默认绕过。
- `RT_RECOVERY_STEP_TIMEOUT_SECONDS`: RT 恢复邮箱重建和 Deactivated 查信单次 attempt 总超时；未设置时沿用 `RT_RECOVERY_OAUTH_TIMEOUT_SECONDS`，再未设置默认 60 秒。
- `RT_RECOVERY_STEP_RETRY_ATTEMPTS`: RT 恢复邮箱重建和 Deactivated 查信 attempt 次数；未设置时沿用 `RT_RECOVERY_OAUTH_RETRY_ATTEMPTS`，再未设置默认 1，范围 `1..10`；只对网络、代理、超时类错误切换代理重试。
- `RT_RECOVERY_OAUTH_TIMEOUT_SECONDS`: RT 恢复单账号单次 OAuth attempt 总超时，默认 60 秒。
- `RT_RECOVERY_OAUTH_RETRY_ATTEMPTS`: RT 恢复单账号 OAuth attempt 次数，默认 1，范围 `1..10`；只对网络、代理、超时类错误切换代理重试。HTTP 401、错误密码、登录拒绝、账号失效、未注册等账号语义错误不触发代理重试。
- `PROXY_NODE_ENABLED`、`PROXY_NODE_PROVIDER`、`PROXY_NODE_API_KEY`、`PROXY_NODE_BASE_URL`、`PROXY_NODE_PROTOCOL`、`PROXY_NODE_AUTO_REFRESH`、`PROXY_NODE_REFRESH_BEFORE_TASK`、`PROXY_NODE_POLL_INTERVAL_SECONDS`、`PROXY_NODE_POLL_TIMEOUT_SECONDS`、`PROXY_NODE_COUNTRY`、`PROXY_NODE_APPLY_TO_OUTBOUND_POOL`: 代理节点接口配置。当前 provider 支持 `webshare`，刷新后可把节点写入 `OUTBOUND_PROXY_POOL`。
- `PLAYWRIGHT_PROXY_URL`、`PLAYWRIGHT_PROXY_BYPASS`: 浏览器代理和本地回调绕过。
- `AUTO_CHECK_INTERVAL`、`AUTO_CHECK_THRESHOLD`、`AUTO_CHECK_MIN_LOW`: 自动巡检。
- `TEAM_TARGET_SEATS`: Team 总人数目标。
- `FILL_BATCH_SIZE`: 补满成员每次最多新增数。

## 本地数据文件

- `.env`: 运行配置。
- `accounts.json`: 账号池状态，由 `src/autoteam/accounts.py` 读写。
- `flow_runs.json`: 批量 CPA JSON 运行记录，由 `src/autoteam/flow_runs.py` 读写。服务重启时，未结束的运行记录会被标记为失败。
- `state.json`: 管理员登录态，由 `src/autoteam/admin_state.py` 读写。
- `auths/`: Codex OAuth 认证文件，由 `src/autoteam/auth_storage.py` 和 `src/autoteam/codex_auth.py` 管理。
- `auths/archive/`: 每个账号的 CPA auth 文件归档，由 `src/autoteam/auth_archive.py` 写入。
- `screenshots/`: 浏览器自动化调试截图。

## 账号字段

`accounts.json` 常见字段：

- `email`
- `password`
- `mail_provider`
- `mail_account_id`
- `status`
- `usage_status`
- `auth_file`: 兼容字段。OAuth 写入时可能指向 OAuth RT 文件；普通同步不把它当主来源。
- `rt_auth_file`: 账号池 OAuth RT 文件。CPA / Sub2API 上传、账号池额度检查优先使用它。
- `session_auth_file`: ChatGPT Web session 备份。普通同步、库存同步和账号池额度检查不能上传或使用它。
- `registration_status`
- `cpa_status`
- `cpa_error_message`
- `quota_exhausted_at`
- `quota_resets_at`
- `created_at`
- `last_active_at`
- `last_quota`
- `run_id`
- `batch_index`
- `flow_status`
- `flow_stage`
- `flow_error_level`
- `flow_error_message`
- `plan_type`
- `cpa_uploaded_at`
- `cloud_stocked_at`
- `cpa_archive_file`
- `qualified_at`
- `sub2api_synced_at`
- `sync_disabled`
- `sold_at`
- `sale_remote_cleanup`
- `self_use_at`
- `self_use_remote_cleanup`

批量 CPA JSON 常见阶段：`email_created`、`register`、`team_joined`、`oauth`、`quota_check`、`cpa_upload`、`completed`。

同步任务建议字段：

- `sync_status`
- `sync_target`
- `sync_stage`
- `sync_attempts`
- `sync_error_message`
- `sync_updated_at`

这些字段用于 CPA / Sub2API 后台异步同步，不应覆盖批量注册流程的 `flow_*` 字段。

## 认证文件

账号池 OAuth RT 文件名：`auths/codex-{email}-{plan_type}-{hash}-oauth.json`。这是 CPA / Sub2API 普通同步的上传来源。

账号池 ChatGPT session 备份文件名：`auths/codex-{email}-{plan_type}-{hash}-session.json`。它只保留注册完成后的 ChatGPT Web session，不是 CPA / Sub2API 上传凭证。

主号文件名：`auths/codex-main-*.json`。

已售、可售、不可用和归档 auth 文件分别存放在 `auths/sold/`、`auths/tradable/`、`auths/unusable/`、`auths/archive/`。这些分类目录内的文件以 `.json` 结尾，可能不带 `-oauth` / `-session` 后缀。

同一邮箱同时存在根目录文件和分类目录文件时，auth 文件 API 的账号主分类按 `sold` > `tradable` > `unusable` > `active` > `archive` 判断；`archive/` 是备份目录，不会覆盖根目录 active 文件。

常见字段：

- `type`
- `id_token`
- `access_token`
- `refresh_token`
- `account_id`
- `email`
- `expired`
- `last_refresh`
- `credential_source`
- `disabled`

OAuth RT 文件必须包含 `refresh_token`。`credential_source=chatgpt_session` 的文件即使有 `access_token`，也不能作为 CPA / Sub2API 普通同步来源。

这些文件包含敏感 token，默认不提交。

## 运维脚本

`scripts/` 下的运维脚本面向「服务已经在跑、需要对账号池做一次性补救」的场景，不是常规启动入口。

`scripts/recreate_permanent_mailboxes.py`：把已过期的临时 MoEmail 邮箱重建为永久邮箱（`expiryTime=0`）。

- 输入：默认 `.tmp/session_only_emails.json`（JSON array of emails），可通过 `argv[1]` 覆盖。
- 流程：调用 `autoteam.mo_email.MoEmailClient` 的 `_request("POST", "/api/emails/generate", json={name, expiryTime: 0, domain})`，把返回的 `account_id` 通过 `autoteam.accounts.update_account(email, mail_account_id=...)` 写回 `accounts.json`。
- 输出：`.tmp/recreate_permanent_mailboxes.json`，含 `total / recreated / failed / accounts_json_updated / results`。
- 适用：账号 `password` 仍可用、但 MoEmail 邮箱列表为空 / OTP 收不到时。先重建邮箱拿新 `mail_account_id`，再做 OAuth 或 CPA 补齐。

`scripts/backfill_session_only_oauth.sh`：为只有 `session_auth_file`、缺 OAuth RT 的账号串行补齐 OAuth → CPA。

- 输入：`.tmp/session_only_emails.json` + `.env` 中的 `API_KEY`。
- 默认 `API_BASE=http://127.0.0.1:8788`（与 `manager.py api` 子命令默认 8787 不同；可通过 `API_BASE` 环境变量覆盖）。
- 流程：对每个 email 串行 `POST /api/accounts/{email}/cpa-auth` 拿 `task_id`，再每 `POLL_INTERVAL`（默认 5s）轮询 `/api/tasks/{task_id}`，直到 `status` 为 `success / failed / error` 或超过 `POLL_TIMEOUT`（默认 300s）。账号之间额外 `sleep 2`。
- 输出：`.tmp/session-only-oauth/run-<ts>.log`、`<email>.json`、`summary.json`。
- 必要约束：服务端 `_playwright_lock` 是全局非阻塞锁，所以脚本严格顺序执行，不能并发。
