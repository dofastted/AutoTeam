# 账号生命周期

## 状态

- `active`: 当前在 Team 中，且本地认为可用。
- `exhausted`: 当前在 Team 中，但额度不足，等待移出。
- `standby`: 已不在当前轮转席位中，等待后续复用。
- `pending`: 注册或创建流程尚未完成。
- `sold`: 已售出账号。仍保留 Team 席位，但本地停止轮转、额度检查和远端同步。

状态存储在 `accounts.json`，读写由 `src/autoteam/accounts.py` 负责。

## 已售账号

`src/autoteam/api.py` (`post_sell_account`): 把 active 合格账号标记为 `sold`。

行为：

- 不移出 ChatGPT Team。
- 不删除本地账号记录和本地 auth 文件。
- 写入 `sync_disabled=true`、`sold_at`、`sale_remote_cleanup`。
- 删除当前已启用 CPA / Sub2API 里的同邮箱账号或同名 auth 文件。
- 后续 `sync_account_states` 不会把 `sold` 改回 `active`。

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
