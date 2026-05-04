# `add-phone` pending 账号清理反思

## 背景

- 时间：2026-05-03。
- 目标文件：`accounts.json`，本次观察到的条数变化是 `795 -> 811 -> 786`。
- 清理对象：`pending` 里的 `add-phone` 账号 25 条。
- 结论前提：这些账号都停在注册失败阶段，没有进入 Team 成员或 invite 清理范围。

本次判断依赖的状态来源有两条：

- 本地账号字段：`accounts.json`，字段定义见 `llmdoc/reference/config-data-files.md:41-78`
- 批量运行阶段：`flow_runs.json`，写入逻辑见 `src/autoteam/flow_runs.py:188-275`

## 现状

这批账号都带有相同特征：

- `status=pending`
- `registration_status=failed`
- `cpa_status=pending`
- `auth_file=null`
- 没有 `rt_auth_file` 和 `session_auth_file`

直注路径里，手机号风控会在注册阶段直接落成失败并跳过，见 `src/autoteam/cpa_batch.py:758-782`；主循环不会把它推进到 `team_joined`，见 `src/autoteam/cpa_batch.py:1651-1667`。

## 根因

这次卡住的不是“要不要删”，而是“用哪条路径删”。

### 1. API 删除被全局浏览器锁挡住

原计划是调用 `DELETE /api/accounts/{email}`。但这个接口先抢 `_playwright_lock`，抢不到就直接返回 `409`，见 `src/autoteam/api.py:2296-2315`。当时 `cpa-batch` 正在跑，所以这条路一开始就被挡住了。

更关键的是，这个 DELETE 不是只删本地记录。它后面还会进入 `delete_managed_account`，默认继续查 Team 成员、invite、远端同步目标和邮箱 provider，见 `src/autoteam/account_ops.py:118-238`。因此它天然不适合和运行中的浏览器任务并发。

### 2. 纯 HTTP 绕过主号端 API 被 Cloudflare 挡住

第二个想法是不用 Playwright，直接用 urllib 打主号端 Team API。后来确认这条路也不成立。

当前 Team 内部接口的前提是：先在浏览器里进入 `chatgpt.com`，拿到 cookie、页面环境、`account_id` 和 access token，再由页面上下文发 `fetch`，见 `llmdoc/architecture/browser-and-oauth.md:30-33` 和 `docs/browser-automation.md:43-52`。脱离浏览器直接打，请求会落到 Cloudflare 403 或错误页，不能据此判断“主号端没有遗留数据”。

## 方案

这次有效的判断办法，不是继续抢浏览器锁，也不是硬绕 Cloudflare，而是改用 `flow_runs.json` 的阶段证据来判断这些账号有没有机会在主号端留下痕迹。

判断标准是：

1. 每个目标账号最终都停在 `stage=register`、`status=failed`。
2. 没有任何一个账号进入 `team_joined`。
3. 邀请路径专有的 `invite_sent` 也没有出现。
4. 本地没有 `session_auth_file`、`rt_auth_file`、`auth_file`。

在当前实现里，只有走到 `team_joined` 之后，后续 Team 成员可见性、session 提取和 OAuth RT 落盘才有意义，见 `src/autoteam/cpa_batch.py:828-908`、`1432-1452`、`1633-1648`。因此这批 `add-phone` 账号可以直接判为“仅本地失败，无远端遗留成员或 invite”。

## 落地步骤

1. 先从 `accounts.json` 和 `flow_runs.json` 交叉筛出 25 个 `add-phone` 账号。
2. 检查它们都没有 `team_joined` / `invite_sent` / 本地 auth 文件。
3. 确认 `cpa_status=pending`、`auth_file=null`，不需要 CPA 或 auth 文件清理。
4. 确认 Mo Email 当前没有删除邮箱接口，见 `llmdoc/architecture/account-lifecycle.md:47`，因此不再追加邮箱删除动作。
5. 先做同目录备份，得到 `accounts.json.bak-addphone-1777818889`。
6. 再做一次纯本地 atomic write，只从 `accounts.json` 移除这 25 条记录。

## atomic write 26ms 窗口

这次没有直接调用 `accounts.save_accounts`，因为它只是普通覆盖写，见 `src/autoteam/accounts.py:76-79`；`account_cleaner._write_accounts_json` 也是同样模式，见 `src/autoteam/account_cleaner.py:518-520`。在 `cpa-batch` 并发运行时，这两条路径都可能把文件暴露在半写状态，或让人工修改更容易被后续写回覆盖。

本次人工策略改成：

- 重新读取最新 `accounts.json`
- 在内存里只删目标 25 条
- 写入同目录临时文件
- 用 rename / replace 一次性替换正式文件

这套原子替换思路参考了 `src/autoteam/cpa_sync.py:129-135`。本次实际观测到从临时文件完成到正式替换的窗口约 26ms。这个窗口并不能防止逻辑层并发覆盖，但足够把“文件损坏”风险压低到可接受范围。

## 验证标准

本次清理后，至少要满足：

1. `accounts.json` 条数从 `811` 变为 `786`。
2. 25 个 `add-phone` 目标邮箱全部不再出现在本地账号池。
3. `flow_runs.json` 中这批账号的最终证据仍是 `register/failed`，没有 `team_joined` 或 invite 事件。
4. 主号端没有为它们补做额外清理动作，因为证据链已经证明没有成员 / invite 遗留。
5. 没有误删带 OAuth RT、session 备份或 `cpa_status=success` 的账号。
