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

`src/autoteam/manager.py` (`cmd_check`): 遍历未禁用同步的 active 账号 OAuth RT 文件，调用 `src/autoteam/codex_auth.py` (`check_codex_quota`) 查询额度。`session_auth_file` 不参与额度检查。额度不足时会写入 `last_quota`、`quota_exhausted_at`、`quota_resets_at`，并把账号标记为 `exhausted`。`sold` 不参与额度检查。

## 智能轮转

`src/autoteam/manager.py` (`cmd_rotate`): 使用 Team 总人数目标，而不是本地账号数量。

主要步骤：

1. `sync_account_states` 同步 Team 实际状态。
2. `cmd_check` 检查 active 账号额度。
3. 将 exhausted 账号从 Team 移出并改为 standby。
4. 统计当前 Team 人数。
5. 优先复用 standby 账号。
6. 仍有空位时创建新账号。
7. 任务结束后把本地 OAuth RT 文件上传到已启用远端。

复用旧账号走 `src/autoteam/manager.py` (`reinvite_account`)。只有 Codex OAuth 返回 `plan_type=team` 时，旧账号才会恢复为 active。

## 补满成员

`src/autoteam/manager.py` (`cmd_fill`): 未传目标时，当前人数加 `FILL_BATCH_SIZE` 作为本次目标，且不超过 `TEAM_TARGET_SEATS`。默认 `FILL_BATCH_SIZE=10`。

显式传入更大目标时，流程仍按 `FILL_BATCH_SIZE` 记录每批结果，并在每批后把本地 OAuth RT 文件上传到 CPA / Sub2API。

## 清理成员

`src/autoteam/manager.py` (`cmd_cleanup`): 只清理本地管理的账号，避免误删 owner 或外部成员。未传上限时使用 `TEAM_TARGET_SEATS`。

## 自动巡检

`src/autoteam/api.py` (`_auto_check_loop`): 后台定时检查 active 账号额度和 Team 实际人数。触发条件由 `AUTO_CHECK_INTERVAL`、`AUTO_CHECK_THRESHOLD`、`AUTO_CHECK_MIN_LOW` 和 `TEAM_TARGET_SEATS` 控制。

## 故障原因分类

本节只归纳当前 `pending` / `unavailable` 账号里反复出现、且已能从代码路径解释的失败类型。字段来源见 `src/autoteam/accounts.py:16-37`、`src/autoteam/cpa_batch.py:616-623`、`src/autoteam/flow_runs.py:188-275` 和 `llmdoc/reference/config-data-files.md:41-89`。

### pending 七类

1. 网络 `ERR_CONNECTION_RESET` / `ERR_CONNECTION_CLOSED` / `ERR_CONNECTION_ABORTED`

- 常见表现：浏览器页或注册线程在 `register` 阶段直接断开，请求未进入稳定页面。
- 代码落点：`src/autoteam/cpa_batch.py:783-799` 会把这类异常落成 `registration_status=failed`、`flow_stage=register`；任务出口代理切换策略见 `llmdoc/architecture/outbound-proxy.md`。
- 处理建议：可重试。先看当前出口代理，再决定是否切换节点或重开批次。

2. OpenAI 创建账号命中 IP 风控

- 常见表现：密码页附近失败，报错为 `Failed to create account on password page` 一类。
- 代码落点：`src/autoteam/cpa_batch.py:723-757` 会把它归为 IP 风控，并按当前任务代理触发轮换。
- 处理建议：可重试。先换出口 IP，再继续直注；不要直接删账号样本。

3. OpenAI 风控要求手机号验证 `add-phone`

- 常见表现：注册阶段明确要求手机号验证，任务被当场跳过。
- 代码落点：`src/autoteam/cpa_batch.py:758-782` 抛 `AccountPhoneVerificationSkipped`，账号状态会停在 `registration_status=failed`、`flow_stage=register`；主循环只累计失败并继续，见 `src/autoteam/cpa_batch.py:1651-1667`。
- 处理建议：直接删除本地记录。若 `flow_runs.json` 里从未进入 `team_joined` 或 `invite_sent`，说明它没有主号端遗留成员或邀请，不值得保留待重试。

4. 直注未完成

- 常见表现：没有明确风控或网络错误，但注册没有走完，账号停在 `pending`，也拿不到 session / OAuth RT。
- 代码落点：`src/autoteam/cpa_batch.py:802-811` 会把“直注注册未完成”写成失败；`src/autoteam/cpa_batch.py:616-623` 说明这类账号通常只停在 `email_created` 或 `register`。
- 处理建议：先看 `flow_runs.json` 的 `stage` 和 `events`。若没有进入 `team_joined`，可按失败注册清理；若已进入 `team_joined`，先查主号端成员 / invite 再删。

5. `greenlet` / `asyncio` 跨线程异常

- 常见表现：持久 Chromium worker 退出、同步 API 误用、线程边界被打穿后，注册线程提前失败。
- 代码落点：API 模式的浏览器任务本来应受 `_playwright_lock` 和 `_PlaywrightExecutor` 保护，见 `src/autoteam/api.py:2296-2339`、`llmdoc/architecture/browser-and-oauth.md:14`。一旦跨线程误用，最终仍会在 `src/autoteam/cpa_batch.py:783-799` 落成注册失败。
- 处理建议：这是代码 bug，不是账号问题。不要靠反复重试掩盖，应该补线程模型和浏览器生命周期修复。

6. `email-verification` 验证码错误或超时

- 常见表现：邮箱验证码页卡住、验证码不对、邮件到达太慢。
- 代码落点：注册主流程在 `src/autoteam/manager.py`，失败后仍由 `src/autoteam/cpa_batch.py:783-799` 归并成注册失败；邮箱轮询和 provider 边界见 `llmdoc/reference/config-data-files.md:13-18`。
- 处理建议：可重试。先确认邮箱 provider 正常、验证码等待时间够用，再决定是否重开。

7. 其他 OAuth callback / 收尾异常

- 常见表现：注册页已经推进，但 `session_auth_file` / `rt_auth_file` 没有落盘，或 callback / token 交换异常。
- 代码落点：直注成功后应先拿 session bundle，再在同一浏览器上下文里做 OAuth，见 `src/autoteam/cpa_batch.py:828-908` 和 `llmdoc/architecture/browser-and-oauth.md:44-48`。
- 处理建议：分两段查。先确认 `admin/members` 和 workspace 是否真的可访问，再查 callback、token 交换和 auth 文件写入。

### unavailable 两类终态

1. `account_deactivated`

- 常见表现：邮箱收到了 OpenAI 停用邮件，账号不再可用。
- 代码落点：`src/autoteam/account_deactivation.py` 会写 `status=unavailable`、`sync_disabled=true` 和 `unavailable_reason=account_deactivated`，文档说明见本页“邮件失效账号”一节。
- 处理建议：视为终态。停止额度检查、轮转和同步；若只是保留证据，可以继续留本地记录。

2. OAuth RT `http_401`

- 常见表现：OAuth RT 刷新明确 401，说明凭证已失效。
- 代码落点：本地 OAuth 文件和同步字段约束见 `llmdoc/reference/config-data-files.md:49-55`、`91-115`；远端 refresh 401 的清理入口见 `src/autoteam/cpa_sync.py:147-150`。
- 处理建议：视为终态，除非要手动重新做 OAuth。对已经 `sync_disabled=true` 的账号，不再进入常规轮转或同步。
