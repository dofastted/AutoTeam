# 账号状态四轴参考

适用范围：四轴状态枚举、旧 `status` 迁移、`category` 聚合规则。

先读 `llmdoc/architecture/account-management.md`。这篇只保留查表和硬约束。

## 1. 四轴枚举

### registration_status

定义：`src/autoteam/account_models.py:15-31`

| 值 | 含义 |
|---|---|
| `planned` | 仅建档或尚未开始注册 |
| `mail_created` | 邮箱已创建 |
| `registering` | 正在注册流程中 |
| `registered` | 注册完成 |
| `register_failed` | 注册失败 |
| `abandoned` | 放弃继续处理 |

### health_status

定义：`src/autoteam/account_models.py:34-54`

| 值 | 含义 |
|---|---|
| `unknown` | 还没有确定健康结论 |
| `valid` | 当前认为可用 |
| `quota_exhausted` | 额度耗尽 |
| `auth_expired` | 认证过期 |
| `invalid` | 失效 |
| `deactivated` | 账号被停用 |
| `risk_blocked` | 风控阻断 |
| `sync_error` | 远端同步异常 |

### usage_status

定义：`src/autoteam/account_models.py:57-75`

| 值 | 含义 |
|---|---|
| `normal` | 普通账号 |
| `inventory` | 库存账号 |
| `in_use` | 已分配使用中 |
| `reserved` | 预留 |
| `sold` | 已售 |
| `self_use` | 自用 |
| `quarantine` | 隔离 |

### team_status

定义：`src/autoteam/account_models.py:78-96`

| 值 | 含义 |
|---|---|
| `unknown` | 未知 |
| `active` | 当前在 Team 中 |
| `standby` | 待复用 |
| `pending_invite` | 等待邀请 |
| `removed` | 已移出 |
| `external` | 外部成员 |
| `owner` | Team owner |

## 2. 旧 status 迁移规则

旧状态转四轴的入口是 `src/autoteam/account_models.py:213-234` 的 `legacy_status_to_axes`，账号文件迁移在 `src/autoteam/account_store.py:249-304`。

| 旧 status | 当前迁移结果 |
|---|---|
| `active` | `team_status=active` |
| `standby` | `team_status=standby` |
| `exhausted` | `health_status=quota_exhausted`，`team_status=active` |
| `sold` | `usage_status=sold`，`sync_disabled=true` |
| `pending` | `registration_status=registering` |
| `unavailable` | `health_status=deactivated` 或 `invalid`，取决于 `unavailable_reason` 是否包含 `deactivated` |

补充规则：

- 如果旧记录已有 `registration_status` / `health_status` / `usage_status` / `team_status`，迁移时优先保留现值，见 `src/autoteam/account_store.py:72-120`
- `auth_file` 会按文件特征拆进 `session_auth_file` 或 `rt_auth_file`，见 `src/autoteam/account_store.py:60-69`
- `cpa_status=success` 或存在 OAuth RT 文件时，注册状态会被补成 `registered`，见 `src/autoteam/account_store.py:72-80`

## 3. category 派生

派生入口：`src/autoteam/account_classifier.py:47-65`

当前分类值：

- `registered`
- `inventory`
- `in_use`
- `invalid`
- `sold`
- `not_registered`

当前代码顺序是：

1. `sold`
2. `invalid`
3. `not_registered`
4. `in_use`
5. `inventory`
6. `registered`

这是当前仓库真实实现，原因是 `registration_status != registered` 的判断写在 `in_use` / `inventory` 之前，见 `src/autoteam/account_classifier.py:54-64`。

库存分类不是只看 `usage_status=inventory`。还要同时满足：

- `cpa_status=success`
- `health_status=valid`
- `rt_auth_file` 存在
- `sync_disabled` 不是真

见 `src/autoteam/account_classifier.py:58-63`。

## 4. 业务约束与当前实现的差异

产品约束要求 `category` 讨论库存视图时守住这个优先级：

1. `sold`
2. `invalid`
3. `in_use`
4. `inventory`
5. `registered`
6. `not_registered`

当前代码还没有完全做到这一点，因为 `not_registered` 提前于 `in_use` / `inventory`。如果后续要统一文档、接口和前端心智，先改 `src/autoteam/account_classifier.py` 和对应测试，再改这里。

## 5. 硬约束

- `sold > invalid > in_use > inventory > registered > not_registered` 是业务讨论和后续对齐时不能改顺序的目标优先级
- `quota_exhausted` 不等于 `invalid`。额度耗尽只会写 `health_status=quota_exhausted`，不会自动 `sync_disabled=true`，见 `src/autoteam/account_health.py:118-146`
- 主号不能进库存流，见 `src/autoteam/account_inventory.py:103-120`、`src/autoteam/account_inventory.py:185-210`、`src/autoteam/account_inventory.py:270-277`
- `AT-013` 兼容补丁当前在 `src/autoteam/account_lifecycle.py:24`：`legacy_accounts.REGISTRATION_STATUS_SUCCESS = REGISTRATION_REGISTERED`。后续如果要删，先审计 `accounts.REGISTRATION_STATUS_SUCCESS` 的调用点
