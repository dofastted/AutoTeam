# Main Automation Flow

> 适用范围：注册 → OAuth → Sentinel 反欺诈 → Persistent Chromium → 批量 CPA → 数据同步与清理

## 1. 概述

AutoTeam 的主自动化流程从 mo-email 邮箱分配开始，经过 ChatGPT 直注注册、Codex OAuth、CPA 上传、Sub2API 同步，最后进入清理、补传和回收。本文只记录自动化层基础设施，包括 OAuth 反欺诈、浏览器保活、自愈、批量脚本和同步阻塞控制，不展开账号四轴状态模型；账号状态真值见 [account-management.md](./account-management.md)。

主入口仍在 `src/autoteam/manager.py` (`cmd_fill`, `cmd_rotate`, `_register_direct_once`) 和 `src/autoteam/cpa_batch.py` (`run_cpa_batch`)。自动化层与账号管理层的边界是：前者负责把浏览器、OAuth、任务和远端同步串起来，后者负责解释账号记录该写成什么状态。

## 2. OAuth Sentinel 反欺诈

OpenAI 现在要求 OTP 和授权继续类请求带 `openai-sentinel-token` 请求头。当前覆盖的 OpenAI 认证端点包括 `src/autoteam/sentinel.py` 顶部注释列出的 `/email-otp/send`、`/email-otp/resend`、`/email-otp/validate`、`/passwordless/send-otp`、`/password/verify`、`/authorize/continue`。缺头时，服务端可能静默丢弃请求，表现为邮箱一直收不到 OTP。

实现集中在 `src/autoteam/sentinel.py`：

- `generate_pow_token(user_agent)`: 生成 `gAAAAAC...` 前缀的 SHA3-512 PoW token。
- `get_sentinel_token(session, device_id, flow, user_agent)`: 先算 PoW，再请求 `https://sentinel.openai.com/backend-api/sentinel/req`，最后把 PoW、Turnstile `dx`、server token、`device_id` 和 `flow` 组装成 JSON 字符串。
- 失败降级：请求 `sentinel.openai.com` 网络异常或返回非 200 时，不抛错，直接退化为只有 `p/id/flow` 的 PoW-only token。

请求头注入在 `src/autoteam/protocol_oauth.py` (`_inject_sentinel_token`) 完成。它从 session 的 `oai-did` cookie 取 `device_id`，取不到时用 `uuid.uuid4()` 兜底，然后在下面 4 个 OAuth 调用点写入 `openai-sentinel-token`：

- `_send_or_resend_otp`
- `_authorize_continue`
- `_login_password_verify`
- `_validate_email_otp`

这个注入层还有一个额外保护：`_inject_sentinel_token` 自己也包了 `try/except`。即使 `get_sentinel_token` 本身抛错，协议 OAuth 主流程也只记 warning，不会因为 sentinel 失败直接中断。

## 3. Persistent Chromium Worker 自愈

持久化 Chromium 的保活和自愈集中在 `src/autoteam/browser_runtime.py`。这层的目标不是简单复用浏览器，而是在 Playwright 引用丢失、线程还活着、profile 锁残留等异常情况下，下一次租约还能自己修回来。

当前关键点：

- `_PersistentBrowserWorker.run()`: 执行前同时检查 `thread.is_alive()` 和 `playwright is not None`。任一不满足都会抛 `BrowserLeaseError`，并把原因写进 `"持久化 Chromium worker 未就绪: ..."`，其中丢失 Playwright 引用时的明确字样是 `"Playwright 引用已丢失"`。
- `_persistent_keepalive_is_alive()`: 不再只看线程活没活。若 `_PersistentBrowserWorker` 仍在跑，但 `worker.playwright is None`，会直接判定 keepalive 已死。
- `BrowserLease.__enter__()`: 获取租约后立刻调用 `_heal_stale_persistent_keepalive()`。只要当前 `PLAYWRIGHT_USER_DATA_DIR` 对应的旧 keepalive 已失效，就会先 `_discard_stale_persistent_keepalive()`，避免后续拿着坏引用继续复用。
- `PersistentContextBrowser.new_context()`: 创建隔离 context 时，如果遇到 `_looks_like_browser_closed_error` 或 `_looks_like_persistent_worker_dead_error`，会调用 `_restart_persistent_browser_after_disconnect()`，重建同一个 profile 的持久化浏览器，再重试一次 `new_context()`。

相关辅助判断：

- `_looks_like_persistent_worker_dead_error(exc)`: 当前识别 `"持久化 Chromium worker 未就绪"`、`"Playwright 引用已丢失"`、`"worker 线程已退出"`。
- `_discard_stale_persistent_keepalive(user_data_dir)`: 清空 `_PERSISTENT_KEEPALIVE`、停止旧 worker、清理 profile 关联 Chromium 进程和锁文件。

这套自愈逻辑只对持久化 profile 模式生效，也就是设置了 `PLAYWRIGHT_USER_DATA_DIR` 且没有走 `PLAYWRIGHT_BROWSER_CDP_URL` 时的路径。

