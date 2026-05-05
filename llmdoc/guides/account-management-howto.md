# 账号管理操作指南

适用范围：账号管理页、清理页、库存操作、主号守卫。

先读 `llmdoc/architecture/account-management.md`。这篇只写日常怎么查和怎么做，不重复架构细节。

## 1. 查账号状态

- HTTP 列表接口：`src/autoteam/api.py:1949` 的 `GET /api/accounts`
- HTTP 详情接口：`src/autoteam/api.py:2043` 的 `GET /api/accounts/{email}`
- Auth 文件列表接口：`GET /api/auths/accounts`
- 前端入口：`web/src/components/AccountManagement.vue`
- 本地账号列表组件：`web/src/components/AccountTable.vue`
- Auth 文件盘点组件：`web/src/components/AuthsTable.vue`
- 详情抽屉：`web/src/components/AccountDrawer.vue`

账号管理页当前分两块：

- 本地账号表来自 `/api/accounts`，用于账号生命周期查询、详情抽屉和操作按钮。
- Auth 文件盘点来自 `/api/auths/accounts`，只核对 `auths/` 文件，不直接打开详情抽屉。

Auth 文件盘点筛选参数：

- `category`: `active`、`sold`、`tradable`、`unusable`、`archive`、`all`
- `q`: 邮箱子串
- `has_oauth`: OAuth 三态
- `has_session`: Session 三态
- `page_size`: 20、50、100、200
- `sort`: `email_asc`、`email_desc`、`expired_asc`、`expired_desc`、`category_asc`

默认 category 为空字符串，隐藏 `archive`。接口字段见 `llmdoc/reference/auths-api.md`。

`GET /api/accounts` 用于生命周期模型查询，筛选用的是四轴聚合 `category`，不是 auth 文件 bucket。它和 `/api/auths/accounts` 不要混用。

要看单个账号的四轴状态、远端状态、凭证状态和分配信息，用详情接口或打开详情抽屉。详情接口当前返回：

- `account`
- `category`
- `credentials`
- `remote`
- `allocation`
- `sale`
- `health`
- `events`

其中 `events` 现在固定是空列表，见 `src/autoteam/api.py:2110`。不要把它当成已接通 ledger。

## 2. 改账号状态

当前 HTTP 操作入口都在 `src/autoteam/api.py`：

- 分配库存到使用中：`POST /api/accounts/{email}/allocate`，`src/autoteam/api.py:2417`
- 从使用中释放回库存：`POST /api/accounts/{email}/release`，`src/autoteam/api.py:2456`
- 标记失效：`POST /api/accounts/{email}/mark-invalid`，`src/autoteam/api.py:2493`
- 修复 OAuth 元数据：`POST /api/accounts/{email}/repair-oauth`，`src/autoteam/api.py:2535`
- 售卖并做远端清理：`POST /api/accounts/{email}/sell`，`src/autoteam/api.py:2305`
- 本地 Codex OAuth 登录：`POST /api/accounts/login`
- 移出 Team：`POST /api/accounts/{email}/kick`
- 删除本地管理账号：`DELETE /api/accounts/{email}`
- 导出 Codex CLI auth：`GET /api/accounts/{email}/codex-auth`

对应纯函数在：

- `src/autoteam/account_inventory.py` (`allocate_account`, `release_account`, `sell_account`)
- `src/autoteam/account_health.py` (`mark_invalid`, `mark_quota_exhausted`)

`repair-oauth` 只回写状态元数据，不会重新拉起浏览器登录，见 `src/autoteam/api.py:2535`。

## 3. 手动 allocate / release

分配前要满足这些条件，见 `src/autoteam/account_inventory.py:87`：

- 不是主号
- `usage_status` 不是 `sold`
- `health_status=valid`
- 当前是 `inventory`，或 `force=true` 且已是 `in_use`
- `cpa_status=success`

释放前要满足这些条件，见 `src/autoteam/account_inventory.py:173`：

- 不是主号
- 不是 `sold`
- 当前是 `in_use`

释放时如果健康状态不是 `valid` 或 `quota_exhausted`，会返回 `warning=not_valid`，但仍会把用途改回 `inventory`，见 `src/autoteam/account_inventory.py:221`。

`quota_exhausted` 不等于 `invalid`。额度耗尽只会写 `health_status=quota_exhausted`，不会自动写 `sync_disabled=true`，见 `src/autoteam/account_health.py:118`。

