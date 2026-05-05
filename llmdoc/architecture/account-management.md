# Account Management Architecture

> 适用范围：AutoTeam 账号生命周期、四轴状态、数据清理、HTTP API、Web UI、事件审计

## 1. 概述

账号管理子系统覆盖从邮箱创建、注册入席、OAuth RT 获取、CPA 入库、库存分配、失效修复、售卖下架到本地审计的整条链路。

旧模型主要依赖单一 `status` 字段。当前实现已经把账号状态拆成注册、健康、用途、Team 四个独立轴，再由 `category` 做 UI 和 API 侧的聚合分类。核心模型在 `src/autoteam/account_models.py:12`，分类逻辑在 `src/autoteam/account_classifier.py:47`，旧数据兼容迁移在 `src/autoteam/account_store.py:249`。

这套模型的目标不是替换全部旧字段，而是在保留 `status`、`auth_file`、`rt_auth_file` 等兼容字段的前提下，让账号管理页、清理页、库存操作和导出逻辑共享同一套判断口径。

## 2. 四轴状态模型

四轴字段由 `src/autoteam/account_models.py:15`、`src/autoteam/account_models.py:34`、`src/autoteam/account_models.py:57`、`src/autoteam/account_models.py:78` 定义。

| 轴 | 字段 | 当前取值 | 主要写入模块 |
|----|------|----------|-------------|
| 注册 | `registration_status` | `planned` / `mail_created` / `registering` / `registered` / `register_failed` / `abandoned` | `src/autoteam/account_store.py:72`、`src/autoteam/cpa_batch.py` |
| 健康 | `health_status` | `unknown` / `valid` / `quota_exhausted` / `auth_expired` / `invalid` / `deactivated` / `risk_blocked` / `sync_error` | `src/autoteam/account_health.py:56` |
| 用途 | `usage_status` | `normal` / `inventory` / `in_use` / `reserved` / `sold` / `self_use` / `quarantine` | `src/autoteam/account_inventory.py:87` |
| Team | `team_status` | `unknown` / `active` / `standby` / `pending_invite` / `removed` / `external` / `owner` | `src/autoteam/account_models.py:77`、`src/autoteam/account_store.py:94` |

`category` 不是持久化真值，而是聚合视图。实际计算入口是 `src/autoteam/account_classifier.py:47`。

当前分类取值：

- `registered`
- `inventory`
- `in_use`
- `invalid`
- `sold`
- `not_registered`

当前优先级：

1. `sold`
2. `invalid`
3. `not_registered`
4. `in_use`
5. `inventory`
6. `registered`

这里要注意三点：

- 当前代码里 `not_registered` 的判断发生在 `in_use` 和 `inventory` 之前，严格来说优先级是 `sold > invalid > not_registered > in_use > inventory > registered`，见 `src/autoteam/account_classifier.py:50`。
- `in_use` 不只看 `usage_status=in_use`。必须是已注册、可用，且 Sub2API 真实存在。`src/autoteam/account_classifier.py` (`derive_category`, `reconcile_usage_classification`) 支持用 `sub2api_present` 传入实时远端结果；默认只认 `remote.sub2api.status=present/uploaded`。
- `inventory` 不只看 `usage_status=inventory`。还要求账号可用、`cpa_status=success`、存在 OAuth RT，且未禁用同步，见 `src/autoteam/account_classifier.py` (`is_usable_account`, `derive_category`)。

四轴之外还有两类相关状态：

- 远端同步状态 `remote.cpa.status` / `remote.sub2api.status`，定义在 `src/autoteam/account_models.py:98`。
- 分配状态 `allocation.status`，当前取值 `inventory` / `in_use` / `released` / `sold`，定义在 `src/autoteam/account_inventory.py:19`。

## 3. 数据契约

V2 账号结构由 `default_v2_account` 生成，入口在 `src/autoteam/account_models.py:237`。当前稳定字段分层如下：

- 顶层基础字段：`schema_version`、`id`、`email`、`password`、`role`
- 四轴字段：`registration_status`、`health_status`、`usage_status`、`team_status`
- 聚合字段：`category`、`sync_disabled`、`cpa_status`
- 嵌套结构：`mail`、`credentials`、`remote`、`allocation`、`sale`

