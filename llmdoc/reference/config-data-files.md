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

批量 CPA JSON 常见阶段：`email_created`、`register`、`team_joined`、`oauth`、`quota_check`、`cpa_upload`、`completed`。

## 认证文件

账号池文件名：`auths/codex-{email}-{plan_type}-{hash}.json`。

主号文件名：`auths/codex-main-*.json`。

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
