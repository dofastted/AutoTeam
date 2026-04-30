# 浏览器与 OAuth

## 浏览器运行

`src/autoteam/config.py` (`get_playwright_launch_options`): 统一生成 Chromium 启动参数。

默认行为：

- `PLAYWRIGHT_BROWSER_MODE=hidden` 默认不弹出窗口；`visible` 显示窗口；`embedded` 当前按不弹窗处理。旧 `PLAYWRIGHT_HEADLESS=false` 仍兼容。
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

账号池自动 OAuth 入口是 `login_codex_via_browser`。它登录账号后打开 Codex OAuth URL，捕获 callback code，换 token 并保存 CPA 兼容 JSON。

批量直注账号优先使用 `build_chatgpt_session_auth_bundle`。直注注册完成并进入 Team 后，`src/autoteam/manager.py` (`_register_direct_once`) 会在关闭同一个浏览器前读取 `https://chatgpt.com/api/auth/session` 的 `accessToken` 和 session cookie，保存为 CPA 兼容 JSON，避免再进入 Codex OAuth consent/callback 页面。

批量 CPA 路径要求拿到 session bundle。`src/autoteam/cpa_batch.py` (`_create_direct_account`) 只执行一次当前邮箱注册；浏览器异常、`https://chatgpt.com/api/auth/error`、未识别邮箱步骤或 session 提取失败都会让当前邮箱失败并换下一个邮箱，不再用 Team 成员检查作为兜底。

直注批量并行由 `src/autoteam/cpa_batch.py` (`_create_direct_accounts_parallel`) 调度。每个 worker 使用独立邮箱客户端和独立 Chromium 槽位，按 `BROWSER_PARALLEL_WORKERS=1..3` 分配目标数；该路径不会调用 `src/autoteam/manager.py` (`_create_new_accounts_parallel`)。

主号 OAuth 入口是 `SessionCodexAuthFlow`、`MainCodexLoginFlow`、`MainCodexSyncFlow`。主号认证文件保存为 `auths/codex-main-*.json`，不进入账号池。

## 手动 OAuth

`src/autoteam/manual_account.py` (`ManualAccountFlow`): 不启动 Chromium。它只生成 OAuth 链接，尝试监听 `http://localhost:1455/auth/callback`，也支持用户粘贴最终 callback URL。

完成后会保存认证文件，按 `plan_type` 和额度结果更新本地账号状态。它不自动同步 CPA / Sub2API；远端上传由同步中心或对应同步接口单独触发。

`src/autoteam/api.py` (`post_account_login`): 仪表盘的单账号登录按钮使用本地 OAuth 验证账号。该接口只要求账号对应邮箱 provider 配置，不要求 CPA / Sub2API 配置；成功后写 `auth_file`、`rt_auth_file`，并保留已有 `session_auth_file`。若 OAuth 页面返回 `account_deactivated`，账号会写为 `status=unavailable`、`sync_disabled=true`、`unavailable_reason=account_deactivated`。