V2 凭证结构：

- `credentials.session.file` / `present`
- `credentials.oauth_rt.file` / `present` / `has_refresh_token`
- `credentials.cpa_archive.file` / `present`

兼容字段仍保留在账号记录顶层，主要给旧流程和旧页面使用：

- `auth_file`
- `rt_auth_file`
- `session_auth_file`
- `cpa_archive_file`
- `mail_provider`
- `mail_account_id`
- `status`

旧字段迁移入口是 `src/autoteam/account_store.py:249`。这里会做四件事：

1. 把旧 `status` 映射到四轴，映射表在 `src/autoteam/account_models.py:213`。
2. 把旧 `auth_file` 拆分成 `session_auth_file` 或 `rt_auth_file`，辅助逻辑在 `src/autoteam/account_store.py:60`。
3. 构建 `credentials`、`remote`、`allocation`、`sale` 等 V2 嵌套块，入口分别在 `src/autoteam/account_store.py:152`、`src/autoteam/account_store.py:188`、`src/autoteam/account_store.py:230`、`src/autoteam/account_store.py:239`。
4. 把 `schema_version` 提升到 `2`，并在需要时写 `.bak-account-store-<ts>` 备份，入口在 `src/autoteam/account_store.py:318`。

主号不是普通库存账号。主号模型在 `src/autoteam/account_admin.py:54`，会强制：

- `role=main`
- `usage_status=normal`
- `team_status` 只能是 `active` 或 `standby`
- `sync_disabled=false`

守门逻辑在 `src/autoteam/account_admin.py:86`。

## 4. 数据清理流程

账号清理逻辑集中在 `src/autoteam/account_cleaner.py`。

入口分两层：

- `scan_accounts`：只扫描，不写文件，见 `src/autoteam/account_cleaner.py:360`
- `cleanup_accounts`：迁移、去重、重算分类，可选写回，见 `src/autoteam/account_cleaner.py:568`

实际 apply 流程：

1. 读 `accounts.json`
2. `backup_accounts_file` 生成 `accounts.json.bak-account-clean-<ts>`，见 `src/autoteam/account_cleaner.py:21`
3. `reclassify_accounts` 串行执行迁移、凭证整理、去重、分类重算，见 `src/autoteam/account_cleaner.py:527`
4. `scan_accounts` 对清理后的结果复扫，见 `src/autoteam/account_cleaner.py:584`
5. 写回 `accounts.json`

当前扫描类别由 `SCAN_ISSUE_KEYS` 固定，定义在 `src/autoteam/account_cleaner.py:59`：

- `duplicate_emails`
- `missing_password`
- `missing_rt_auth_file`
- `session_used_as_auth_file`
- `sold_sync_enabled`
- `invalid_in_inventory`
- `cpa_success_not_inventory`
- `missing_credential_file`

每类问题的判定口径：

- `duplicate_emails`：同邮箱有多条记录，按固定优先级选主记录，见 `src/autoteam/account_cleaner.py:212`
- `missing_password`：已注册账号缺密码，见 `src/autoteam/account_cleaner.py:379`
- `missing_rt_auth_file`：`usage_status=inventory` 或 `cpa_status=success`，但没有可上传的 OAuth RT 文件，见 `src/autoteam/account_cleaner.py:413`
- `session_used_as_auth_file`：`auth_file` 指到了 session 文件，见 `src/autoteam/account_cleaner.py:396`
- `sold_sync_enabled`：已售账号仍未 `sync_disabled=true`，见 `src/autoteam/account_cleaner.py:422`
- `invalid_in_inventory`：`health_status=invalid` 但仍在库存，见 `src/autoteam/account_cleaner.py:427`
- `cpa_success_not_inventory`：`cpa_status=success` 但 `usage_status` 不是 `inventory`，见 `src/autoteam/account_cleaner.py:432`
- `missing_credential_file`：顶层引用的凭证文件路径不存在，见 `src/autoteam/account_cleaner.py:384`

清理报告有两种输出：