## 4. 批量删除避免阻塞

`src/autoteam/api.py` (`delete_account`) 现在增加了查询参数 `sync_cpa_after: bool = True`。接口语义没有改掉默认行为：单个删除仍会在末尾按原路径触发一次 CPA 同步。

新增参数是为批量删除场景减阻塞：

- `sync_cpa_after=true`: 默认行为，单个 DELETE 完成后继续尾部 `sync_to_cpa`。
- `sync_cpa_after=false`: 跳过这次尾部同步，适合前端批量操作或脚本连续删多个账号，最后由调用方统一触发一次同步。

代码注释已经把这个边界写在 `src/autoteam/api.py` (`delete_account`) 的 docstring 里。调用方如果选择 `false`，必须自己补回一次最终同步，不然本地删完、远端 CPA 不对账，会留下短暂不一致。

## 5. About-You 注册超时

`src/autoteam/manager.py` 现在把 `_DIRECT_ABOUT_YOU_TIMEOUT_SECONDS` 固定为 `60.0`。它是直注注册流程里 `_complete_direct_about_you(...)` 的默认超时上限，用来限制 about-you 页面填写等待时间。

这个值从 90 秒降到 60 秒的直接影响是：慢代理、Cloudflare 慢页、新页面选择器不稳定时，会更快暴露成超时，而不是长时间挂住一个注册窗口。

## 6. Watchdog 与 Backfill 脚本

| 脚本 | 用途 |
|------|------|
| `scripts/watchdog_rerun_session_only.sh` | 一次性看门狗。默认监控 `RUN_ID=6cd96d6df18a` 的 `cpa-batch` run，状态离开 `running/pending` 后，再查 `/api/tasks` 是否还有 `cpa-batch` 或 `cpa-auth` 运行中任务；确认没有阻塞后，用 `nohup codex exec --dangerously-bypass-approvals-and-sandbox` 触发 `.tmp/codex-runs/rerun-A-only.prompt.md`。日志写 `.tmp/watchdog-rerun-A.log`，硬上限 `POLL_MAX_SECONDS=86400`。 |
| `scripts/backfill_session_only_oauth.sh` | 顺序重跑只有 `session_auth_file`、缺 OAuth RT 的账号。当前轮询任务结果时，已同时接受 `success` 和 `completed` 作为成功状态，并把 `failed` / `error` 视为失败终止条件。 |

`watchdog_rerun_session_only.sh` 是单次脚本，不会常驻重触发。它的目标只是等某一轮 `cpa-batch` 跑完后，把 session-only 的补传批处理接上去。

## 7. 测试覆盖

`tests/unit/test_browser_runtime.py` 这次新增了 2 个针对持久化 worker 自愈的单测：

- `test_persistent_worker_reports_lost_playwright`: 把 `worker.playwright` 手动置空后，确认 `worker.run(...)` 抛 `BrowserLeaseError`，错误串包含 `"Playwright 引用已丢失"`。
- `test_persistent_keepalive_rebuilds_when_worker_loses_playwright`: 先启动一次持久化 profile，再把旧 worker 的 `playwright` 置空并保持线程仍活着；下一次 `acquire_browser_lease(...).launch_chromium(...)` 会重建新 worker，并把 `_PERSISTENT_KEEPALIVE["playwright"]` 切到新的 Playwright 实例。

## 8. 关键约束 / 易错点

1. sentinel token 失败必须降级。`get_sentinel_token(...)` 网络失败或 HTTP 非 200 时只能回 PoW-only token，不能把 OAuth 主链路直接打断。
2. `device_id` 不能为空。`src/autoteam/sentinel.py` (`get_sentinel_token`) 对空 `device_id` 会直接 `raise ValueError`，所以调用侧必须从 `oai-did` cookie 或 `uuid.uuid4()` 兜底。
3. 批量删除选择 `sync_cpa_after=false` 后，调用方要在末尾补一次统一同步。这个参数只是把阻塞移到批次末尾，不是取消同步。
4. 持久化 Chromium 的失活条件不只看线程。worker 线程活着但 `playwright is None`，也必须当成 dead。
5. watchdog 只触发一次。要持续巡检或自动恢复，应该走现有 hook 或另建常驻机制，不能把这个脚本当守护进程。
6. about-you 默认上限只有 60 秒。调试慢链路时如果频繁误超时，要明确知道这是当前代码里的硬限制。

## 9. 相关文档

- [account-management.md](./account-management.md): 账号管理子系统，负责四轴状态、分类和清理口径。
- [browser-and-oauth.md](./browser-and-oauth.md): 浏览器运行、管理员登录、Codex OAuth 和手动 OAuth。
- [sync-targets.md](./sync-targets.md): CPA / Sub2API 正向同步、反向恢复和主号同步。
- [local-development.md](../guides/local-development.md): 本地安装、测试、前端构建和启动命令。
