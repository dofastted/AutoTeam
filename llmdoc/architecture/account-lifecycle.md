# 账号生命周期

## 状态

- `active`: 当前在 Team 中，且本地认为可用。
- `exhausted`: 当前在 Team 中，但额度不足，等待移出。
- `standby`: 已不在当前轮转席位中，等待后续复用。
- `pending`: 注册或创建流程尚未完成。
- `sold`: 已售出账号。仍保留 Team 席位，但本地停止轮转、额度检查和远端同步。

状态存储在 `accounts.json`，读写由 `src/autoteam/accounts.py` 负责。

## 业务属性

`usage_status` 独立于 `status`，用于表达账号用途：

- `normal`: 普通轮转账号，不进入 CPA 可售库存。
- `inventory`: CPA 库存账号，可用于云端库存同步。
- `self_use`: 自用账号，远端下架，本地记录和 auth 文件保留。
- `sold`: 已售出账号，远端下架，本地记录和 auth 文件保留。

新账号创建时默认是 `normal`。批量 CPA 上传成功后，`src/autoteam/cpa_batch.py` (`_verify_and_upload_cpa`) 会写 `cpa_status=success` 和 `usage_status=inventory`。

## 已售账号

`src/autoteam/api.py` (`post_sell_account`): 把 active 合格账号标记为 `sold`。

行为：

- 不移出 ChatGPT Team。
- 不删除本地账号记录和本地 auth 文件。
- 写入 `usage_status=sold`、`sync_disabled=true`、`sold_at`、`sale_remote_cleanup`。
- 删除当前已启用 CPA / Sub2API 里的同邮箱账号或同名 auth 文件。
- 后续 `sync_account_states` 不会把 `sold` 改回 `active`。

## 邮件失效账号

`src/autoteam/account_deactivation.py` (`check_deactivated_mail`): 读取邮箱 provider 的收件箱，查找包含 `deactivated` 的邮件。

行为：

- 默认只检查未标记失效、未售出、自用且未禁用同步的账号。
- 传入 `directory=auths/unusable/account_deactivated` 时，会直接从目录中的 `codex-*.json` 读取邮箱清单，即使本地账号已被标记失效也会参与 dry-run 校对。
- 命中后会写入 `status=unavailable`、`sync_disabled=true`、`unavailable_reason=account_deactivated`、`unavailable_at`。
- 同时写入 `deactivated_mail_checked_at`、`deactivated_mail_evidence`、`mailbox_retired`、`mailbox_retired_at`。
- `apply=true` 时，active / exhausted 账号会尝试从 Team 移出。
- 邮箱 provider 若支持删除，会尝试删除对应邮箱账户；Mo Email 当前没有删除邮箱接口，只会保留本地记录。

## 自用账号

`src/autoteam/api.py` (`post_self_use_account`): 把 active 账号标记为自用。

行为：

- 不移出 ChatGPT Team。
- 不删除本地账号记录和本地 auth 文件。
- 写入 `usage_status=self_use`、`sync_disabled=true`、`self_use_at`、`self_use_remote_cleanup`。
- 删除当前已启用 CPA / Sub2API 里的同邮箱账号或同名 auth 文件。
- 不计入 CPA 云端库存目标。

## 额度检查

`src/autoteam/manager.py` (`cmd_check`): 遍历未禁用同步的 active 账号认证文件，调用 `src/autoteam/codex_auth.py` (`check_codex_quota`) 查询额度。额度不足时会写入 `last_quota`、`quota_exhausted_at`、`quota_resets_at`，并把账号标记为 `exhausted`。`sold` 不参与额度检查。

## 智能轮转

`src/autoteam/manager.py` (`cmd_rotate`): 使用 Team 总人数目标，而不是本地账号数量。

主要步骤：

1. `sync_account_states` 同步 Team 实际状态。
2. `cmd_check` 检查 active 账号额度。
3. 将 exhausted 账号从 Team 移出并改为 standby。
4. 统计当前 Team 人数。
5. 优先复用 standby 账号。
6. 仍有空位时创建新账号。
7. 任务结束后调用已启用远端同步。

复用旧账号走 `src/autoteam/manager.py` (`reinvite_account`)。只有 Codex OAuth 返回 `plan_type=team` 时，旧账号才会恢复为 active。

## 补满成员

`src/autoteam/manager.py` (`cmd_fill`): 未传目标时，当前人数加 `FILL_BATCH_SIZE` 作为本次目标，且不超过 `TEAM_TARGET_SEATS`。默认 `FILL_BATCH_SIZE=10`。

显式传入更大目标时，流程仍按 `FILL_BATCH_SIZE` 记录每批结果，并在每批后同步 CPA / Sub2API。

## 清理成员

`src/autoteam/manager.py` (`cmd_cleanup`): 只清理本地管理的账号，避免误删 owner 或外部成员。未传上限时使用 `TEAM_TARGET_SEATS`。

## 自动巡检

`src/autoteam/api.py` (`_auto_check_loop`): 后台定时检查 active 账号额度和 Team 实际人数。触发条件由 `AUTO_CHECK_INTERVAL`、`AUTO_CHECK_THRESHOLD`、`AUTO_CHECK_MIN_LOW` 和 `TEAM_TARGET_SEATS` 控制。