- JSON：`scan_accounts` 返回的结构
- CSV：`format_scan_report_csv` 生成 `issue,email,detail` 三列，见 `src/autoteam/account_cleaner.py:469`

## 5. HTTP API 端点

账号管理重构新增或直接依赖的 HTTP 端点都在 `src/autoteam/api.py`。

### 查询与详情

| 方法 | 路径 | 说明 | 提交 |
|------|------|------|------|
| GET | `/api/accounts` | 分页、分类、搜索、排序 | `3d5bf5a` |
| GET | `/api/accounts/{email}` | 聚合详情，返回账号、凭证、远端、分配、售卖、健康、事件占位 | `467a16f` |

`GET /api/accounts` 的过滤条件当前是：

- `category`: `registered` / `inventory` / `in_use` / `invalid` / `sold` / `not_registered` / `all`
- `q`: 只搜 `email` 和 `notes`
- `page` / `page_size`
- `sort`: `updated_at_desc` / `updated_at_asc` / `email_asc` / `email_desc` / `created_at_desc`

实现入口在 `src/autoteam/api.py:1949`。

`GET /api/accounts/{email}` 的聚合结构包含：

- `account`
- `category`
- `credentials`
- `remote`
- `allocation`
- `sale`
- `health`
- `events`

实现入口在 `src/autoteam/api.py:2043`。当前 `events` 字段固定返回空列表，真实 ledger 还没接到这个接口，见 `src/autoteam/api.py:2110`。

### 清理

| 方法 | 路径 | 说明 | 提交 |
|------|------|------|------|
| POST | `/api/accounts/clean/dry-run` | 扫描账号池并返回 JSON + CSV | `696c382` |
| POST | `/api/accounts/clean/apply` | 自动备份后应用清理，再返回复扫结果 | `696c382` |

实现入口在 `src/autoteam/api.py:2114` 和 `src/autoteam/api.py:2132`。

### RT 恢复

| 方法 | 路径 | 说明 | 提交 |
|------|------|------|------|
| POST | `/api/accounts/rt-recovery/scan` | 扫描缺 RT、401 需要重取 RT、deactivated 和不可恢复账号 | 本地改动 |
| POST | `/api/accounts/rt-recovery/start` | 人工启动批量 RT 恢复任务 | 本地改动 |
| POST | `/api/accounts/rt-recovery/mark-deactivated` | 将 deactivated 账号标记不可用，并释放 Team 席位 | 本地改动 |
| POST | `/api/accounts/{email}/rt-recovery` | 单账号 RT 恢复 | 本地改动 |

RT 恢复的状态判断在 `src/autoteam/account_rt_recovery.py`。启动任务在 `src/autoteam/api.py`，顺序固定为 MoEmail 永久邮箱重建、定向拉信检查 Deactivated、命中后标记不可用并释放 Team、未命中才获取 OAuth RT。

这组接口不属于 CPA / Sub2API 同步接口。恢复成功只保证本地账号和 OAuth RT 文件更新；远端上传要走同步中心或单独同步入口。

### 库存与修复操作

| 方法 | 路径 | 说明 | 提交 |
|------|------|------|------|
| POST | `/api/accounts/{email}/allocate` | 库存账号分配到 `in_use` | `88e68da` |
| POST | `/api/accounts/{email}/release` | `in_use` 账号释放回库存 | `88e68da` |
| POST | `/api/accounts/{email}/mark-invalid` | 标记失效并写 `invalid_reason` | `88e68da` |
| POST | `/api/accounts/{email}/repair-oauth` | 只回写 OAuth 修复元数据，不启动浏览器 | `88e68da` |
| POST | `/api/accounts/{email}/sell` | 既有售卖入口，远端清理后标记已售 | 既有接口，重构沿用 |

实现入口分别在 `src/autoteam/api.py:2416`、`src/autoteam/api.py:2455`、`src/autoteam/api.py:2492`、`src/autoteam/api.py:2534`、`src/autoteam/api.py:2305`。

这些端点的返回结构都收敛到：

- `changed`
- `applied`
- `reason`
- `warning`
- `account`

例外是 `sell`，它返回远端删除结果、归档文件和最终状态，不走统一操作返回体。

