# 账号数据结构参考

适用范围：`accounts.json` 的 V2 嵌套结构、旧平铺字段兼容、详情接口和导出读取口径。

## 1. V2 顶层结构

V2 默认结构定义在 `src/autoteam/account_models.py:177-282` 的 `AccountV2` 和 `default_v2_account`。

当前稳定顶层字段：

- `schema_version`
- `id`
- `email`
- `password`
- `role`
- `registration_status`
- `health_status`
- `usage_status`
- `team_status`
- `category`
- `mail`
- `credentials`
- `cpa_status`
- `remote`
- `allocation`
- `sale`
- `sync_disabled`
- `created_at`
- `updated_at`

## 2. 嵌套块说明

### mail

定义：`src/autoteam/account_models.py:122-129`

| 字段 | 类型 | 说明 |
|---|---|---|
| `provider` | `str \| None` | 邮箱 provider |
| `account_id` | `str \| int \| None` | provider 侧账号 ID |
| `domain` | `str \| None` | 邮箱域名 |
| `prefix` | `str \| None` | 前缀 |
| `index` | `int \| None` | 自增序号 |
| `group_id` | `str \| None` | 邮箱分组 ID |

### credentials.session

定义：`src/autoteam/account_models.py:131-134`

| 字段 | 类型 | 说明 |
|---|---|---|
| `file` | `str \| None` | session 文件路径 |
| `present` | `bool` | 是否有记录 |

### credentials.oauth_rt

定义：`src/autoteam/account_models.py:136-140`

| 字段 | 类型 | 说明 |
|---|---|---|
| `file` | `str \| None` | OAuth RT 文件路径 |
| `present` | `bool` | 是否有记录 |
| `has_refresh_token` | `bool` | 是否确认带 refresh token |

`record_rt_obtained` 还会补 `obtained_at`，见 `src/autoteam/account_lifecycle.py:72-118`。

### credentials.cpa_archive

定义：`src/autoteam/account_models.py:142-145`

| 字段 | 类型 | 说明 |
|---|---|---|
| `file` | `str \| None` | CPA 归档路径 |
| `present` | `bool` | 是否有记录 |

### remote

定义：`src/autoteam/account_models.py:153-162`

每个远端块都包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | `str` | 远端同步状态 |
| `auth_name` | `str \| None` | 远端展示名 |
| `group` | `str \| None` | 远端分组 |

当前有：

- `remote.cpa`
- `remote.sub2api`

### allocation

定义：`src/autoteam/account_models.py:164-168`

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | `str \| None` | `inventory` / `in_use` / `released` / `sold` |
| `project` | `str \| None` | 分配项目 |
| `allocation_id` | `str \| None` | 分配 ID |

运行时还可能出现：

- `allocated_to`
- `allocated_at`
- `released_at`
- `release_reason`

见 `src/autoteam/account_inventory.py:139-167` 和 `src/autoteam/account_inventory.py:231-251`。

### sale

定义：`src/autoteam/account_models.py:170-175`

| 字段 | 类型 | 说明 |
|---|---|---|
| `sold_at` | `float \| None` | 售出时间 |
| `sold_to` | `str \| None` | 买方 |
| `sale_batch_id` | `str \| None` | 批次 ID |
| `delivered` | `bool` | 是否已交付 |

运行时还可能出现兼容字段：

- `buyer`
- `price`
- `note`

见 `src/autoteam/account_inventory.py:304-313` 和 `src/autoteam/account_exports.py:169-185`。

## 3. V1 平铺字段对照

迁移入口：`src/autoteam/account_store.py:152-246`

| V1 / 兼容字段 | V2 位置 | 当前说明 |
|---|---|---|
| `auth_file` | `credentials.session.file` 或 `credentials.oauth_rt.file` | 需先判断它是 session 还是 OAuth RT |
| `rt_auth_file` | `credentials.oauth_rt.file` | OAuth RT 主路径 |
| `session_auth_file` | `credentials.session.file` | ChatGPT session 备份 |
| `cpa_archive_file` | `credentials.cpa_archive.file` | CPA 归档 |
| `mail_provider` | `mail.provider` | 邮箱 provider |
| `mail_account_id` | `mail.account_id` | 邮箱账号 ID |
| `cloudmail_account_id` | `mail.account_id` | 旧字段兼容 |
| `status` | 四轴组合 | 通过 `legacy_status_to_axes` 拆分 |
| `sold_at` | `sale.sold_at` | 已售时间 |
| `cpa_status` | 顶层 `cpa_status` | 兼容保留 |

## 4. 详情接口与嵌套结构的关系

`GET /api/accounts/{email}` 当前没有直接把 V2 `credentials.*` 原样返回。它返回的是这三个兼容凭证块：

- `rt_auth_file`
- `session_auth_file`
- `auth_file`

见 `src/autoteam/api.py:2096-2100`。

所以当前前端详情页还处在“兼容旧平铺路径优先展示”的阶段，不能把它误写成“完整展示 V2 credentials 嵌套块”。

## 5. 凭证识别和导出口径

凭证识别入口：`src/autoteam/account_credentials.py:79` 的 `identify_credential_file`

关键边界：

- `credential_source=chatgpt_session` 或文件名像 session，就按 session 处理
- OAuth RT 是否可上传，要看 `is_uploadable_oauth_rt`
- 导出库存 CSV 时优先拿 `credentials.oauth_rt` 和 `credentials.cpa_archive`

对应实现见：

- `src/autoteam/account_credentials.py:96-111`
- `src/autoteam/account_exports.py:132-137`

## 6. 数据清理与备份边界

- 清理 apply 之前必须先写 `accounts.json.bak-account-clean-<unix>`，见 `src/autoteam/account_cleaner.py:21` 和 `src/autoteam/api.py:2138`
- 主号约束修正由 `src/autoteam/account_admin.py` 负责，必要时会把 `usage_status` 拉回 `normal`、把 `sync_disabled` 拉回 `false`，见 `src/autoteam/account_admin.py:86-119`
