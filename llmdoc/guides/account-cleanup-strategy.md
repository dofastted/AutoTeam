# 失败账号清理策略

适用范围：`cpa-batch` 仍在运行、`_playwright_lock` 已被占用、但需要清理一批明确失败账号的场景。

先读 `llmdoc/architecture/account-lifecycle.md`、`llmdoc/architecture/browser-and-oauth.md` 和 `llmdoc/reference/config-data-files.md`。

## 1. 先分清三件事

1. 账号是不是只在本地失败，还没进入 Team。
2. 当前删除动作会不会撞上 API 的全局浏览器锁。
3. 有没有必要访问主号端 Team API 做远端清理。

这些边界分别对应：

- 浏览器任务互斥：`src/autoteam/api.py:2296-2339`
- Team 内部接口必须走浏览器页面上下文：`src/autoteam/chatgpt_api.py` 的 `_api_fetch`，说明见 `llmdoc/architecture/browser-and-oauth.md:30-33`
- 运行记录和阶段证据：`src/autoteam/flow_runs.py:23-40`、`188-275`

## 2. 为什么 `cpa-batch` 运行中不能直接删

`DELETE /api/accounts/{email}` 不是纯本地删记录。它会先抢 `_playwright_lock`，再跑 `delete_managed_account`，后者默认还会查 Team 成员、查 invite、删远端同步目标、删邮箱提供者账号，见 `src/autoteam/api.py:2296-2339` 和 `src/autoteam/account_ops.py:118-238`。

因此只要有 `cpa-batch`、管理员登录、主号 Codex 登录或别的浏览器任务在跑，这个接口就会直接返回 `409`，不是局部失败。

## 3. 不要用纯 HTTP 直打主号 ChatGPT API

Team 成员和 invite 接口不是普通 requests / urllib 客户端。当前实现明确要求先在浏览器里拿到 ChatGPT cookie、页面环境、`account_id` 和 access token，再由页面上下文发 `fetch`，见 `llmdoc/architecture/browser-and-oauth.md:30-33` 和 `docs/browser-automation.md:43-52`。

如果脱离 Playwright 浏览器直接调，常见结果是 Cloudflare 403 或返回非 JSON 登录页。`src/autoteam/account_ops.py:28-43` 已经把这类情况视为鉴权失败或错误页，不应把它当成“主号端没有数据”。

## 4. 并发清理的判断顺序

### 第一步：只挑“注册失败且没入 Team”的账号

优先看这些字段：

- `status=pending` 或 `registration_status=failed`
- `cpa_status=pending`
- `auth_file` / `rt_auth_file` / `session_auth_file` 为空
- `flow_stage=register` 或更早

字段来源见 `llmdoc/reference/config-data-files.md:41-78`。

### 第二步：用 `flow_runs.json` 代替主号端 API 做阶段判断

`flow_runs.json` 每个账号都会记录 `stage`、`status`、`events`，定义见 `src/autoteam/flow_runs.py:188-275`。

清理前重点看：

- 是否从未进入 `team_joined`
- 邀请模式下是否从未进入 `invite_sent`
- 最终是否停在 `register` 且 `status=failed`

如果三项都成立，可以把结论收敛成：账号只在本地注册阶段失败，没有主号端成员或 invite 遗留，不需要为它再启动 Team API 清理。

### 第三步：再决定能不能本地删

只有在确认下面几点后，才适合绕过 API 走纯本地清理：

- 账号从未进入 `team_joined` / `invite_sent`
- 没有 OAuth RT 文件，也没有 session 备份
- `cpa_status` 仍是 `pending`
- 邮箱 provider 本身没有必须同步删除的远端资源，或当前 provider 不支持删除

Mo Email 当前没有删除邮箱接口，边界见 `llmdoc/architecture/account-lifecycle.md:47`。

## 5. 本地 atomic write SOP

当前仓库里，`accounts.save_accounts` 仍是直接 `write_text`，见 `src/autoteam/accounts.py:76-79`；`account_cleaner._write_accounts_json` 也是直接覆盖写，见 `src/autoteam/account_cleaner.py:518-520`。它们都不适合在 `cpa-batch` 并发运行时拿来做人工删记录。

并发清理时，建议按下面顺序：

1. 先复制一份同目录备份，命名沿用现有 `.bak-*` 风格，参考 `src/autoteam/account_cleaner.py:21-37`。
2. 从当前 `accounts.json` 重新读取一次最新内容，不要复用几分钟前的快照。
3. 只移除已经确认是“注册失败且没入 Team”的目标邮箱。
4. 把新内容写到 `accounts.json` 同目录临时文件。
5. 用同目录 rename / replace 一次性替换正式文件。
6. 替换后立刻复读 `accounts.json`，确认条数和目标邮箱集合都正确。

仓库里现成的同目录原子替换例子见 `src/autoteam/cpa_sync.py:129-135`。这套做法的目的不是防止逻辑冲突，而是把“文件处于半写状态”的窗口压到最短。

## 6. 操作后怎么验

至少验四项：

1. `accounts.json` 条数变化符合预期，且目标邮箱已不存在。
2. `flow_runs.json` 里这些账号最终仍停留在 `register/failed`，没有后续 `team_joined` 事件。
3. 目标账号不存在 `rt_auth_file`、`session_auth_file`、`auth_file` 等本地凭证残留。
4. 如果以后要重新开批次，新的失败判断仍以最新 `flow_runs.json` 为准，不复用旧结论。

## 7. 什么时候不要用这套 SOP

下面几种情况不要在 `cpa-batch` 运行期间做纯本地删：

- 账号已经进入 `team_joined`
- 邀请模式下已经出现 `invite_sent`
- 本地已有 `rt_auth_file` 或 `session_auth_file`
- 账号已经是 `active` / `standby` / `inventory`
- 需要同步删除 CPA / Sub2API / Team invite / Team 成员

这些场景应该等浏览器任务空闲后，回到 `DELETE /api/accounts/{email}` 或其它正式 API 路径。
