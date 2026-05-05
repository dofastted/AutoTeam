# 浏览器与 OAuth

## 浏览器运行

`src/autoteam/config.py` (`get_playwright_launch_options`): 统一生成 Chromium 启动参数。

默认行为：

- `PLAYWRIGHT_BROWSER_MODE=hidden` 默认不弹出窗口；`visible` 显示窗口；`embedded` 当前按不弹窗处理。旧 `PLAYWRIGHT_HEADLESS=false` 仍兼容。Chromium 启动时固定带 `--window-position=0,0` 和 `--window-size=1280,800`，可见窗口会出现在屏幕左上角。
- 支持 `PLAYWRIGHT_PROXY_URL`、`PLAYWRIGHT_PROXY_SERVER`、`PLAYWRIGHT_PROXY_USERNAME`、`PLAYWRIGHT_PROXY_PASSWORD`、`PLAYWRIGHT_PROXY_BYPASS`。若 `PLAYWRIGHT_PROXY_URL` 未设置，浏览器会使用 `llmdoc/architecture/outbound-proxy.md` 里的当前任务出口代理。
- `src/autoteam/browser_runtime.py` (`acquire_browser_lease`): 默认只允许一个 Chromium 流程；账号补满、轮转和直注批量任务可按 `BROWSER_PARALLEL_WORKERS=1..3` 临时开放多个独立 Chromium 槽位。异常退出会关闭浏览器并释放自己的槽位。
- 浏览器流程常写入 `screenshots/` 作为排查证据。

API 模式下，Playwright 相关操作通过 `src/autoteam/api.py` (`_PlaywrightExecutor`) 放到专用线程执行，并由 `_playwright_lock` 限制业务任务并发；单个任务内部的新号创建可使用多个独立浏览器 worker。

## 管理员登录

`src/autoteam/chatgpt_api.py` (`ChatGPTTeamAPI`): 管理员浏览器会话和 ChatGPT Team 内部接口的核心对象。

它负责：

- 启动 Chromium。
- 进入 `chatgpt.com`。
- 注入或获取管理员 session。
- 选择 Team workspace。
- 在页面上下文调用 ChatGPT 内部 API。

登录态保存到 `state.json`，由 `src/autoteam/admin_state.py` 管理。

## Team 内部接口

`src/autoteam/chatgpt_api.py` (`_api_fetch`): 在浏览器页面上下文里调用 `https://chatgpt.com{path}`。它依赖浏览器 cookie、页面环境、account id 和 access token，不是普通 requests 客户端。

相关调用由 `src/autoteam/account_ops.py`、`src/autoteam/manager.py` 和 `src/autoteam/api.py` 使用。

## Codex OAuth

`src/autoteam/codex_auth.py`: 负责 PKCE、OAuth URL、token 交换、ChatGPT session 凭证提取、认证文件保存、额度查询和 refresh。

`src/autoteam/protocol_oauth.py`: 账号池自动 RT 获取模块。`run_protocol_oauth_login_with_browser_context` 复用已登录的注册浏览器上下文打开 PKCE Codex OAuth 链接，拦截 `http://localhost:1455/auth/callback` 后用 `/oauth/token` 换取 `refresh_token`。`run_protocol_oauth_login` 保留为后备协议链路，用 HTTP session、邮箱 OTP、PKCE authorize 和 `/oauth/token` 获取 RT。HTTP client 优先使用 `curl_cffi`，不可用时退回 `requests`；两者都不继承系统代理，默认使用 `outbound_proxy.current_proxy_url()`。

账号池 OAuth 后备入口是 `src/autoteam/account_oauth.py` (`run_account_oauth_login`)。它读取账号邮箱、密码、邮箱 provider、`mail_account_id` 和已有 `session_auth_file` 中的 `session_token` / `cookie_header`，调用 `protocol_oauth.run_protocol_oauth_login`，成功后继续用 `codex_auth.save_auth_file(..., source="oauth")` 写入 OAuth RT 文件。

批量直注账号优先使用 `build_chatgpt_session_auth_bundle`。直注注册完成并进入 Team 后，`src/autoteam/manager.py` (`_register_direct_once`) 会先访问 `https://chatgpt.com/admin/members`，确认 workspace 已创建且成员页可访问，再在关闭同一个浏览器前读取 `https://chatgpt.com/api/auth/session` 的 `accessToken` 和 session cookie，保存为 ChatGPT Web session 备份。该备份写入 `session_auth_file`，普通同步不能上传它。

批量 CPA 路径要求拿到 session bundle。`src/autoteam/cpa_batch.py` (`_create_direct_account`) 只执行一次当前邮箱注册；浏览器异常、`https://chatgpt.com/api/auth/error`、未识别邮箱步骤、`admin/members` 不可访问或 session 提取失败都会让当前邮箱失败并换下一个邮箱，不再用 Team 成员检查作为兜底。注册后的 workspace / organization 页由 `src/autoteam/chatgpt_api.py` (`complete_workspace_selection`) 处理，直注和邀请注册都会先尝试进入可用 Team workspace，避免后续 Codex OAuth 报 `no_valid_organizations`。

