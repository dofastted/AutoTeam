# 运行事实

- 项目根目录是 `/mnt/x/project/AutoTeam`。
- Python 包在 `src/autoteam/`，前端源码在 `web/src/`，前端构建产物写入 `src/autoteam/web/dist/`。
- 启动命令是 `uv run autoteam api`，默认 HTTP 端口是 `8787`。
- Vite 开发服务在 `web/vite.config.js` 中配置端口 `5173`，`/api` 代理到 `http://localhost:8787`。
- 首次启动只强制要求 `API_KEY`。邮箱服务、CPA、Sub2API、代理等运行项在执行对应功能时校验。
- `TEAM_TARGET_SEATS` 是 Team 总人数目标，默认 `999`。`FILL_BATCH_SIZE` 是补满成员每次最多新增账号数，默认 `10`。
- ChatGPT Team 中已有 owner 或外部成员也计入目标人数。轮转目标不是“本地管理账号数”。
- Playwright 默认隐藏运行。`PLAYWRIGHT_BROWSER_MODE=visible` 可显示窗口；`embedded` 当前按不弹窗处理。旧 `PLAYWRIGHT_HEADLESS=false` 仍兼容。配置入口是 `src/autoteam/config.py` (`get_playwright_launch_options`)。
- 后端外部请求默认走出口代理池。`OUTBOUND_PROXY_POOL` 默认 `http://127.0.0.1:10808`，`localhost`、`127.0.0.1`、`::1` 默认直连；任务内固定一个代理，网络失败后可尝试下一个。
- 代理节点接口由 `src/autoteam/proxy_nodes.py` 管理。当前支持 `PROXY_NODE_PROVIDER=webshare`，可通过 `POST /api/proxy-nodes/refresh` 调节点 API 轮询新节点，并按 `PROXY_NODE_PROTOCOL=http/socks5/socks5h` 写入 `OUTBOUND_PROXY_POOL`。`PROXY_NODE_AUTO_REFRESH=true` 时，API 后台任务和自动巡检会在业务动作前先尝试刷新节点。
- `BROWSER_PARALLEL_WORKERS` 控制账号补满、轮转和直注批量任务的新号创建并行窗口数，范围 `1..3`，默认 `1`。API 业务任务仍由 `src/autoteam/api.py` (`_playwright_lock`) 串行调度。
- CPA 批量直注的并行窗口由 `src/autoteam/cpa_batch.py` 自己调度。注册阶段必须先创建邮箱、完成注册入席、确认 `https://chatgpt.com/admin/members` 可访问、拿到 ChatGPT session 备份，并在同一个注册浏览器上下文内完成 Codex PKCE OAuth 生成 OAuth RT 文件；注册后的 workspace / organization 选择页由 `src/autoteam/chatgpt_api.py` (`complete_workspace_selection`) 处理。浏览器错误、认证错误页、成员页不可访问、缺少 session 凭证或缺少 OAuth RT 时，当前邮箱失败并换新邮箱，不做 Team 成员检查兜底。direct worker 调用 `src/autoteam/manager.py` (`_register_direct_once`) 时使用 `cpa_batch.direct.*` 浏览器 owner，并在线程内禁用共享 `PLAYWRIGHT_USER_DATA_DIR`，避免多个 worker 抢同一个持久化 Chromium profile。direct 单窗口 `parallel_workers=1` 时，一个账号完成注册、OAuth RT 文件落盘、CPA 上传和可选 Sub2API 同步后，才会创建下一个账号；`parallel_workers>1` 允许注册并行，CPA worker 不占用注册浏览器槽位。
- CPA 云端上传只使用 OAuth RT auth 文件。`src/autoteam/cpa_batch.py` (`_create_direct_account`) 优先在注册浏览器内通过 `src/autoteam/protocol_oauth.py` (`run_protocol_oauth_login_with_browser_context`) 生成 `-oauth.json`；`_verify_and_upload_cpa` 缺少 RT 文件时才调用 `src/autoteam/account_oauth.py` (`run_account_oauth_login`) 作为后备，随后检查额度并上传 CPA。
- 恢复 CPA 批量任务时，`src/autoteam/flow_runs.py` (`fail_running_flow_accounts`) 会先把该 run 中遗留的账号级 `running` 记录标记为失败。
- `auths/codex-{email}-team-{hash}-session.json` 是 ChatGPT session 备份文件。`auths/codex-{email}-team-{hash}-oauth.json` 是 CPA 使用的 OAuth RT 文件。`auths/codex-main-*.json` 是主号认证文件。
- OAuth RT 文件由 `src/autoteam/codex_auth.py` (`save_auth_file`, `save_main_auth_file`) 写入，由 `src/autoteam/cpa_sync.py` 上传或从 CPA 恢复。ChatGPT session 备份不能上传 CPA / Sub2API。`CPA_URL` 可填 CLIProxyAPI 根地址或管理页 `management.html#/auth-files`，代码会归一化为 API 根地址，HTTP 上传实际调用 `/v0/management/auth-files`。
- 本地巡检 hook 由 `tools/codex-hook/check_and_invoke.py` 执行，运行状态写入 `.autoteam-hook/runtime/campaign.json` 和 `.autoteam-hook/logs/`。安装脚本是 `tools/codex-hook/install_cron.sh`，当前通过用户 `crontab` 每 10 分钟触发一次；它会检查成功账号登记、异步 CPA JSON 是否已进远端，并在需要时恢复或新开批量任务。
