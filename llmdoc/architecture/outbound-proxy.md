# 出口代理

`src/autoteam/outbound_proxy.py`: 统一处理后端外部 HTTP 出口代理。

## 默认行为

- `OUTBOUND_PROXY_ENABLED=true`: 默认启用。
- `OUTBOUND_PROXY_POOL=http://127.0.0.1:10808`: 默认使用 Windows Clash HTTP 代理。
- `OUTBOUND_PROXY_BYPASS=localhost,127.0.0.1,::1`: 本地地址默认直连。
- `OUTBOUND_PROXY_STRATEGY=task-sticky`: 一次任务内固定一个代理。
- `OUTBOUND_PROXY_FAILOVER=true`: 网络失败后尝试下一个代理。
- `PROXY_NODE_PROVIDER=webshare`: 可选代理节点接口。启用后可从 Webshare 拉取 / refresh 节点，并写入 `OUTBOUND_PROXY_POOL`。

支持的代理值：

- `http://host:port`
- `https://host:port`
- `socks5://host:port`
- `socks5h://host:port`
- `direct` 或 `none`

## 使用范围

这些外部请求会使用 `src/autoteam/outbound_proxy.py`：

- `src/autoteam/codex_auth.py`: Codex token 交换、额度查询、refresh。
- `src/autoteam/cloudmail.py`、`src/autoteam/mo_email.py`、`src/autoteam/cloudflare_temp_email.py`: 邮箱服务 API。
- `src/autoteam/cpa_sync.py`: CPA 管理 API。
- `src/autoteam/sub2api_sync.py`: Sub2API 管理 API。
- `src/autoteam/api.py`: 用缓存 token 读取 Team 成员。
- `src/autoteam/setup_wizard.py`: 配置连通性验证。

`src/autoteam/codex_hook.py` 也使用同一工具，但它访问 `http://127.0.0.1:8787`，按默认绕过规则直连本地 API。

## 代理节点接口

`src/autoteam/proxy_nodes.py`: 迁移自 `Gpt-Agreement-Payment/pipeline.py` 的 Webshare 节点 API 能力。

确认行为：

- `GET /api/proxy-nodes/status`: 读取节点接口配置、当前节点和最近一次刷新结果。
- `POST /api/proxy-nodes/refresh`: 调用 Webshare 当前节点、替换额度、refresh、轮询新节点，然后按 `PROXY_NODE_PROTOCOL` 生成 `http` / `socks5` / `socks5h` 代理 URL。
- `PROXY_NODE_APPLY_TO_OUTBOUND_POOL=true` 时，把生成的代理 URL 写入当前进程的 `OUTBOUND_PROXY_POOL`。
- `PROXY_NODE_AUTO_REFRESH=true` 且 `PROXY_NODE_REFRESH_BEFORE_TASK=true` 时，`src/autoteam/api.py` (`_run_task`) 会在任务进入 `task_proxy_context` 前刷新节点。
- 自动巡检每轮检查前也会尝试刷新节点；失败只记录警告，不阻断本轮检查。

## Playwright

`src/autoteam/config.py` (`get_playwright_launch_options`): 若 `PLAYWRIGHT_PROXY_URL` 未设置，浏览器使用当前任务选中的出口代理。若设置了 `PLAYWRIGHT_PROXY_URL`，以 Playwright 专用配置为准。

`PLAYWRIGHT_PROXY_BYPASS` 未设置时默认 `localhost,127.0.0.1`，避免 OAuth 本地回调被代理拦截。

## 任务固定

`src/autoteam/api.py` (`_run_task`): API 后台任务进入 `task_proxy_context` 后再执行业务函数。

`src/autoteam/manager.py` (`main`): CLI 命令在执行前进入 `task_proxy_context`。

`src/autoteam/cpa_batch.py`: 批量直注 worker 和 CPA 上传 worker 使用 `task_proxy_context`，同一 worker 内固定同一个代理。

## 失败切换

只在连接失败、代理失败、超时这类网络错误时尝试下一个代理。HTTP 401/403、账号失效、CPA/Sub2API 鉴权失败不是代理失败，不触发切换。

RT 恢复的 OAuth 阶段也使用同一代理池。`src/autoteam/api.py` (`_run_rt_recovery_oauth_with_retry`) 每次 attempt 会显式继承当前任务代理；网络、代理、超时类错误会切换到 `OUTBOUND_PROXY_POOL` 的下一个代理后重试。默认只有 1 次 attempt，需要多代理重试时必须显式设置 `RT_RECOVERY_OAUTH_RETRY_ATTEMPTS` 或 `RT_RECOVERY_STEP_RETRY_ATTEMPTS`。账号语义错误不切换代理，包括 `account_deactivated` / `deleted`、`phone_required`、`HTTP 401`、`invalid_username_or_password`、`password_rejected`、`login_rejected`、未注册、注册未完成和无有效组织。

Python `requests` 使用 `socks5` 或 `socks5h` 时需要 SOCKS 依赖。缺失时会报出可执行提示：安装 `requests[socks]` 或改用 HTTP 代理。
