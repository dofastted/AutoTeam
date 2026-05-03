# Auth 文件 API 参考

适用范围：`auths/` 文件盘点、账号管理页扁平表、Dashboard auth 文件统计。

## 文件扫描

扫描入口在 `src/autoteam/api.py`。

- 根目录文件名：`auths/codex-{email}-team-{hash}-{oauth|session}.json`
- 分类目录：`auths/sold/`、`auths/tradable/`、`auths/unusable/account_deactivated/`、`auths/archive/`
- 分类目录中文件以 `.json` 结尾，不带 `-oauth` / `-session` 后缀
- 已知 bucket：`active`、`sold`、`tradable`、`unusable`、`archive`
- 同一邮箱可能同时出现在根目录和分类目录。主分类由 `_bucket_primary_category(categories)` 决定，优先级是 `sold` > `tradable` > `unusable` > `archive` > `active`；空集合为 `unknown`。

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
| `q` | 邮箱子串 | 空 |
| `has_oauth` | `true` / `false` | 不筛选 |
| `has_session` | `true` / `false` | 不筛选 |
| `page` | `>=1` | `1` |
| `page_size` | `1..200` | `20` |
| `sort` | `email_asc` / `email_desc` / `expired_asc` / `expired_desc` / `category_asc` | 实现默认值 |

`category` 为空字符串时隐藏 `archive`，但保留 `active`、`sold`、`tradable`、`unusable`。`category=all` 显示全部 bucket。

返回字段：

| 字段 | 含义 |
|---|---|
| `items` | 当前页账号记录 |
| `total` | 当前筛选后的总记录数 |
| `page` | 当前页 |
| `page_size` | 每页数量 |
| `has_next` | 是否还有下一页 |
| `category` | 后端采用的 category 参数 |
| `q` | 后端采用的搜索词 |
| `sort` | 后端采用的排序 |
| `facets` | 可选筛选项计数 |
| `stats` | 同 `/api/auths/stats` 统计口径 |

`facets.category` 返回五个 bucket 的计数，忽略当前 category 过滤，但仍受文件扫描结果限制。它使用按邮箱聚合后的主分类口径，不等同于 `*_files` 文件数。

`items` 按邮箱聚合。当前前端依赖这些语义：

- `category`: 所属 bucket
- `email`: 账号邮箱
- `has_oauth`: 是否有 OAuth RT 文件
- `has_session`: 是否有 ChatGPT session 文件
- `expired`: 过期字段，用于 `expired_asc` / `expired_desc`
- `files`: 该账号关联文件

`expired_asc` / `expired_desc` 排序会先把 Unix 秒、Unix 毫秒、数字字符串和 ISO 字符串统一成时间戳；缺失或不可解析值排在最后。响应里的 `expired` 保留原始值。

不要把 `/api/auths/accounts` 和 `/api/accounts` 混用。前者从 `auths/` 文件系统扫描，服务账号管理页的扁平 auth 文件视图；后者从 `accounts.json` 读账号生命周期模型。前端 `AuthsTable` 只做文件盘点，不直接打开 `/api/accounts/{email}` 详情。