直注注册窗口会在 `admin/members` 可访问后打开 PKCE Codex OAuth 链接。浏览器已带 ChatGPT 登录态，`src/autoteam/protocol_oauth.py` (`run_protocol_oauth_login_with_browser_context`) 通过 callback URL 取 code，再调用 token endpoint 生成 `auths/codex-{email}-team-{hash}-oauth.json`。同一阶段也保存 `auths/codex-{email}-team-{hash}-session.json` 作为 ChatGPT Web session 备份。后续 CPA worker 只有在缺少 OAuth RT 文件时才调用 `run_account_oauth_login` 后备。

直注批量并行由 `src/autoteam/cpa_batch.py` (`_create_direct_accounts_parallel`) 调度。每个 worker 使用独立邮箱客户端和独立 Chromium 槽位，按 `BROWSER_PARALLEL_WORKERS=1..3` 分配目标数；该路径不会调用 `src/autoteam/manager.py` (`_create_new_accounts_parallel`)。

主号 OAuth 入口是 `SessionCodexAuthFlow`、`MainCodexLoginFlow`、`MainCodexSyncFlow`。主号认证文件保存为 `auths/codex-main-*.json`，不进入账号池。

## 手动 OAuth

`src/autoteam/manual_account.py` (`ManualAccountFlow`): 不启动 Chromium。它只生成 OAuth 链接，尝试监听 `http://localhost:1455/auth/callback`，也支持用户粘贴最终 callback URL。

完成后会保存 OAuth RT 文件，按 `plan_type` 和额度结果更新本地账号状态。它不自动同步 CPA / Sub2API；远端上传由同步中心或对应同步接口单独触发。

`src/autoteam/api.py` (`post_account_login`): 仪表盘的单账号登录按钮使用本地 OAuth 验证账号。该接口只要求账号对应邮箱 provider 配置，不要求 CPA / Sub2API 配置；成功后写 `auth_file`、`rt_auth_file`，并保留已有 `session_auth_file`。默认拒绝已售出或 `sync_disabled=true` 的账号；排查已标记失效账号时可显式传 `force=true` 重新跑本地 OAuth 验证。若 OAuth 页面返回 `account_deactivated`，账号会写为 `status=unavailable`、`sync_disabled=true`、`unavailable_reason=account_deactivated`。

## 账号池 RT 恢复

`src/autoteam/account_rt_recovery.py`: 扫描缺 RT 或 401 需要重取 RT 的已注册账号，排除主号、已售、未注册和无密码账号。

`src/autoteam/api.py` (`POST /api/accounts/rt-recovery/start`): RT 恢复是人工启动的后台任务，不会自动上传 CPA / Sub2API。每个账号按固定顺序处理：

- `src/autoteam/mo_email.py` (`MoEmailClient.recreate_permanent_email`): 先按原邮箱 local-part 重建 MoEmail 邮箱，`expiryTime=0`，并写回新的 `mail_account_id`。
- `src/autoteam/account_deactivation.py` (`check_deactivated_mail`): 只查当前邮箱的邮件，命中 `Deactivated` / `deactivated` 时写 `status=unavailable`、`sync_disabled=true`、`unavailable_reason=account_deactivated`。
- Deactivated 命中后，通过 `src/autoteam/api.py` (`_team_remover_factory`) 复用 `src/autoteam/manager.py` (`remove_from_team`) 释放 Team 席位，然后停止当前账号，不再跑 OAuth。
- 未命中 Deactivated 时，才调用 `src/autoteam/account_oauth.py` (`run_account_oauth_login`) 获取新的 OAuth RT。

邮箱重建、Deactivated 查信和 OAuth 阶段都由 `src/autoteam/api.py` (`_run_rt_recovery_step_with_retry`) 包总超时和代理重试；OAuth 保留兼容入口 `_run_rt_recovery_oauth_with_retry`：

- `RT_RECOVERY_STEP_TIMEOUT_SECONDS` 控制邮箱重建和 Deactivated 查信单次 attempt 总等待时间。未设置时沿用 `RT_RECOVERY_OAUTH_TIMEOUT_SECONDS`，再未设置默认 60 秒。
- `RT_RECOVERY_STEP_RETRY_ATTEMPTS` 控制邮箱重建和 Deactivated 查信 attempt 次数。未设置时沿用 `RT_RECOVERY_OAUTH_RETRY_ATTEMPTS`，再未设置默认 1 次，范围 `1..10`。
- `RT_RECOVERY_OAUTH_TIMEOUT_SECONDS` 控制单次 OAuth attempt 总等待时间，默认 60 秒。
- `RT_RECOVERY_OAUTH_RETRY_ATTEMPTS` 控制单账号最多 OAuth attempt 次数，默认 1 次，范围 `1..10`。
- 单次 attempt 超时后当前账号记为失败或进入下一次代理重试，批量任务不会卡住后续账号。
- 只有网络、代理、超时类错误会调用 `outbound_proxy.rotate_task_proxy()` 切换出口代理后重试。
- `account_deactivated` / `deleted`、`phone_required`、`HTTP 401`、`invalid_username_or_password`、`password_rejected`、`login_rejected`、未注册、注册未完成、无有效组织等账号语义错误不会触发代理重试。

邮箱重建、查信或 OAuth 任一步失败时，账号会记录 `last_rt_recovery_error` 和 `last_rt_recovery_failed_at`。批量启动前仍需要人工确认，因为该流程会访问邮箱、启动 OAuth，并可能改变 Team 成员。
