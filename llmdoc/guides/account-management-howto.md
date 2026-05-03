# 账号管理操作指南

适用范围：账号管理页、清理页、库存操作、主号守卫。

先读 `llmdoc/architecture/account-management.md`。这篇只写日常怎么查和怎么做，不重复架构细节。

## 1. 查账号状态

- HTTP 列表接口：`src/autoteam/api.py:1949` 的 `GET /api/accounts`
- HTTP 详情接口：`src/autoteam/api.py:2043` 的 `GET /api/accounts/{email}`
- Auth 文件列表接口：`GET /api/auths/accounts`
- 批量动作接口：`POST /api/accounts/bulk-action`
- 前端入口：`web/src/components/AccountManagement.vue`
- 本地账号列表组件：`web/src/components/AccountTable.vue`
- Auth 文件表组件：`web/src/components/AuthsTable.vue`
- 详情抽屉：`web/src/components/AccountDrawer.vue`

账号管理页当前分两块：

- 本地账号表来自 `/api/accounts`，用于账号生命周期查询、详情抽屉和操作按钮。
- Auth 文件盘点来自 `/api/auths/accounts`，只核对 `auths/` 文件，不直接打开详情抽屉。

Auth 文件表筛选来自 `/api/auths/accounts`：

- `category`: `active`、`sold`、`tradable`、`unusable`、`archive`、`all`
- `plan_type`: `team`、`plus`、`free`、`unknown`、`all`
- `q`: 邮箱子串
- `has_oauth`: OAuth 三态
- `has_session`: Session 三态
- `page_size`: 20、50、100、200
- `sort`: `email_asc`、`email_desc`、`expired_asc`、`expired_desc`、`category_asc`、`plan_asc`

默认 category 为空字符串，隐藏 `archive`，但保留非 Team plan。非 Team 行只读展示，不打开详情抽屉，也不能做危险批量动作。接口字段见 `llmdoc/reference/auths-api.md`。

`GET /api/accounts` 仍用于生命周期模型查询，筛选用的是四轴聚合 `category`，不是 auth 文件 bucket。它和 `/api/auths/accounts` 不要混用。

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
- 批量标记失效、卖出、删除、Team 移出、取消邀请：`POST /api/accounts/bulk-action`

对应纯函数在：

- `src/autoteam/account_inventory.py` (`allocate_account`, `release_account`, `sell_account`)
- `src/autoteam/account_health.py` (`mark_invalid`, `mark_quota_exhausted`)

`repair-oauth` 只回写状态元数据，不会重新拉起浏览器登录，见 `src/autoteam/api.py:2535`。

批量接口先用 `confirm=false` 做预览。预览不会写 `accounts.json`，不会删除 CPA / Sub2API，也不会调用 Team API。确认后再用同一批 `items` 和 `confirm=true` 执行。

安全顺序：

1. 在账号管理页只选择 Team plan 行。非 Team plan 只读，不进入批量选择。
2. 卖出前确认账号仍在 `accounts.json`，`status=active`，并且有本地 OAuth RT 文件。执行时后端先删除已启用 CPA / Sub2API 的同邮箱或同 auth 文件远端记录，再写本地 `sold` 和 `sync_disabled=true`。
3. 删除账号会走正式删除流程：抢 `_playwright_lock`，再由 `delete_managed_account` 处理 Team member、invite、远端同步目标、本地 auth 文件、邮箱提供者账号和本地记录。
4. Team 成员移出和邀请取消也要抢 `_playwright_lock`，避免和浏览器任务同时改远端。
5. 单项失败只影响该邮箱，后端继续处理后续项；前端显示成功、跳过、失败数量和前几条原因。

跳过原因常见值：

- `main_account`: 主号禁止批量危险操作。
- `non_team_plan`: 非 Team auth 文件只能只读展示。
- `missing_account`: 本地 `accounts.json` 不存在该邮箱。
- `missing_oauth_rt`: 卖出缺少可用 OAuth RT 文件。
- `not_active`: 卖出时账号不是 active。
- `invalid_type` 或 `missing_user_id`: Team 成员动作参数不完整。

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

## 5. 主号禁止说明

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

## 6. 前端约束

账号管理页没有 `vue-router`。顶层切页靠 `web/src/App.vue:221` 的 `currentPage`，模板用 `v-if` / `v-else-if`，见 `web/src/App.vue:156-192`。

新组件如果需要 `defineProps` 的 `validator`，不要引用 `<script setup>` 里的局部变量。旧 `AccountTable.vue` 曾因这个问题 hotfix；后续若在 `AuthsTable.vue` 加 validator，也按同一规则处理。