## 6. Web UI

账号管理前端不使用 `vue-router`。顶层页面切换由 `web/src/App.vue:221` 的 `currentPage` 控制，模板用 `v-if` / `v-else-if` 切页，见 `web/src/App.vue:156` 到 `web/src/App.vue:192`。

账号管理相关入口：

| 页面键 | 组件 | 作用 |
|--------|------|------|
| `accounts` | `web/src/components/AccountManagement.vue` | 本地账号表、Auth 文件盘点和详情抽屉入口 |
| `account-clean` | `web/src/components/AccountCleanPage.vue` | 扫描、预览、应用三步清理 |

### 账号管理中心

`web/src/components/AccountManagement.vue` 已移除旧五 tab 账号视图。当前页面由三个子组件组成：

- `AccountTable.vue`：从 `/api/accounts` 读取 `accounts.json` 生命周期模型，提供本地账号操作入口。操作列调用 `loginAccount`、`getCodexAuth`、`kickAccount`、`sellAccount`、`deleteAccount`。
- `AuthsTable.vue`：从 `/api/auths/accounts` 读取 `auths/` 文件聚合结果，提供 category、plan_type、OAuth、Session、排序、邮箱搜索、分页和 Team 批量工具。
- `AccountDrawer.vue`：详情抽屉与状态操作，只接收 `/api/accounts` 可解析的邮箱。

`AuthsTable.vue` 不再触发行点击详情，避免 auth-only 邮箱调用 `/api/accounts/{email}` 后返回 404。

### 账号列表

`web/src/components/AuthsTable.vue` 当前负责：

- category 下拉：`active`、`sold`、`tradable`、`unusable`、`archive`、`all`
- plan_type 下拉：`team`、`plus`、`free`、`unknown`
- OAuth 三态筛选
- Session 三态筛选
- 邮箱搜索
- 排序：`email_asc`、`email_desc`、`expired_asc`、`expired_desc`、`category_asc`、`plan_asc`
- 页大小：20、50、100、200
- facets badge：显示按邮箱主分类聚合后的五个 bucket 计数
- Team 行勾选和批量工具条：`mark-invalid`、`sell`、`delete`

列表数据调用 `api.getAuthsAccounts`，也就是 `GET /api/auths/accounts`。默认 category 为空字符串，隐藏 `archive`，但不隐藏非 Team plan。非 Team 行只读，不打开详情抽屉，也不能进入危险批量选择。

当前列表列包括：

- 邮箱
- plan
- category
- OAuth
- Session
- expired
- 文件信息

### 详情抽屉

`web/src/components/AccountDrawer.vue` 当前有 7 个详情区块和 1 个操作区块：

1. 基本信息，见 `web/src/components/AccountDrawer.vue:72`
2. 认证文件，见 `web/src/components/AccountDrawer.vue:135`
3. 远端同步，见 `web/src/components/AccountDrawer.vue:171`
4. 分配信息，见 `web/src/components/AccountDrawer.vue:219`
5. 售卖信息，见 `web/src/components/AccountDrawer.vue:261`
6. 事件日志，见 `web/src/components/AccountDrawer.vue:291`
7. 操作，见 `web/src/components/AccountDrawer.vue:306`

当前支持的 4 个动作按钮：

- `allocate`
- `release`
- `mark-invalid`
- `repair-oauth`

见 `web/src/components/AccountDrawer.vue:330`。

主号限制也在 UI 侧做了显式禁用，见 `web/src/components/AccountDrawer.vue:317`。

事件日志区块目前还是占位文案 `暂无事件（AT-035 接入 ledger）`，见 `web/src/components/AccountDrawer.vue:301`。这和后端 `events: []` 的现状一致。

### 账号清理页

`web/src/components/AccountCleanPage.vue` 是固定三步流：

1. 扫描，见 `web/src/components/AccountCleanPage.vue:54`
2. 预览风险，见 `web/src/components/AccountCleanPage.vue:109`
3. 应用，见 `web/src/components/AccountCleanPage.vue:242`

页面特征：