## 4. 跑账号清理 dry-run / apply

扫描入口：

- 纯函数：`src/autoteam/account_cleaner.py` (`scan_accounts`)
- API：`src/autoteam/api.py:2114` 的 `POST /api/accounts/clean/dry-run`
- 前端页：`web/src/components/AccountCleanPage.vue`

应用入口：

- 纯函数：`src/autoteam/account_cleaner.py` (`cleanup_accounts`)
- API：`src/autoteam/api.py:2132` 的 `POST /api/accounts/clean/apply`

清理页按三步走：

1. 扫描
2. 预览
3. 应用

实现位置见 `web/src/components/AccountCleanPage.vue:54`、`web/src/components/AccountCleanPage.vue:109`、`web/src/components/AccountCleanPage.vue:242`。

apply 前一定先备份 `accounts.json`。API 入口会先调 `backup_accounts_file`，生成 `.bak-account-clean-<unix>`，再继续清理，见 `src/autoteam/api.py:2138` 和 `src/autoteam/account_cleaner.py:21`。

## 5. 恢复缺失 RT / 401 RT

RT 恢复用于“账号已注册，但缺 OAuth RT”或“OAuth RT 检测为 401，需要重新获取”的账号。它不用于未注册账号，也不用于已售账号。

相关入口：

- 扫描：`POST /api/accounts/rt-recovery/scan`
- 批量启动：`POST /api/accounts/rt-recovery/start`
- 单账号恢复：`POST /api/accounts/{email}/rt-recovery`
- Deactivated 标记：`POST /api/accounts/rt-recovery/mark-deactivated`
- 前端面板：`web/src/components/AccountRtRecoveryPanel.vue`

批量启动后，每个账号都会先用 MoEmail 按原邮箱重建永久邮箱，再拉取邮件检查 `Deactivated`。如果邮件命中 Deactivated，系统会标记账号不可用、禁用同步并释放 Team 席位，不会继续获取 RT。没有命中时，才会进入 Codex OAuth RT 获取流程。

RT 恢复默认按快速失败处理：邮箱重建、Deactivated 查信和 OAuth 单次 attempt 默认 60 秒，默认只尝试 1 次。需要长等待或多代理重试时，可以通过 `RT_RECOVERY_STEP_TIMEOUT_SECONDS`、`RT_RECOVERY_STEP_RETRY_ATTEMPTS`、`RT_RECOVERY_OAUTH_TIMEOUT_SECONDS`、`RT_RECOVERY_OAUTH_RETRY_ATTEMPTS` 显式覆盖。HTTP 401、`invalid_username_or_password`、`password_rejected`、`login_rejected` 等账号语义错误会直接记失败，不会继续切代理或等待 OTP。

这条流程不会自动上传 CPA / Sub2API。恢复成功后如需远端使用，仍要通过同步中心或单独同步入口处理。

不要把 Sub2API 里存在的账号直接当成可用账号。未注册、不可用、401、`sync_disabled=true` 或没有 Team OAuth RT 的账号，都不能归为使用中。

## 6. 主号禁止说明

主号判断入口：

- 后端模型：`src/autoteam/account_admin.py` (`is_main_account`)
- API 标记：`src/autoteam/api.py:1334`
- 详情抽屉提示：`web/src/components/AccountDrawer.vue:317`

主号库存操作全部禁用：

- `allocate_account` 遇到 `role=main` 直接返回 `reason=main_account`，见 `src/autoteam/account_inventory.py:103`
- `release_account` 遇到 `role=main` 直接返回 `reason=main_account`，见 `src/autoteam/account_inventory.py:185`
- `sell_account` 遇到 `role=main` 直接返回 `reason=main_account`，见 `src/autoteam/account_inventory.py:270`
- API 层也会先挡一次，见 `src/autoteam/api.py:2184`、`src/autoteam/api.py:2256`、`src/autoteam/api.py:2313`

`is_main_account=True` 不是展示字段而已，它是库存流的硬约束。

## 7. 前端约束

账号管理页没有 `vue-router`。顶层切页靠 `web/src/App.vue:221` 的 `currentPage`，模板用 `v-if` / `v-else-if`，见 `web/src/App.vue:156-192`。

新组件如果需要 `defineProps` 的 `validator`，不要引用 `<script setup>` 里的局部变量。旧 `AccountTable.vue` 曾因这个问题 hotfix；后续若在 `AuthsTable.vue` 加 validator，也按同一规则处理。
