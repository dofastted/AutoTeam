# 浏览器与 OAuth

## 浏览器运行

`src/autoteam/config.py` (`get_playwright_launch_options`): 统一生成 Chromium 启动参数。

默认行为：

- `headless=False`，会显示浏览器窗口。
- 支持 `PLAYWRIGHT_PROXY_URL`、`PLAYWRIGHT_PROXY_SERVER`、`PLAYWRIGHT_PROXY_USERNAME`、`PLAYWRIGHT_PROXY_PASSWORD`、`PLAYWRIGHT_PROXY_BYPASS`。
- 浏览器流程常写入 `screenshots/` 作为排查证据。

API 模式下，Playwright 相关操作通过 `src/autoteam/api.py` (`_PlaywrightExecutor`) 放到专用线程执行，并由 `_playwright_lock` 限制并发。

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

`src/autoteam/codex_auth.py`: 负责 PKCE、OAuth URL、token 交换、认证文件保存、额度查询和 refresh。

账号池自动 OAuth 入口是 `login_codex_via_browser`。它登录账号后打开 Codex OAuth URL，捕获 callback code，换 token 并保存 CPA 兼容 JSON。

主号 OAuth 入口是 `SessionCodexAuthFlow`、`MainCodexLoginFlow`、`MainCodexSyncFlow`。主号认证文件保存为 `auths/codex-main-*.json`，不进入账号池。

## 手动 OAuth

`src/autoteam/manual_account.py` (`ManualAccountFlow`): 不启动 Chromium。它只生成 OAuth 链接，尝试监听 `http://localhost:1455/auth/callback`，也支持用户粘贴最终 callback URL。

完成后会保存认证文件，按 `plan_type` 和额度结果更新账号状态，并同步到已启用远端。