- dry-run 时只调 `/api/accounts/clean/dry-run`
- 可下载扫描 CSV
- apply 前靠 `window.confirm` 做最终确认
- apply 后展示 `backup_path`、重分类统计和复扫摘要

对应任务提交是 `11ba8d7`。

## 7. 事件 Ledger

事件 ledger 模块已经落在 `src/autoteam/account_ledger.py`，提交是 `bba1730`。

当前 ledger 不是数据库，也不是内存任务表，而是本地 append-only jsonl：

- 目录：`data/account-ledger`
- 文件粒度：按天一个 `YYYY-MM-DD.jsonl`
- 写入入口：`append_event`，见 `src/autoteam/account_ledger.py:33`
- 读取入口：`read_events`，见 `src/autoteam/account_ledger.py:82`

单条事件结构：

- `event_id`
- `ts`
- `event_type`
- `email`
- `actor`
- `payload`

事件 ID 格式是 `evt_<unix>_<6hex>`，见 `src/autoteam/account_ledger.py:25`。

当前测试里已经覆盖过的事件类型包括：

- `register`
- `inventory`
- `allocate`

见 `tests/unit/test_account_ledger.py:35`、`tests/unit/test_account_ledger.py:44`、`tests/unit/test_account_ledger.py:55`。

这点要和产品骨架区分开：

- ledger 模块本身已实现，可独立写入和按邮箱/时间过滤读取
- 账号详情 API 还没有真正把 ledger 读进 `events`
- 账号详情抽屉也还只是占位

所以现在 ledger 属于“底层能力已到位，检索面还没完全接上”的状态。

## 8. CSV 导入导出

CSV 导入导出模块在 `src/autoteam/account_exports.py`。

当前已实现的三个入口：

| 函数 | 说明 | 提交 |
|------|------|------|
| `export_inventory_csv` | 导出库存账号 | `3206599` |
| `export_sold_csv` | 导出已售账号 | `99bfd0c` |
| `dry_run_import_csv` | 导入前预览冲突和缺字段 | `b531102` |

库存导出列头在 `src/autoteam/account_exports.py:10`：

- `email`
- `password`
- `cpa_json_path`
- `auth_file_path`
- `plan_type`
- `registered_at`
- `updated_at`
- `note`

已售导出列头在 `src/autoteam/account_exports.py:21`：

- `email`
- `sold_at`
- `sold_to`
- `sale_price`
- `sale_note`
- `sale_batch_id`
- `plan_type`
- `original_inventory_at`

导入 dry-run 返回：

- `headers`
- `row_count`
- `to_add`
- `conflicts`
- `missing_fields`
- `invalid_rows`
- `summary`

实现入口在 `src/autoteam/account_exports.py:197`。

## 9. 测试覆盖

账号管理重构相关测试集中在 `tests/unit/`。

核心模块测试：

- `tests/unit/test_account_models.py`
- `tests/unit/test_account_classifier.py`
- `tests/unit/test_account_store.py`
- `tests/unit/test_account_cleaner.py`
- `tests/unit/test_account_credentials.py`
- `tests/unit/test_account_admin.py`
- `tests/unit/test_account_inventory.py`
- `tests/unit/test_account_health.py`
- `tests/unit/test_account_ledger.py`
- `tests/unit/test_account_exports.py`

API 测试：

- `tests/unit/test_api_accounts_list.py`
- `tests/unit/test_api_accounts_detail.py`
- `tests/unit/test_api_accounts_clean.py`
- `tests/unit/test_api_accounts_inventory_ops.py`

辅助链路测试：

- `tests/unit/test_account_lifecycle.py`
- `tests/unit/test_account_remote.py`

这组测试文件已经覆盖四轴分类、旧数据迁移、清理、库存操作、失效标记、CSV 导出导入、ledger 读写，以及账号管理 API 的主要返回结构。

当前仓库对这一批改动的统一验收口径仍然是 `uv run pytest -q`。本次任务是纯文档收尾，没有重新跑测试。

## 10. 关键约束 / 易错点

