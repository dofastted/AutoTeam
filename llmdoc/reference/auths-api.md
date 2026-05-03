# Auth 文件 API 参考

适用范围：`auths/` 文件盘点、账号管理页扁平表、Dashboard auth 文件统计。

## 文件扫描

扫描入口在 `src/autoteam/api.py`。

- 根目录文件名：`auths/codex-{email}-{plan_type}-{hash}-{oauth|session}.json`
- `plan_type` 当前识别 `team`、`plus`、`free`、`unknown`。旧 Team 文件仍按 `team` 解析。
- 分类目录：`auths/sold/`、`auths/tradable/`、`auths/unusable/account_deactivated/`、`auths/archive/`
- 分类目录中文件以 `.json` 结尾，不带 `-oauth` / `-session` 后缀
- 已知 bucket：`active`、`sold`、`tradable`、`unusable`、`archive`
- 同一邮箱可能同时出现在根目录和分类目录。主分类由 `_bucket_primary_category(categories)` 决定，优先级是 `sold` > `tradable` > `unusable` > `active` > `archive`；空集合为 `unknown`。`archive/` 是备份目录，不覆盖根目录仍存在的 active 文件。

auth JSON 常见字段：

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

`auths/` 数据曾从 `/mnt/x/project/AutoTeam/auths/` 复制到当前 `acc` worktree，命令语义是 `cp -rn`，不会覆盖已有同名文件。

## GET /api/auths/stats

无查询参数。

返回字段：

| 字段 | 含义 |
|---|---|
| `total_files` | 扫描到的 `.json` 文件总数 |
| `oauth_files` | 根目录中 `-oauth.json` 文件数 |
| `session_files` | 根目录中 `-session.json` 文件数 |
| `active_files` | 根目录可解析 active 文件数 |
| `sold_files` | `auths/sold/` 文件数 |
| `tradable_files` | `auths/tradable/` 文件数 |
| `unusable_files` | `auths/unusable/` 下文件数 |
| `archive_files` | `auths/archive/` 文件数 |
| `accounts_active` | 主分类为 `active` 的唯一邮箱数 |
| `accounts_sold` | 主分类为 `sold` 的唯一邮箱数 |
| `accounts_tradable` | 主分类为 `tradable` 的唯一邮箱数 |
| `accounts_unusable` | 主分类为 `unusable` 的唯一邮箱数 |
| `accounts_archive` | 主分类为 `archive` 的唯一邮箱数 |
| `unique_emails` | 扫描结果里的唯一邮箱数 |

不变量：`accounts_active + accounts_sold + accounts_tradable + accounts_unusable + accounts_archive == unique_emails`。

`*_files` 是文件计数口径，可能同一邮箱被多个文件或多个目录重复计入。`accounts_*` 是按邮箱主分类后的账号计数口径，Dashboard 主卡片使用这个口径。

## GET /api/auths/accounts

查询参数：

| 参数 | 取值 | 默认 |
|---|---|---|
| `category` | `active` / `sold` / `tradable` / `unusable` / `archive` / `all` / 空字符串 | 空字符串 |
| `plan_type` | `team` / `plus` / `free` / `unknown` / `all` / 空字符串 | 空字符串 |
| `q` | 邮箱子串 | 空 |
| `has_oauth` | `true` / `false` | 不筛选 |
| `has_session` | `true` / `false` | 不筛选 |
| `page` | `>=1` | `1` |
| `page_size` | `1..200` | `20` |
| `sort` | `email_asc` / `email_desc` / `expired_asc` / `expired_desc` / `category_asc` / `plan_asc` | 实现默认值 |

`category` 为空字符串时隐藏 `archive`，但保留 `active`、`sold`、`tradable`、`unusable`。它不再隐藏非 Team plan。`category=all` 显示全部 bucket。

`plan_type` 为空字符串时不过滤 plan；`plan_type=all` 也不过滤 plan。

返回字段：

| 字段 | 含义 |
|---|---|
| `items` | 当前页账号记录 |
| `total` | 当前筛选后的总记录数 |
| `page` | 当前页 |
| `page_size` | 每页数量 |
| `has_next` | 是否还有下一页 |
| `category` | 后端采用的 category 参数 |
| `plan_type` | 后端采用的 plan_type 参数 |
| `q` | 后端采用的搜索词 |
| `sort` | 后端采用的排序 |
| `facets` | 可选筛选项计数 |
| `stats` | 同 `/api/auths/stats` 统计口径 |

`facets.category` 返回五个 bucket 的计数，忽略当前 category 过滤，但仍受文件扫描结果限制。它使用按邮箱聚合后的主分类口径，不等同于 `*_files` 文件数。

`facets.plan_type` 返回 `team`、`plus`、`free`、`unknown` 四类唯一邮箱计数。

`items` 按邮箱聚合。当前前端依赖这些语义：

- `category`: 所属 bucket
- `email`: 账号邮箱
- `plan_type`: `team` / `plus` / `free` / `unknown`
- `plan_types`: 同邮箱关联文件中的 plan 集合
- `is_team_plan`: `plan_type == "team"`
- `is_limited_view`: 非 Team plan 为 `true`
- `has_oauth`: 是否有 OAuth RT 文件
- `has_session`: 是否有 ChatGPT session 文件
- `expired`: 过期字段，用于 `expired_asc` / `expired_desc`
- `file_count`: 该账号关联文件数

非 Team plan 的记录只供账号管理页只读展示。前端只展示邮箱、plan、OAuth、Session、过期时间和文件数，不打开账号详情抽屉，也不允许危险批量操作。
Auth 文件表整体只做文件盘点和 Team 批量工具，不通过行点击打开 `/api/accounts/{email}` 详情。

`expired_asc` / `expired_desc` 排序会先把 Unix 秒、Unix 毫秒、数字字符串和 ISO 字符串统一成时间戳；缺失或不可解析值排在最后。响应里的 `expired` 保留原始值。

## POST /api/accounts/bulk-action

请求体固定字段：

- `action`: `mark-invalid` / `sell` / `delete` / `remove-team` / `cancel-invite`
- `items`: 每项包含 `email`，Team 成员动作还需要 `type` 和 `user_id`
- `options`: 动作参数。`mark-invalid` 可传 `reason`、`last_error`；`delete` 可传 `sync_cpa_after`
- `confirm`: `false` 时只预览，不写本地或远端；`true` 时执行

返回：

- `action`
- `confirm`
- `preview`
- `results`

`results[]` 固定包含：

- `email`
- `ok`
- `status`: `preview` / `done` / `skipped` / `failed`
- `message`
- `skipped_reason`
- `data`

限制：

- 主号全部拒绝，`skipped_reason=main_account`。
- 非 Team auth 记录只读，`skipped_reason=non_team_plan`。
- `sell` 要求 `accounts.json` 中存在账号、`status=active`、并且存在 OAuth RT 文件。
- `delete`、`remove-team`、`cancel-invite` 会检查 `_playwright_lock`。锁被占用时整个请求返回 `409`。
- 单项失败不会中断后续项，失败项返回 `status=failed`。

不要把 `/api/auths/accounts` 和 `/api/accounts` 混用。前者从 `auths/` 文件系统扫描，服务账号管理页的扁平 auth 文件视图；后者从 `accounts.json` 读账号生命周期模型。
