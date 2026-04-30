# 配置与数据文件

## 配置来源

`src/autoteam/config.py`: 启动时从项目根 `.env` 读取环境变量，再导出常量。

`src/autoteam/setup_wizard.py`: 首次配置和 `.env` 写入。

`src/autoteam/api.py`: Web 配置接口，支持读取和写入运行配置。

## 关键配置

- `API_KEY`: Web 面板和 API 鉴权。启动阶段唯一强制项。
- `MAIL_PROVIDER`: `mo_email`、`cloudmail`、`cloudflare_temp_email`。
- `CPA_URL`、`CPA_KEY`、`SYNC_TARGET_CPA`: CPA 同步。
- `SUB2API_URL`、`SUB2API_EMAIL`、`SUB2API_PASSWORD`、`SUB2API_GROUP`、`SYNC_TARGET_SUB2API`: Sub2API 同步。
- `SYNC_EXECUTION_MODE`: 同步执行方式，建议默认 `async`，可选 `inline`。
- `SYNC_UPLOAD_STRATEGY`: 上传策略，建议默认 `incremental`，可选 `full`。
- `SYNC_DELETE_MISSING`: 是否删除远端缺失匹配项，建议默认 `false`。
- `SYNC_FAILURE_POLICY`: 同步错误策略，建议默认 `pause`，可选 `continue`。
- `SYNC_AUTO_RETRY`: 自动重试策略，建议默认 `transient`，可选 `off`、`always`。
- `SYNC_RETRY_MAX_ATTEMPTS`: 单项同步最大尝试次数，建议默认 `3`。
- `SYNC_RETRY_BACKOFF_SECONDS`: 重试等待时间列表，建议默认 `5,30,120`。
- `SYNC_PAUSE_ON_SUCCESS_RATE_BELOW`: 批量成功率低于该值时暂停，建议默认 `95`。
- `PLAYWRIGHT_BROWSER_MODE`: 浏览器显示方式，`hidden` 不弹窗，`visible` 显示窗口，`embedded` 当前按不弹窗运行。
- `PLAYWRIGHT_HEADLESS`: 旧版兼容项，`false` 等同可见窗口。
- `BROWSER_PARALLEL_WORKERS`: 账号补满、轮转和直注批量任务的新号创建并行窗口数，范围 `1..3`。
- `OUTBOUND_PROXY_ENABLED`、`OUTBOUND_PROXY_POOL`、`OUTBOUND_PROXY_BYPASS`、`OUTBOUND_PROXY_STRATEGY`、`OUTBOUND_PROXY_FAILOVER`: 后端外部请求出口代理池。默认使用 `http://127.0.0.1:10808`，本地地址默认绕过。
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
- `auth_file`
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
- `cpa_archive_file`
- `qualified_at`
- `sub2api_synced_at`
- `sync_disabled`
- `sold_at`
- `sale_remote_cleanup`

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

账号池文件名：`auths/codex-{email}-{plan_type}-{hash}.json`。

主号文件名：`auths/codex-main-*.json`。

账号归档文件：`auths/archive/{email}/codex-{email}-{plan_type}-{hash}.json`。归档文件同样包含敏感 token，不提交。

常见字段：

- `type`
- `id_token`
- `access_token`
- `refresh_token`
- `account_id`
- `email`
- `expired`
- `last_refresh`

这些文件包含敏感 token，默认不提交。