- `sold` 的优先级最高。已售账号会被强制 `usage_status=sold` 且 `sync_disabled=true`，见 `src/autoteam/account_classifier.py:78` 和 `src/autoteam/account_inventory.py:288`。
- Sub2API 存在不等于使用中。未注册、不可用、检测到 401、`sync_disabled=true`、没有 Team OAuth RT 的账号都不能归为 `in_use`；实时修正脚本见 `temp/reconcile_sub2api_account_usage.py`。
- `quota_exhausted` 不等于 `invalid`。额度用尽只写 `health_status=quota_exhausted`，不会自动 `sync_disabled`，也不会把库存直接打成失效，见 `src/autoteam/account_health.py:118`。
- 主号不能进入库存流。分配、释放、售卖、详情抽屉动作都要先挡掉 `role=main`，见 `src/autoteam/account_inventory.py:103`、`src/autoteam/account_inventory.py:185`、`src/autoteam/account_inventory.py:270`、`web/src/components/AccountDrawer.vue:317`。
- `repair-oauth` 不是重新跑浏览器登录。它只把 `health_status` 回写成 `valid` 并记一条修复元数据，见 `src/autoteam/api.py:2535`。
- `GET /api/accounts/{email}` 当前没有真实事件列表。不要把 `events` 字段当成已经接通 ledger 的事实，见 `src/autoteam/api.py:2110`。
- `inventory` 分类要求 OAuth RT 可上传。只有 `auth_file` 或只有 session 备份，不会进库存类，见 `src/autoteam/account_classifier.py:58` 和 `src/autoteam/account_cleaner.py:413`。
- 清理 apply 必先备份 `accounts.json`。API 层先调 `backup_accounts_file`，再执行 `cleanup_accounts`，见 `src/autoteam/api.py:2138`。
- `AT-013` 在 `cpa_batch.py` 里留了兼容旧路径的模块级 monkey-patch：`accounts.REGISTRATION_STATUS_SUCCESS = "registered"`。这条兼容事实来自任务清单 `docs/AutoTeam-账号管理重构文档包/04-AutoTeam-账号管理重构-TODO.csv:14`，后续如果移除，先审计旧调用点。

## 11. 重构史 / 提交链

本轮账号管理重构在 `acc` 分支按 Phase 1 到 Phase 8 串行推进，任务清单在 `docs/AutoTeam-账号管理重构文档包/progress.md:26`。

和本篇直接相关的提交链：

- `e69d9b9`：AT-001 四轴状态与 V2 结构
- `e6ee9d4`：AT-002 分类函数
- `d6668cf`：AT-036 旧 `status` 迁移到四轴
- `9249272` / `e43353e` / `35dabc2` / `a4f69d6`：AT-003 到 AT-008 数据清理与凭证迁移
- `6861a8f` / `4ef9e5e`：AT-009 到 AT-010 主号模型与主号凭证摘要
- `78cd46c` / `9c76639` / `1a3620c`：AT-013 到 AT-015 注册、OAuth RT、CPA 入库
- `22473ce` / `9031245` / `fedbf87`：AT-017 到 AT-019 分配、释放、售卖
- `e4c663c` / `b544e7f`：AT-021 到 AT-022 失效与额度耗尽区分
- `3d5bf5a` / `467a16f` / `696c382` / `88e68da`：AT-023 到 AT-026 API
- `c5d8a6e` / `a88dbf2` / `6e3cc11` / `11ba8d7`：AT-028 到 AT-031 Web UI
- `3206599` / `99bfd0c` / `b531102` / `bba1730`：AT-032 到 AT-035 CSV 与 ledger

## 12. 相关文档

- `llmdoc/architecture/account-lifecycle.md`：旧生命周期视角，偏轮转和已售逻辑
- `llmdoc/architecture/api-and-web.md`：FastAPI 与 Web 总体入口
- `llmdoc/architecture/sync-targets.md`：CPA / Sub2API 状态与远端同步边界
- `llmdoc/guides/local-development.md`：本地开发、测试、构建
- `llmdoc/reference/config-data-files.md`：`accounts.json`、`auths/`、`flow_runs.json` 等数据文件
- `docs/AutoTeam-账号管理重构文档包/04-AutoTeam-账号管理重构-TODO.csv`：AT-001 到 AT-040 的逐项提交与验收记录
